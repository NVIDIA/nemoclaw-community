#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Create or update a minimal configuration for this recipe."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EXAMPLE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.configuration import (  # noqa: E402
    DEFAULTS,
    GATEWAY_ENDPOINTS,
    SECRET_KEYS,
    ConfigurationError,
    EnvDocument,
    enabled_profiles,
    parse_env_text,
    profile_errors,
    profile_keys,
    read_env,
    render_updates,
    resolved_values,
    write_env,
)

LABELS = {
    "COMPATIBLE_API_KEY": "Inference API key",
    "NEMOCLAW_MODEL": "Inference model",
    "OPENAI_API_KEY": "Inference API key",
    "OPENSHELL_GATEWAY": "OpenShell gateway name",
    "OPENSHELL_GATEWAY_ENDPOINT": "OpenShell gateway endpoint",
    "OUTLOOK_CLIENT_ID": "Microsoft Entra client ID",
    "OUTLOOK_REPLY_TO": "Reply-to mailbox",
    "OUTLOOK_TARGET_MAILBOX": "Agent mailbox",
    "OUTLOOK_TENANT_ID": "Microsoft Entra tenant ID",
    "SANDBOX_NAME": "Sandbox name",
    "SLACK_APP_TOKEN": "Slack app-level token",
    "SLACK_BOT_TOKEN": "Slack bot access token",
}


def prompt_choice(
    prompt: str,
    choices: tuple[str, ...],
    *,
    default: str,
    input_fn: Callable[[str], str],
) -> str:
    while True:
        answer = (
            input_fn(f"{prompt} ({'/'.join(choices)}) [{default}]: ").strip().lower()
        )
        selected = answer or default
        if selected in choices:
            return selected
        print(f"Choose one of: {', '.join(choices)}", file=sys.stderr)


def prompt_value(
    key: str,
    current: str,
    *,
    required: bool,
    input_fn: Callable[[str], str],
    secret_fn: Callable[[str], str],
) -> str:
    label = LABELS.get(key, key)
    secret = key in SECRET_KEYS
    while True:
        if secret:
            state = "configured; Enter keeps it" if current else "required"
            answer = secret_fn(f"{label} [{state}]: ")
        else:
            state = current or ("required" if required else "optional")
            answer = input_fn(f"{label} [{state}]: ")
        if answer:
            return answer.strip()
        if current or not required:
            return current
        print(f"{label} is required.", file=sys.stderr)


def infer_profile(document: EnvDocument) -> str:
    profiles = enabled_profiles(document.values)
    if profiles == ("Slack",):
        return "slack"
    if profiles == ("Outlook",):
        return "outlook"
    if len(profiles) == 2:
        return "both"
    return "slack"


