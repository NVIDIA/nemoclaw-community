# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Remove everything this recipe has kept. All of it.

A partial reset is the worst outcome here: somebody who asked for their data to
be gone, and was told it was, while the memory still describes them and the
preference policy still encodes what they ignore. So this removes three things
together and reports each — the store, the memory, and the learned policy — and
refuses rather than leaving a subset behind.

What it does not touch is the credential. That is held by the OpenShell
gateway, never by this recipe, and removing it is a separate command against a
separate system. Both are printed at the end, because somebody withdrawing
consent wants both and would otherwise stop after the one that felt complete.

    python3 reset.py --dry-run      # list what would go
    python3 reset.py --yes          # remove it

Export first if you want a copy: `export_store.py` writes the same three
things in a readable form.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from _db import ledger_path


def targets() -> dict[str, Path]:
    workspace = ledger_path().parent.parent
    return {
        "store": ledger_path().parent,
        "memory": workspace / "memory",
        "policy": workspace / "policy",
        # Collection bookkeeping. Not personal in itself, but it names channels
        # and threads, and leaving it behind would have the next run re-read
        # windows the user just cleared.
        "collection_state": workspace / "slack_capabilities.json",
    }


def survey() -> dict[str, object]:
    found = {}
    for name, path in targets().items():
        if path.is_dir():
            found[name] = sum(1 for _ in path.rglob("*") if _.is_file())
        elif path.exists():
            found[name] = 1
        else:
            found[name] = 0
    return found


def remove() -> tuple[dict[str, object], list[str]]:
    removed: dict[str, object] = {}
    failed: list[str] = []
    for name, path in targets().items():
        try:
            if path.is_dir():
                shutil.rmtree(path)
                removed[name] = "removed"
            elif path.exists():
                path.unlink()
                removed[name] = "removed"
            else:
                removed[name] = "absent"
        except OSError as exc:
            removed[name] = f"failed: {exc.strerror or exc}"
            failed.append(name)
    return removed, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be removed and remove nothing")
    parser.add_argument("--yes", action="store_true",
                        help="required to actually remove anything")
    args = parser.parse_args(argv)

    if args.dry_run:
        print(json.dumps({"would_remove": survey()}))
        return 0

    if not args.yes:
        print("This removes the store, the memory and the learned policy.",
              file=sys.stderr)
        print("Run with --dry-run to see what that is, or --yes to do it.",
              file=sys.stderr)
        return 1

    removed, failed = remove()
    print(json.dumps({"removed": removed}))

    if failed:
        # A reset that half-worked must not read as a reset that worked.
        print(f"Could not remove: {', '.join(failed)}. Data remains.",
              file=sys.stderr)
        return 1

    print("", file=sys.stderr)
    print("The store, the memory and the policy are gone. The Slack "
          "credential is not — it is held by the gateway, not by this "
          "recipe. To revoke it as well:", file=sys.stderr)
    print("  uninstall the app from your Slack workspace, then", file=sys.stderr)
    print("  openshell sandbox provider detach <sandbox> <provider>",
          file=sys.stderr)
    print("  openshell provider delete <provider>", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
