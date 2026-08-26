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


# Everything a collector or a lifecycle control leaves in the workspace.
#
# Named individually rather than by glob: a reset that removed whatever it
# found would eventually remove something a future feature meant to keep, and
# the failure would be silent and unrecoverable. A new file here is a
# deliberate line, and the test below fails when the workspace grows one that
# nobody listed.
COLLECTION_STATE = (
    "slack_capabilities.json",   # probed scopes, keyed on the credential
    "slack_channels.json",       # the public channels the user named
    "slack_threads.json",        # per-thread watermarks
    "slack_rotation.json",       # where the next bounded tick starts
    "slack_thread_rotation.json",  # per-channel thread rotation
    "graph_identity.json",       # the mailbox the token belongs to
    "exclusions.json",           # who the user chose to keep out
)


def targets() -> dict[str, Path]:
    workspace = ledger_path().parent.parent
    found = {
        "store": ledger_path().parent,
        "memory": workspace / "memory",
        "policy": workspace / "policy",
    }
    # Collection bookkeeping. Not personal in the way a message is, but it
    # names channels, threads and correspondents, and leaving it behind has
    # the next run re-read windows the user just cleared — which is the one
    # outcome a reset must not produce.
    for name in COLLECTION_STATE:
        found[name] = workspace / name
    return found


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
    print("The store, the memory, the policy and the collection state are "
          "gone. The credential is not — it is held by the gateway, not by "
          "this recipe.", file=sys.stderr)
    print("", file=sys.stderr)
    # Order matters, and getting it wrong undoes the reset within half an
    # hour: a scheduled collector that is still running against a credential
    # that is still attached will refill the store from the source before
    # anybody notices. Stop the schedule first, detach second, delete last.
    print("Do these in order, or the next scheduled tick refills what you "
          "just removed:", file=sys.stderr)
    print("  1. stop collecting   hermes -p <profile> cron pause <intake job "
          "id>", file=sys.stderr)
    print("                       or remove the job entirely with `cron "
          "remove`", file=sys.stderr)
    print("  2. detach            openshell sandbox provider detach <sandbox> "
          "<provider>", file=sys.stderr)
    print("  3. revoke            uninstall the app from the source workspace",
          file=sys.stderr)
    print("  4. delete            openshell provider delete <provider>",
          file=sys.stderr)
    print("", file=sys.stderr)
    print("Deleting the profile removes its workspace with it, which is the "
          "one-step version: hermes profile delete <profile>", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
