#!/usr/bin/env python3
"""Render the tightly-scoped model-serving templates without shell escaping."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path


PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def parse_assignment(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    key, replacement = value.split("=", 1)
    if not KEY.fullmatch(key):
        raise argparse.ArgumentTypeError(f"invalid placeholder key: {key}")
    if "\x00" in replacement:
        raise argparse.ArgumentTypeError(f"replacement for {key} contains NUL")
    return key, replacement


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--set", dest="assignments", action="append", default=[], type=parse_assignment)
    args = parser.parse_args()

    template = args.template.read_text(encoding="utf-8")
    values = dict(args.assignments)
    unresolved = sorted(set(PLACEHOLDER.findall(template)) - values.keys())
    if unresolved:
        raise SystemExit(f"missing template values: {', '.join(unresolved)}")

    rendered = PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
    remaining = sorted(set(PLACEHOLDER.findall(rendered)))
    if remaining:
        raise SystemExit(f"unresolved template values: {', '.join(remaining)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".render-", dir=args.output.parent, text=True)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(rendered)
        os.chmod(temporary, 0o600)
        os.replace(temporary, args.output)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    main()
