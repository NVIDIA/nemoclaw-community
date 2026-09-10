# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Remove everything this recipe has kept. All of it.

A partial reset is the worst outcome here: somebody who asked for their data to
be gone, and was told it was, while the memory still describes them and the
preference policy still encodes what they ignore. So this removes everything
together and reports each — the store, the memory, the learned policy, and the
skill overrides — and refuses rather than leaving a subset behind.

What it does not touch is the credential. That is held by the OpenShell
gateway, never by this recipe, and removing it is a separate command against a
separate system. Both are printed at the end, because somebody withdrawing
consent wants both and would otherwise stop after the one that felt complete.

    python3 reset.py --dry-run      # list what would go
    python3 reset.py --yes          # remove it

Export first if you want a copy: `export_store.py` writes the same four
things in a readable form.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path

import skill_overrides
from _db import ledger_path


def _profile_root() -> Path:
    return ledger_path().parent.parent.parent


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
        # The overrides themselves, their retained bases, and this feature's
        # own bookkeeping database — a separate tree reset.py did not
        # previously walk.
        "skill-overrides": workspace / "skill-overrides",
        "skill-overrides-restore": workspace / ".skill-overrides-restore",
    }
    # `workspace/.skill-overrides-global.lock` is deliberately absent from
    # this dict, the same way `cron/` is deliberately absent elsewhere: it
    # is the barrier `remove()` itself holds exclusively while deleting
    # everything above, so unlinking it from inside that same hold would
    # let a fresh file at the same path grant a brand new process
    # exclusivity nobody currently running actually has — recreating,
    # inside the fix, the exact inode-swap race the lock exists to close.
    # It survives every reset; see `remove()`'s own docstring.
    # Collection bookkeeping. Not personal in the way a message is, but it
    # names channels, threads and correspondents, and leaving it behind has
    # the next run re-read windows the user just cleared — which is the one
    # outcome a reset must not produce.
    for name in COLLECTION_STATE:
        found[name] = workspace / name
    return found