def collect_interactive_updates(
    document: EnvDocument,
    environment: Mapping[str, str],
    *,
    profile: str | None,
    replacements: Mapping[str, str],
    input_fn: Callable[[str], str] = input,
    secret_fn: Callable[[str], str] = getpass.getpass,
) -> tuple[str, dict[str, str]]:
    current = resolved_values(document, environment)
    selected_profile = profile or prompt_choice(
        "Messaging profile",
        ("slack", "outlook", "both"),
        default=infer_profile(document),
        input_fn=input_fn,
    )
    sandbox_name = prompt_value(
        "SANDBOX_NAME",
        replacements.get("SANDBOX_NAME", current["SANDBOX_NAME"]),
        required=True,
        input_fn=input_fn,
        secret_fn=secret_fn,
    )
    gateway = prompt_value(
        "OPENSHELL_GATEWAY",
        replacements.get("OPENSHELL_GATEWAY", current["OPENSHELL_GATEWAY"]),
        required=True,
        input_fn=input_fn,
        secret_fn=secret_fn,
    )
    explicit_endpoint = document.values.get(
        "OPENSHELL_GATEWAY_ENDPOINT"
    ) or environment.get("OPENSHELL_GATEWAY_ENDPOINT", "")
    gateway_endpoint = prompt_value(
        "OPENSHELL_GATEWAY_ENDPOINT",
        replacements.get(
            "OPENSHELL_GATEWAY_ENDPOINT",
            explicit_endpoint or GATEWAY_ENDPOINTS.get(gateway, ""),
        ),
        required=True,
        input_fn=input_fn,
        secret_fn=secret_fn,
    )
    model = prompt_value(
        "NEMOCLAW_MODEL",
        replacements.get("NEMOCLAW_MODEL", current["NEMOCLAW_MODEL"]),
        required=True,
        input_fn=input_fn,
        secret_fn=secret_fn,
    )
    updates: dict[str, str] = {
        "SANDBOX_NAME": sandbox_name,
        "OPENSHELL_GATEWAY": gateway,
        "OPENSHELL_GATEWAY_ENDPOINT": gateway_endpoint,
        "NEMOCLAW_MODEL": model,
        "NEMOCLAW_INFERENCE_PREFLIGHT": current.get(
            "NEMOCLAW_INFERENCE_PREFLIGHT", "1"
        ),
        "GITHUB_READONLY_REPO": current.get(
            "GITHUB_READONLY_REPO", DEFAULTS["GITHUB_READONLY_REPO"]
        ),
    }
    inference_key_name = "COMPATIBLE_API_KEY"
    inference_key = current.get(inference_key_name, "")
    if not inference_key and current.get("OPENAI_API_KEY"):
        inference_key_name = "OPENAI_API_KEY"
        inference_key = current[inference_key_name]
    updates[inference_key_name] = prompt_value(
        inference_key_name,
        inference_key,
        required=True,
        input_fn=input_fn,
        secret_fn=secret_fn,
    )

    for key in profile_keys(selected_profile):
        updates[key] = prompt_value(
            key,
            replacements.get(key, current.get(key, "")),
            required=True,
            input_fn=input_fn,
            secret_fn=secret_fn,
        )
    if selected_profile in {"slack", "both"}:
        updates["NEMOCLAW_SLACK_RICH_BLOCKS"] = current.get(
            "NEMOCLAW_SLACK_RICH_BLOCKS", "true"
        )
    if selected_profile in {"outlook", "both"}:
        updates["OUTLOOK_LOGIN_CACHE"] = current.get("OUTLOOK_LOGIN_CACHE", "1")
    return selected_profile, updates


def collect_non_interactive_updates(
    document: EnvDocument,
    environment: Mapping[str, str],
    *,
    profile: str,
    replacements: Mapping[str, str],
    replace: bool,
) -> dict[str, str]:
    existing = {} if replace else document.values
    current = resolved_values(
        EnvDocument(lines=(), values=dict(existing), line_indexes={}), environment
    )
    updates = {
        "SANDBOX_NAME": replacements.get("SANDBOX_NAME", current["SANDBOX_NAME"]),
        "OPENSHELL_GATEWAY": replacements.get(
            "OPENSHELL_GATEWAY", current["OPENSHELL_GATEWAY"]
        ),
        "NEMOCLAW_MODEL": replacements.get("NEMOCLAW_MODEL", current["NEMOCLAW_MODEL"]),
        "NEMOCLAW_INFERENCE_PREFLIGHT": current.get(
            "NEMOCLAW_INFERENCE_PREFLIGHT", "1"
        ),
        "GITHUB_READONLY_REPO": current.get(
            "GITHUB_READONLY_REPO", DEFAULTS["GITHUB_READONLY_REPO"]
        ),
    }
    explicit_endpoint = existing.get("OPENSHELL_GATEWAY_ENDPOINT") or environment.get(
        "OPENSHELL_GATEWAY_ENDPOINT", ""
    )
    gateway_endpoint = (
        replacements.get("OPENSHELL_GATEWAY_ENDPOINT")
        or explicit_endpoint
        or GATEWAY_ENDPOINTS.get(updates["OPENSHELL_GATEWAY"], "")
    )
    if not gateway_endpoint:
        raise ConfigurationError(
            "non-interactive setup requires OPENSHELL_GATEWAY_ENDPOINT for a custom gateway"
        )
    updates["OPENSHELL_GATEWAY_ENDPOINT"] = gateway_endpoint

    inference_key_name = "COMPATIBLE_API_KEY"
    inference_key = current.get(inference_key_name, "")
    if not inference_key and current.get("OPENAI_API_KEY"):
        inference_key_name = "OPENAI_API_KEY"
        inference_key = current["OPENAI_API_KEY"]
    if not inference_key:
        raise ConfigurationError(
            "non-interactive setup requires COMPATIBLE_API_KEY or OPENAI_API_KEY "
            "in the environment or existing configuration"
        )
    updates[inference_key_name] = inference_key

    missing: list[str] = []
    for key in profile_keys(profile):
        value = current.get(key, "")
        if not value:
            missing.append(key)
        else:
            updates[key] = value
    if missing:
        raise ConfigurationError(
            "non-interactive setup is missing required inputs: " + ", ".join(missing)
        )
    if profile in {"slack", "both"}:
        updates["NEMOCLAW_SLACK_RICH_BLOCKS"] = current.get(
            "NEMOCLAW_SLACK_RICH_BLOCKS", "true"
        )
    if profile in {"outlook", "both"}:
        updates["OUTLOOK_LOGIN_CACHE"] = current.get("OUTLOOK_LOGIN_CACHE", "1")
    return updates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("slack", "outlook", "both"))
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Read required credentials from the environment or existing file",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the target with a minimal file instead of preserving unselected lines",
    )
    parser.add_argument("--env-file", type=Path, default=EXAMPLE_DIR / ".env")
    parser.add_argument("--sandbox-name")
    parser.add_argument("--gateway", choices=("openshell", "snap-docker"))
    parser.add_argument("--gateway-endpoint")
    parser.add_argument("--model")
    return parser


