# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Command line entry point.

    python -m sre_autoheal preflight                 # identity, RBAC, LLM, knowledge
    python -m sre_autoheal scan [-n NS]              # detect + diagnose, never act
    python -m sre_autoheal heal --once [--dry-run]   # one detect/heal cycle
    python -m sre_autoheal watch                     # loop forever (in-cluster default)
    python -m sre_autoheal memory summary|export|reset
    python -m sre_autoheal knowledge list|show ID
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, List, Optional

from . import __version__
from .config import Config, load_config
from .engine import Engine
from .knowledge import Knowledge
from .memory import Memory


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)


def _print(obj: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
    else:
        _print_human(obj)


def _print_human(obj: Any) -> None:
    if isinstance(obj, dict) and "incidents" in obj and "cluster" in obj:
        c = obj["cluster"]
        print(f"cluster: {c.get('server')} platform={c.get('platform')} version={c.get('version')} identity={c.get('identity')}")
        print(f"nodes={c.get('nodes')} (not ready {c.get('nodes_not_ready')})  pods={c.get('pods')} unhealthy={c.get('unhealthy_pods')} "
              f"pending={c.get('pending_pods')}  degraded operators={c.get('degraded_operators')}")
        if c.get("snapshot_errors"):
            print("snapshot errors: " + "; ".join(c["snapshot_errors"]))
        print(f"findings={obj.get('findings')} posture={obj.get('posture_findings')} incidents={len(obj['incidents'])} "
              f"duration={obj.get('duration_seconds')}s")
        for inc in obj["incidents"]:
            f = inc["finding"]
            subj = f.get("owner") or f.get("resource")
            d = inc.get("diagnosis") or {}
            print(f"- [{f['severity']:^8}] {f['pattern_id']:<28} {subj.get('namespace') or '-'}/{subj['kind'].lower()}/{subj['name']}")
            print(f"    symptom : {f['summary']}")
            print(f"    cause   : {d.get('root_cause')} (conf {d.get('confidence')}, {d.get('source')})")
            print(f"    decision: {inc['decision']} - {inc['decision_reason']}" + (f" [action={inc.get('action')}]" if inc.get("action") else ""))
            if inc.get("verify_detail"):
                print(f"    verify  : {inc['verify_detail']}")
        return
    print(json.dumps(obj, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sre-autoheal", description="Kubernetes/OpenShift self-healing SRE agent")
    p.add_argument("--config", "-c", action="append", default=[], help="config file (JSON or YAML); repeatable")
    p.add_argument("--log-level", default=None)
    p.add_argument("--json", action="store_true", help="machine-readable output (notifications go to stderr sinks only)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", dest="json_sub", help=argparse.SUPPRESS)

    sub.add_parser("preflight", parents=[common], help="check identity, RBAC, LLM and knowledge base")

    scan = sub.add_parser("scan", parents=[common], help="detect and diagnose without acting")
    scan.add_argument("-n", "--namespace", action="append", default=[])
    scan.add_argument("--no-llm", action="store_true")

    heal = sub.add_parser("heal", parents=[common], help="run one detect/diagnose/heal cycle")
    heal.add_argument("-n", "--namespace", action="append", default=[])
    heal.add_argument("--once", action="store_true", default=True)
    heal.add_argument("--dry-run", action="store_true")
    heal.add_argument("--mode", choices=["observe", "safe", "assisted"])
    heal.add_argument("--no-llm", action="store_true")

    watch = sub.add_parser("watch", parents=[common], help="run cycles forever")
    watch.add_argument("--interval", type=int)
    watch.add_argument("--dry-run", action="store_true")
    watch.add_argument("--mode", choices=["observe", "safe", "assisted"])

    mem = sub.add_parser("memory", parents=[common], help="inspect learned state")
    mem.add_argument("memory_command", choices=["summary", "export", "reset", "incidents"])
    mem.add_argument("--last", type=int, default=20)

    kn = sub.add_parser("knowledge", parents=[common], help="inspect the failure-pattern knowledge base")
    kn.add_argument("knowledge_command", choices=["list", "show", "render-json"])
    kn.add_argument("pattern_id", nargs="?")
    return p


def apply_overrides(config: Config, args: argparse.Namespace) -> None:
    if getattr(args, "json_sub", False):
        args.json = True
    if args.json:
        # keep stdout parseable; notifications still reach Slack/email/webhook sinks
        config.data["notify"]["stdout"]["enabled"] = False
    if getattr(args, "dry_run", False):
        config.data["policy"]["dry_run"] = True
    if getattr(args, "mode", None):
        config.data["policy"]["mode"] = args.mode
    if getattr(args, "no_llm", False):
        config.data["llm"]["enabled"] = False
    if getattr(args, "interval", None):
        config.data["detection"]["interval_seconds"] = args.interval


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    apply_overrides(config, args)
    _setup_logging(args.log_level or config.get("log_level", "INFO"))
    log = logging.getLogger("sre_autoheal")
    if config.source_files:
        log.info("config files: %s", ", ".join(config.source_files))

    if args.command == "knowledge":
        kb = Knowledge.load()
        if args.knowledge_command == "list":
            rows = [{"id": p_["id"], "platform": p_.get("platform"), "detected": p_.get("detected", False),
                     "actions": [r["action"] for r in p_.get("remediation", [])]} for p_ in kb.patterns.values()]
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for r in rows:
                    print(f"{r['id']:<32} {r['platform']:<10} {'detected' if r['detected'] else 'reference':<10} {', '.join(r['actions'])}")
            return 0
        if args.knowledge_command == "show":
            print(json.dumps(kb.pattern(args.pattern_id or ""), indent=2))
            return 0
        print(kb.render_json())
        return 0

    if args.command == "memory":
        engine_client = None
        if config.get("memory.backend") == "configmap":
            from . import kube as k
            cluster_cfg = config.section("cluster")
            engine_client = k.KubeClient.build(cluster_cfg.get("transport", "auto"), cluster_cfg.get("kubectl_binary", ""))
        memory = Memory.build(config.section("memory"), engine_client)
        if args.memory_command == "summary":
            _print(memory.summary(), args.json)
        elif args.memory_command == "export":
            print(json.dumps(memory.export_policy_suggestions(), indent=2, default=str))
        elif args.memory_command == "incidents":
            _print(memory.data["incidents"][-args.last:], True)
        elif args.memory_command == "reset":
            from .memory import _empty
            memory.data = _empty()
            memory.save()
            print("memory reset")
        return 0

    engine = Engine.build(config)
    if args.command == "preflight":
        report = engine.preflight()
        _print(report, args.json or True)
        blocked = [k_ for k_, v in report["rbac"].items() if not v]
        if blocked:
            log.warning("RBAC missing for: %s", "; ".join(blocked))
        return 0 if report["rbac"].get("read pods") else 2

    if args.command == "scan":
        result = engine.run_cycle(namespaces=args.namespace or None, act=False)
        _print(result, args.json)
        return 0

    if args.command == "heal":
        result = engine.run_cycle(namespaces=args.namespace or None, act=True)
        _print(result, args.json)
        failed = [i for i in result["incidents"] if i["decision"] == "heal_failed"]
        return 1 if failed else 0

    if args.command == "watch":
        engine.run_forever(args.interval)
        return 0
    return 0
