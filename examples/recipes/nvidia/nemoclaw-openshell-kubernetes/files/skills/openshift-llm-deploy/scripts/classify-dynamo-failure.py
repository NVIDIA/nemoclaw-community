#!/usr/bin/env python3
"""Conservatively classify an observed Dynamo deployment failure."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


MAX_EVIDENCE_BYTES = 262_144


def bounded(path: str) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_bytes()[:MAX_EVIDENCE_BYTES].decode("utf-8", "replace")
    except OSError:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dgd-conditions", default="")
    parser.add_argument("--pod-state-file", default="")
    parser.add_argument("--runtime-log-file", default="")
    args = parser.parse_args()

    evidence = "\n".join(
        (
            args.dgd_conditions,
            bounded(args.pod_state_file),
            bounded(args.runtime_log_file),
        )
    )
    normalized = evidence.lower()

    terminal_patterns = (
        ("image-pull", r"imagepullbackoff|errimagepull|invalidimagename|manifest unknown"),
        ("authorization", r"forbidden|permission denied|unauthorized"),
        ("scheduling", r"failedscheduling|insufficient (cpu|memory|nvidia\.com/gpu)|untolerated taint"),
        ("storage", r"failedmount|failedattachvolume|unbound immediate persistentvolumeclaims"),
        ("resource-limit", r"oomkilled|out of memory|cuda out of memory"),
        ("container-start", r"createcontainer(config)?error|containercannotrun|runcontainererror"),
    )
    for reason, pattern in terminal_patterns:
        if re.search(pattern, normalized):
            print("DYNAMO_FAILURE_CLASS=terminal")
            print(f"DYNAMO_FAILURE_REASON={reason}")
            return

    # Fallback is intentionally narrow. Only explicit model/runtime
    # incompatibility is evidence that changing the serving backend is safer
    # than retrying the same failed infrastructure operation.
    fallback_patterns = (
        r"unsupported (model|architecture|config)",
        r"(model|architecture).{0,80}not supported",
        r"unknown model type",
        r"no supported backend",
        r"does not support.{0,80}(model|architecture)",
    )
    if any(re.search(pattern, normalized) for pattern in fallback_patterns):
        print("DYNAMO_FAILURE_CLASS=fallback")
        print("DYNAMO_FAILURE_REASON=proven-model-runtime-incompatibility")
        return

    if re.search(r"(failed|error|failure)=true:", normalized):
        print("DYNAMO_FAILURE_CLASS=terminal")
        print("DYNAMO_FAILURE_REASON=dynamo-controller-reported-failure")
        return

    print("DYNAMO_FAILURE_CLASS=pending")
    print("DYNAMO_FAILURE_REASON=no-terminal-evidence")


if __name__ == "__main__":
    main()