def print_prerequisites(profile: str) -> None:
    print("External prerequisites:")
    print("  - An inference API key and access to the configured model")
    if profile in {"slack", "both"}:
        print(
            "  - A Slack app with Socket Mode, a bot access token, and an app-level token"
        )
    if profile in {"outlook", "both"}:
        print(
            "  - A Microsoft Entra application, mailbox permission, and administrator consent"
        )


def print_summary(path: Path, values: Mapping[str, str]) -> None:
    profiles = enabled_profiles(values)
    print(f"Configuration written: {path}")
    print("File permissions: owner read/write only")
    print(f"Messaging profiles: {', '.join(profiles) or 'none'}")
    print(f"Sandbox: {values.get('SANDBOX_NAME', DEFAULTS['SANDBOX_NAME'])}")
    print(f"Gateway: {values.get('OPENSHELL_GATEWAY', DEFAULTS['OPENSHELL_GATEWAY'])}")
    print(f"Model: {values.get('NEMOCLAW_MODEL', DEFAULTS['NEMOCLAW_MODEL'])}")
    print("Credentials: configured values are redacted")
    print("Next command: python3 scripts/preflight.py")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.non_interactive and not args.profile:
        print("--profile is required with --non-interactive", file=sys.stderr)
        return 2
    replacements = {
        key: value
        for key, value in {
            "SANDBOX_NAME": args.sandbox_name,
            "OPENSHELL_GATEWAY": args.gateway,
            "OPENSHELL_GATEWAY_ENDPOINT": args.gateway_endpoint,
            "NEMOCLAW_MODEL": args.model,
        }.items()
        if value is not None
    }
    try:
        document = read_env(args.env_file)
        if args.non_interactive:
            updates = collect_non_interactive_updates(
                document,
                os.environ,
                profile=args.profile,
                replacements=replacements,
                replace=args.replace,
            )
            selected_profile = args.profile
        else:
            selected_profile, updates = collect_interactive_updates(
                EnvDocument(lines=(), values={}, line_indexes={})
                if args.replace
                else document,
                os.environ,
                profile=args.profile,
                replacements=replacements,
            )
        candidate_text = render_updates(document, updates, replace=args.replace)
        candidate = read_candidate(candidate_text)
        errors = profile_errors(candidate.values)
        if errors:
            raise ConfigurationError("; ".join(errors))
        print_prerequisites(selected_profile)
        write_env(args.env_file, candidate_text)
        print_summary(args.env_file, resolved_values(candidate))
        return 0
    except ConfigurationError as error:
        print(f"Configuration failed: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        detail = error.strerror or error.__class__.__name__
        print(
            f"Configuration failed: cannot write {args.env_file}: {detail}",
            file=sys.stderr,
        )
        return 2


def read_candidate(text: str) -> EnvDocument:
    return parse_env_text(text)


if __name__ == "__main__":
    raise SystemExit(main())