def _is_dir_strict(path: Path) -> bool:
    """Like `Path.is_dir()`, but only `FileNotFoundError` means "not
    there" — `Path.is_dir()`/`Path.exists()` (like every `Path.is_*`
    predicate) fold *any* `OSError` into `False`, which would let a
    target this process cannot currently stat look identical to one
    genuinely absent. `remove()` below relies on that distinction: a
    real error here must reach its `except OSError`, the same way a
    failed `rmtree`/`unlink` already does, not be silently recorded as
    `"absent"`.

    `os.lstat`, not `os.stat` — a target replaced by a symlink is never
    "a directory to `rmtree`" here, regardless of what it points to or
    whether that target even exists: `remove()`'s own `elif` branch
    below removes a symlink with a plain `unlink`, the same way it
    would an ordinary file, never by following it. `os.stat` would
    instead report a symlink pointing at a directory as `True` here
    (`shutil.rmtree` would then itself refuse to follow it and raise,
    which is safe but indirect) and, worse, report a *broken* symlink
    as absent outright, once this function's own `except
    FileNotFoundError` catches the dangling target's own lookup
    failure — leaving the symlink itself never removed at all.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(st.st_mode)


def _exists_strict(path: Path) -> bool:
    """The `_is_dir_strict`-style equivalent of `Path.exists()` — see
    its docstring, including why this uses `os.lstat` rather than
    `os.stat`."""
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False


def _count_files_strict(path: Path) -> int:
    """A recursive count of regular files under `path` — like
    `sum(1 for _ in path.rglob('*') if _.is_file())`, except real:
    `Path.rglob()` silently stops descending into a subdirectory it
    cannot scan, and `Path.is_file()` folds any `OSError` into `False`,
    both making an inaccessible portion of the tree undercount instead
    of surfacing the problem. Only used by `--dry-run`'s survey, but a
    real error there should still be an honest failure, not a silently
    wrong count somebody might read before consenting to `--yes`. Does
    not descend into or count a symlink, matching this recipe's
    containment conventions elsewhere.
    """
    count = 0
    with os.scandir(path) as it:
        entries = sorted(it, key=lambda e: e.name)
    for entry in entries:
        if entry.is_symlink():
            continue
        if entry.is_dir():
            count += _count_files_strict(Path(entry.path))
        elif entry.is_file():
            count += 1
    return count


def survey() -> dict[str, object]:
    found = {}
    for name, path in targets().items():
        if _is_dir_strict(path):
            found[name] = _count_files_strict(path)
        elif _exists_strict(path):
            found[name] = 1
        else:
            found[name] = 0
    return found


def remove() -> tuple[dict[str, object] | None, list[str], list[str]]:
    """Restores every active override to its shipped content, then deletes
    everything in `targets()` — both inside one held exclusive lock, as a
    single epoch.

    That single epoch is the point: restoring skill A, then separately
    locking and deleting, leaves a real gap in which a new `--fork`/
    `--apply` on A could create or apply an override nothing here ever
    saw, which the deletion step would then destroy unrestored. Holding
    the exclusive lock across both means nothing else can even begin
    claiming a skill's lock — not to fork, apply, or remove — until this
    whole function returns.

    `restore_all_for_reset_locked` restores through `skills/<name>/
    SKILL.md` directly (`apply_overrides` already materialized any
    customization there, outside anything the deletion targets below
    touch) and is itself per-skill fault-isolated, but a failure in the
    surrounding bookkeeping here — this function, or the exclusive lock
    acquisition itself — is not: it is left to propagate, and `main()`
    turns it into a clean failure message rather than deleting anything
    while unsure what succeeded.

    If a live file still contains this feature's recorded write, it must be
    restored successfully before anything is deleted. Content that another
    writer already replaced is preserved and does not need restoration. A
    missing retained base or genuinely diverged operation still blocks all
    deletion. Reporting a complete reset while this feature's own words stayed
    live would be exactly the silent partial reset this command must refuse.
    """
    with skill_overrides.exclusive_lock_for_reset(_profile_root()):
        restore_reports = skill_overrides.restore_all_for_reset_locked(_profile_root())
        # The candidate list is every live skill, most of which were never
        # customized at all — "skipped-no-override" there means exactly
        # that, not a failure, and reporting it for every plain shipped
        # skill on every reset would bury the one line that matters. Only
        # a skill that actually had state to account for and could neither
        # restore its own write nor safely preserve another writer's content
        # counts here.
        restored = [f"{report.skill}: {report.kind}" for report in restore_reports
                   if report.kind != "skipped-no-override"]
        unrestored = [f"{report.skill}: {report.detail}" for report in restore_reports
                     if report.kind not in (
                         "removed", "preserved-live", "skipped-no-override")]
        if unrestored:
            return None, unrestored, restored

        removed: dict[str, object] = {}
        failed: list[str] = []
        for name, path in targets().items():
            try:
                if _is_dir_strict(path):
                    shutil.rmtree(path)
                    removed[name] = "removed"
                elif _exists_strict(path):
                    path.unlink()
                    removed[name] = "removed"
                else:
                    removed[name] = "absent"
            except OSError as exc:
                removed[name] = f"failed: {exc.strerror or exc}"
                failed.append(name)
        return removed, failed, restored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be removed and remove nothing")
    parser.add_argument("--yes", action="store_true",
                        help="required to actually remove anything")
    args = parser.parse_args(argv)

    if args.dry_run:
        try:
            would_remove = survey()
        except Exception as exc:
            # `survey()` now surfaces a genuine stat failure instead of
            # silently counting an inaccessible target as absent — a
            # `--dry-run` that cannot actually answer the question must
            # say so plainly, not traceback.
            print(f"Could not survey what would be removed: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"would_remove": would_remove}))
        return 0

    if not args.yes:
        print("This removes the store, the memory, the learned policy and "
              "any skill overrides.", file=sys.stderr)
        print("Run with --dry-run to see what that is, or --yes to do it.",
              file=sys.stderr)
        return 1

    try:
        # Best-effort, not airtight (see skill_overrides.refuse_if_busy's
        # own docstring): a scheduled tick already mid-write holds a
        # skill's lock file, and deleting the skill-overrides tree out
        # from under it would unlink that exact file, letting a fresh one
        # at the same path grant exclusivity nobody still running
        # actually has. Refuse outright rather than race it. Under the
        # same exception boundary as `remove()` below, not a separate
        # one: a symlinked or otherwise unreadable state directory can
        # make this check itself raise, and that must fail the same
        # controlled way as anything remove() itself can raise.
        busy = skill_overrides.refuse_if_busy(_profile_root())
        if busy is not None:
            print(f"A scheduled operation on skill {busy!r} appears to be "
                  "in progress right now — its lock is currently held. "
                  "Resetting while it might still be running risks two "
                  "operations on the same files at once. Nothing has been "
                  "removed. Wait for it to finish (or pause the schedule "
                  "first), then try again.", file=sys.stderr)
            return 1

        removed, failed, restored = remove()
    except Exception as exc:
        # `remove()`'s own exclusive-lock epoch means nothing was deleted
        # if this raises — but a raw traceback here is exactly the
        # uncontrolled failure this command exists to avoid reporting as
        # anything other than what it is.
        print(f"Reset failed before removing anything: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if removed is None:
        print(json.dumps({"skill_overrides_restored": restored}))
        print(f"Could not restore: {', '.join(failed)}. Nothing has been "
              "removed. A skill left live because its own restoration "
              "failed is not what this recipe means when it says a reset "
              "removes everything — see the detail above, resolve it "
              "(often a concurrent scheduled tick still holding that "
              "skill's lock; wait for it to finish), and run this again.",
              file=sys.stderr)
        return 1

    print(json.dumps({"removed": removed, "skill_overrides_restored": restored}))

    if failed:
        # A reset that half-worked must not read as a reset that worked.
        print(f"Could not remove: {', '.join(failed)}. Data remains.",
              file=sys.stderr)
        return 1

    print("", file=sys.stderr)
    print("The store, the memory, the policy, the skill overrides and the "
          "collection state are gone. The credential is not — it is held by "
          "the gateway, not by this recipe.", file=sys.stderr)
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
