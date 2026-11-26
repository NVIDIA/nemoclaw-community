# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Command-line entry point: `python3 -m localonly <command>`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import cases as case_table
from . import endpoint, evidence, policy_facts, runner, workspace
from .backends import OpenShellBackend


def _split(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _cmd_check_endpoint(args: argparse.Namespace) -> int:
    try:
        host = endpoint.check_local_endpoint(args.url, _split(args.extra_hosts))
    except endpoint.EndpointRejected as exc:
        print("REJECTED: inference endpoint is not local: %s" % exc, file=sys.stderr)
        return 1
    print("OK: inference endpoint host is local: %s" % host)
    return 0


def _cmd_check_publish_host(args: argparse.Namespace) -> int:
    try:
        host = endpoint.check_publish_host(args.host)
    except endpoint.EndpointRejected as exc:
        print("REJECTED: %s" % exc, file=sys.stderr)
        return 1
    print("OK: publish host: %s" % host)
    return 0


def _report(problems: List[str], subject: str) -> int:
    if problems:
        for problem in problems:
            print("REJECTED: %s" % problem, file=sys.stderr)
        return 1
    print("OK: %s permits egress only to %s" % (subject, ", ".join(sorted(policy_facts.ALLOWED_EGRESS_HOSTS))))
    return 0


def _cmd_check_policy(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8")
    problems = policy_facts.check_policy(text)
    if problems:
        return _report(problems, "sandbox policy file")
    print("OK: sandbox policy file declares no network endpoint")
    return 0


def _cmd_check_profile(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8")
    return _report(policy_facts.check_profile(text, args.base_url), "provider profile")


def _cmd_check_effective_policy(_args: argparse.Namespace) -> int:
    return _report(policy_facts.check_effective_policy(sys.stdin.read()), "effective policy")


def _cmd_list_workspace(args: argparse.Namespace) -> int:
    try:
        files = workspace.list_approved_files(
            Path(args.path), args.max_file_bytes, args.max_files,
        )
    except (workspace.WorkspaceRejected, OSError) as exc:
        print("REJECTED: %s" % exc, file=sys.stderr)
        return 1
    for item in files:
        print("%s\t%s" % (item.relative, item.source))
    return 0


def _cmd_cases(args: argparse.Namespace) -> int:
    for case in case_table.select(args.priority):
        print("%-5s %-3s %-5s %-8s %s" % (
            case.case_id, case.priority, case.expect, case.status, case.title,
        ))
    return 0


def _compose_action(compose_files: List[str], *arguments: str) -> Callable[[], None]:
    file_arguments = [item for path in compose_files for item in ("-f", path)]

    def action() -> None:
        subprocess.run(
            ["docker", "compose", *file_arguments, *arguments],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, timeout=300,
        )
    return action


def _cmd_run(args: argparse.Namespace) -> int:
    host_actions: Dict[str, Callable[[], None]] = {}
    if args.compose_file:
        host_actions["stop_inference"] = _compose_action(args.compose_file, "stop", "ollama")
        host_actions["start_inference"] = _compose_action(
            args.compose_file, "up", "-d", "--wait", "ollama",
        )
    backend = OpenShellBackend(args.sandbox)
    outcomes = runner.run_suite(
        backend, case_table.select(args.priority), host_actions, args.host_trait,
    )
    print(runner.format_table(outcomes))
    if args.evidence:
        evidence.write_jsonl(Path(args.evidence), outcomes, backend.name, args.host_trait)
        print("Evidence written to %s" % args.evidence)
    status = runner.exit_status(outcomes)
    print({0: "RESULT: PASS", 1: "RESULT: FAIL", 2: "RESULT: INCONCLUSIVE"}[status])
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="localonly", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    sub = commands.add_parser("check-endpoint", help="Reject a remote inference base URL.")
    sub.add_argument("url")
    sub.add_argument("--extra-hosts", default="", help="Comma-separated accepted local hosts.")
    sub.set_defaults(handler=_cmd_check_endpoint)

    sub = commands.add_parser("check-publish-host", help="Reject a publish address on every interface.")
    sub.add_argument("host")
    sub.set_defaults(handler=_cmd_check_publish_host)

    sub = commands.add_parser("check-policy", help="Check the recipe sandbox policy file.")
    sub.add_argument("path")
    sub.set_defaults(handler=_cmd_check_policy)

    sub = commands.add_parser("check-profile", help="Check the recipe provider profile.")
    sub.add_argument("path")
    sub.add_argument("--base-url", help="URL the sandbox calls; the profile endpoint must match it.")
    sub.set_defaults(handler=_cmd_check_profile)

    sub = commands.add_parser(
        "check-effective-policy", help="Check sandbox policy JSON read from standard input.",
    )
    sub.set_defaults(handler=_cmd_check_effective_policy)

    sub = commands.add_parser("list-workspace", help="List the files that setup copies.")
    sub.add_argument("path")
    sub.add_argument("--max-file-bytes", type=int, default=workspace.DEFAULT_MAX_FILE_BYTES)
    sub.add_argument("--max-files", type=int, default=workspace.DEFAULT_MAX_FILES)
    sub.set_defaults(handler=_cmd_list_workspace)

    sub = commands.add_parser("cases", help="Print the test case table.")
    sub.add_argument("--priority", choices=("P0", "P1"))
    sub.set_defaults(handler=_cmd_cases)

    sub = commands.add_parser("run", help="Run the cases against a running sandbox.")
    sub.add_argument("--sandbox", required=True)
    sub.add_argument("--priority", choices=("P0", "P1"))
    sub.add_argument("--evidence", help="Path of the JSON Lines evidence file to write.")
    sub.add_argument(
        "--compose-file", action="append", default=[],
        help="Compose file of the recipe inference server. Repeat for an override file.",
    )
    sub.add_argument(
        "--host-trait", action="append", default=[], choices=(case_table.WSL2,),
        help="Trait of the sandbox host. Cases that require a missing trait are not applicable.",
    )
    sub.set_defaults(handler=_cmd_run)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
