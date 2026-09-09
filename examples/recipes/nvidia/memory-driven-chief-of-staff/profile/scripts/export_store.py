# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Write out everything this recipe holds, in a form a person can read.

Somebody who wants to know what an assistant has kept about them should not
have to open a database to find out, and somebody leaving should be able to
take it with them. So this writes the whole store and the whole memory as
Markdown and JSON side by side: the Markdown to be read, the JSON to be
processed.

`store.json` is the complete record: every column of every row, nothing
summarised and nothing dropped. `store.md` is the same content laid out to be
read, and it is explicit about the one thing it does differently — a long body
is shown to a bounded length with the remainder marked, because a Markdown
file with a hundred-kilobyte message in it stops being readable, which was the
only reason to write it. When the two disagree, the JSON is the answer.

An export that quietly left something out would be worse than none, because it
would answer the question wrongly. So a table that cannot be read is a failed
export rather than an empty section, and both files are written with the same
owner-only permissions as the store they came from.

    python3 export_store.py                 # to ./export-<date>/
    python3 export_store.py --to <dir>

The destination must be somewhere else. This replaces whatever is there, so
exporting into the workspace would delete the store and leave a copy of it in
place — the destination and the workspace have to be disjoint, and a
destination that is either of them, inside the other, or around it is refused
before anything is created or removed.

Pairs with `reset.py`, which removes what this shows. The two are documented
together because somebody withdrawing consent usually wants both: see what is
held, then have it gone.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import sys
from datetime import date
from pathlib import Path

import skill_overrides
import skill_override_bundle
from _db import ensure_store, ledger_path

TABLES = ("items", "obligations", "events", "cursors", "meta")


# How much of a body `store.md` shows before marking the remainder. The JSON
# holds all of it; this bound exists so the readable form stays readable.
BODY_PREVIEW = 2000


def _write_private(path: Path, text: str, *, errors: str = "strict") -> None:
    """Write owner-only, and be owner-only from the first byte.

    Creating the file and then chmod-ing it leaves a window in which the
    content is world-readable, which on a shared machine is the whole risk.

    `errors="surrogateescape"` is what a caller passes for a skill
    override's own text — captured with the matching decode in
    `skill_overrides.snapshot_for_export`, the pair round-trips a
    malformed or non-UTF-8 override back to its exact original bytes
    instead of silently dropping or altering them.
    """
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8", errors=errors) as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def _narrow(root: Path) -> None:
    """Owner-only, everywhere under the export."""
    os.chmod(root, 0o700)
    for path in root.rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)


def rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]


def _overrides_as_dicts(reports: list[skill_overrides.Report]) -> list[dict]:
    return [{"skill": r.skill, "status": r.kind, "detail": r.detail}
           for r in reports]


def as_markdown(data: dict[str, list[dict]],
               overrides: list[skill_overrides.Report] = ()) -> str:
    """The same content, laid out to be read rather than parsed."""
    out: list[str] = ["# What this assistant is holding", ""]
    out.append(f"Exported {date.today().isoformat()}.")
    out.append("")

    obligations = data.get("obligations", [])
    out.append(f"## Obligations ({len(obligations)})")
    out.append("")
    if not obligations:
        out.append("None.")
    for row in sorted(obligations, key=lambda r: r.get("global_rank") or 0):
        rank = row.get("global_rank")
        out.append(f"- **{row.get('title') or '(untitled)'}**")
        out.append(f"  - rank {rank}, {row.get('priority')}, "
                   f"{row.get('status')}")
        out.append(f"  - from `{row.get('source_id')}`")
    out.append("")

    items = data.get("items", [])
    held = sum(1 for r in items if r.get("body"))
    cleared = sum(1 for r in items if r.get("body_cleared_at"))
    out.append(f"## Messages ({len(items)})")
    out.append("")
    out.append(f"{held} still hold their text. {cleared} have had it cleared "
               "by the retention pass; the rest never carried any.")
    out.append("")
    for row in sorted(items, key=lambda r: r.get("event_at") or ""):
        out.append(f"- `{row.get('event_at')}` **{row.get('sender') or '?'}** "
                   f"— {row.get('subject') or '(no subject)'}")
        if row.get("body"):
            body = " ".join(str(row["body"]).split())
            if len(body) > BODY_PREVIEW:
                out.append(f"  - {body[:BODY_PREVIEW]}")
                out.append(f"  - _(body continues; {len(body) - BODY_PREVIEW} "
                           "more characters in `store.json`)_")
            else:
                out.append(f"  - {body}")
        elif row.get("body_cleared_at"):
            out.append(f"  - text cleared {row['body_cleared_at']}")
    out.append("")

    events = data.get("events", [])
    out.append(f"## What happened, and who did it ({len(events)})")
    out.append("")
    if not events:
        out.append("Nothing yet.")
    for row in sorted(events, key=lambda r: r.get("ts") or ""):
        out.append(f"- `{row.get('ts')}` {row.get('event_type')} "
                   f"by {row.get('actor')} on `{row.get('obligation_id')}`")
    out.append("")

    # A customization the user wrote, not a ledger row — genuinely different
    # in kind from the tables above, so it gets its own section rather than
    # being forced into their row-oriented shape.
    out.append(f"## Skill overrides ({len(overrides)})")
    out.append("")
    if not overrides:
        out.append("None.")
    else:
        out.append("Readable copies are under `skill-overrides/overrides/`. "
                   "The versioned `skill-overrides-recovery.json` also holds "
                   "the retained bases, distribution approvals, manifest and "
                   "operation history. Restore trusted bundles with "
                   "`skill_overrides.py --restore <bundle>` into an empty "
                   "override-state directory, then run `--check`. Restore "
                   "does not overwrite live skills or restore the main ledger.")
    for report in sorted(overrides, key=lambda r: r.skill):
        state = "up to date with the shipped skill" if report.kind == "applied" \
            else ("stale — the shipped skill has changed since this was "
                  "forked; --apply refuses it until it is forked again"
                 if report.kind == "skipped-stale"
                 else f"not applied: {report.detail}")
        out.append(f"- **{report.skill}** — {state}")
    out.append("")
    return "\n".join(out) + "\n"


def _is_dir_strict(path: Path) -> bool:
    """Like `Path.is_dir()`, but only `FileNotFoundError` means "not
    there" — `Path.is_dir()` (like every `Path.is_*` predicate) folds
    *any* `OSError` into `False`, which would let a directory this
    process cannot currently stat look identical to one that genuinely
    is not there. An export that silently treated the two the same would
    finish and report success while quietly missing whatever that
    directory held.
    """
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except FileNotFoundError:
        return False


def _is_symlink_strict(path: Path) -> bool:
    """The `os.lstat`-based equivalent of `_is_dir_strict`, for the same
    reason — see its docstring."""
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def _regular_file_exists(path: Path) -> bool:
    """The `_is_dir_strict`-style equivalent of `Path.is_file()` — see
    its docstring. `False` here can mean a genuine directory (an
    ordinary, expected case the caller's own `_is_dir_strict` check
    already handles) as well as absence; only a permission error or
    similar must not be folded into the same `False`, which is exactly
    what this fixes relative to `Path.is_file()`.
    """
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISREG(st.st_mode)


def _lexists_strict(path: Path) -> bool:
    """Like `Path.exists()`, but via `os.lstat` (does not follow a
    symlink — the point being to answer "is there a directory entry
    here at all", not "does whatever it points at exist") and, as with
    every other strict helper in this file, only `FileNotFoundError`
    means "not there".
    """
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False


def _top_level_export_source_is_dir(path: Path) -> bool:
    """Whether `path` (`memory/` or `policy/`) is a real directory this
    export should copy from — `False` only for genuine absence, and
    raises for anything else that is not a directory to copy: a symlink
    (refused outright rather than followed), or an existing regular
    file, FIFO, socket, or similar sitting where this recipe only ever
    creates a directory.

    That last case matters beyond export's own "nothing is omitted"
    promise: `reset.py` unconditionally removes whatever is at this
    exact path as one of its targets, regardless of type. An export
    that treated an anomalous non-directory object here the same as
    absence — silently skipping it, the same `False` a genuine absence
    produces — would let an export-then-reset cycle lose it: reset
    still deletes it, but export never captured it first.

    `_copy_inside_workspace`'s own per-entry containment check already
    refuses any entry that resolves outside the workspace, but that
    check only ever runs on entries `_walk_strict` actually yields — an
    external symlink target with nothing in it would let the whole
    top-level source be a symlink, get scanned, yield nothing, and
    complete as an ordinary empty directory would, without ever being
    checked at all. Refusing a symlinked top-level source itself, the
    same way `_safe_child` refuses a symlinked parent elsewhere in this
    recipe, closes that regardless of what — if anything — is on the
    other end of it.
    """
    if _is_symlink_strict(path):
        raise ExportEscapesWorkspace(
            f"{path} is a symlink. Nothing has been exported. Remove "
            "the link or copy the directory in.")
    if _is_dir_strict(path):
        return True
    if _lexists_strict(path):
        raise ExportEscapesWorkspace(
            f"{path} exists but is not a directory (a regular file, "
            "FIFO, device, or similar). Nothing has been exported. "
            "Remove it or replace it with an ordinary directory.")
    return False


def _walk_strict(source: Path):
    """Yield every path under `source`, depth-first — like
    `sorted(source.rglob('*'))`, except real: `Path.rglob()` silently
    stops descending into a subdirectory it cannot scan (a permission
    error inside its own internal directory scan is caught there and
    treated as "nothing here"), which is exactly the kind of silent
    omission this export's own "nothing is omitted" contract has to
    refuse instead of reproducing. Does not descend into a symlinked
    directory, matching `rglob`'s own default and this module's
    existing containment check for what such a directory's target might
    hold.
    """
    with os.scandir(source) as it:
        children = sorted(it, key=lambda e: e.name)
    for entry in children:
        path = Path(entry.path)
        yield path
        if entry.is_dir(follow_symlinks=False) and not entry.is_symlink():
            yield from _walk_strict(path)


def _copy_inside_workspace(source: Path, target: Path, workspace: Path) -> int:
    """Copy a tree, refusing anything that leaves the workspace.

    `copytree` follows symbolic links by default — it copies what the link
    points at, not the link — so a link under `memory/` pulls a file from
    anywhere on the machine into an export the user is about to hand to
    somebody. Every entry is resolved and checked against the workspace before
    it is read.
    """
    copied = 0
    for entry in _walk_strict(source):
        if entry.name.startswith("._") or entry.name == ".DS_Store":
            continue
        resolved = entry.resolve()
        try:
            resolved.relative_to(workspace.resolve())
        except ValueError:
            raise ExportEscapesWorkspace(
                f"{entry} points outside the workspace, at {resolved}. "
                "Nothing has been exported. Remove the link or copy the file "
                "in.")
        relative = entry.relative_to(source)
        is_dir = _is_dir_strict(entry)
        is_symlink = _is_symlink_strict(entry)
        if is_dir and not is_symlink:
            (target / relative).mkdir(parents=True, exist_ok=True)
        elif _regular_file_exists(entry):
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            _write_private(target / relative,
                           entry.read_text(encoding="utf-8", errors="replace"))
            copied += 1
        elif is_dir and is_symlink:
            # A symlinked directory — deliberately skipped, not
            # descended into (see `_walk_strict`) or materialized as an
            # empty directory here either. Legitimate and expected, not
            # an anomaly: the containment check above already refuses
            # one whose target reaches outside the workspace.
            continue
        else:
            # Whatever is left — a FIFO, a socket, a device file, or
            # similar — is not "nothing to copy" the way a symlinked
            # directory is; silently skipping it would omit real state
            # from an export that promises nothing is.
            raise ExportEscapesWorkspace(
                f"{entry} is neither a regular file nor a directory (a "
                "FIFO, device, socket, or similar). Nothing has been "
                "exported. Remove it or replace it with an ordinary "
                "file or directory.")
    return copied


class ExportEscapesWorkspace(Exception):
    """A source resolved outside the workspace, so nothing is written."""


class ExportOverlapsWorkspace(Exception):
    """The destination and the live workspace are not disjoint."""


def _refuse_overlap(destination: Path, workspace: Path) -> None:
    """The destination must not be the workspace, inside it, or around it.

    This export replaces its destination, which is what makes it a snapshot
    rather than an accumulation — and what makes an overlapping destination
    destructive. Exporting into the workspace deleted the live store and left
    the two export files in its place, reported as success.

    Checked on resolved paths, before the staging directory is created and
    before anything is removed, so a refusal costs nothing.
    """
    destination = destination.resolve()
    workspace = workspace.resolve()

    if destination == workspace:
        raise ExportOverlapsWorkspace(
            f"{destination} is the workspace itself. Exporting there would "
            "replace the store with a copy of it. Nothing has been written.")
    try:
        destination.relative_to(workspace)
    except ValueError:
        pass
    else:
        raise ExportOverlapsWorkspace(
            f"{destination} is inside the workspace at {workspace}. The "
            "export replaces its destination, and the store lives here. "
            "Nothing has been written.")
    try:
        workspace.relative_to(destination)
    except ValueError:
        return
    raise ExportOverlapsWorkspace(
        f"{destination} contains the workspace at {workspace}. Replacing it "
        "would remove the store. Nothing has been written.")


def export(destination: Path) -> dict[str, object]:
    ensure_store()

    # Build the whole thing beside the destination and rename on success.
    #
    # Writing in place left a previous export's files behind: a memory page
    # deleted since yesterday survived into today's export, and the default
    # destination is date-based so the same directory is reused all day. A
    # partial write also looked complete. A fresh directory renamed at the end
    # gives an export that is either whole or absent.
    destination = destination.resolve()
    _refuse_overlap(destination, ledger_path().parent.parent)

    # Read before anything is created, not after: an unreadable table used
    # to become an empty one, which produced an export that looked
    # complete and was not — the failure mode this command exists to
    # avoid, so this is left to raise rather than caught. Reading it here,
    # before the staging directory exists, means that failure needs no
    # cleanup rather than needing the same cleanup as every failure below.
    data: dict[str, list[dict]] = {}
    with sqlite3.connect(ledger_path()) as conn:
        # One consistent snapshot across every table, not one per query —
        # without this, a writer committing between two of these SELECTs
        # could produce, for example, an obligation exported here whose
        # source item is missing from the `items` this same export wrote.
        conn.execute("BEGIN")
        try:
            for table in TABLES:
                data[table] = rows(conn, table)
        finally:
            conn.execute("ROLLBACK")  # a read transaction; nothing to keep

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".export-", dir=destination.parent))

    workspace = ledger_path().parent.parent
    try:
        # `chmod` inside the try too: staging exists the moment `mkdtemp`
        # returns, so any failure from here on, including this one, must
        # go through the same cleanup as every other failure below.
        os.chmod(staging, 0o700)
        # Status and text captured together, under each skill's own lock
        # — not a status check and a separate filesystem copy as two
        # unlocked reads a concurrent apply/fork/remove could land
        # between, leaving the two disagree with each other.
        snapshot, recovery = skill_override_bundle.capture(workspace.parent)
        _write_private(staging / "skill-overrides-recovery.json",
                       json.dumps(recovery, indent=2, ensure_ascii=True))
        overrides = [report for report, _text in snapshot]
        _write_private(staging / "store.json",
                       json.dumps({**data, "skill_overrides":
                                  _overrides_as_dicts(overrides)},
                                  indent=2, ensure_ascii=False))
        _write_private(staging / "store.md", as_markdown(data, overrides))

        copied = 0
        memory_src = workspace / "memory"
        if _top_level_export_source_is_dir(memory_src):
            _copy_inside_workspace(memory_src, staging / "memory", workspace)
            copied = sum(1 for _ in (staging / "memory").rglob("*.md"))

        policy_src = workspace / "policy"
        if _top_level_export_source_is_dir(policy_src):
            _copy_inside_workspace(policy_src, staging / "policy", workspace)

        # Keep the readable override copies beside the complete recovery
        # bundle. Both came from the same globally locked snapshot.
        for report, text in snapshot:
            if text is None:
                continue
            override_path = (staging / "skill-overrides" / "overrides"
                            / report.skill / "SKILL.md")
            override_path.parent.mkdir(parents=True, exist_ok=True)
            _write_private(override_path, text, errors="surrogateescape")

        _narrow(staging)

        # Replace whatever was there. An export is a snapshot, not an
        # accumulation. Kept inside the same cleanup ownership as
        # everything built above it, not after: a failure publishing an
        # otherwise-complete export — the destination being an existing
        # regular file `rmtree` cannot remove, `os.replace` itself
        # failing across a filesystem boundary, or anything else — must
        # not leave the complete, sensitive staging tree behind either.
        # Strict `lstat`-based checks, not `Path.is_dir()`/`.exists()`:
        # those fold any `OSError` into `False`, which here would mean
        # skipping removal of a destination this process genuinely
        # could not inspect and then failing `os.replace` right after,
        # for the same silent-omission reason every other strict check
        # in this recipe exists.
        if _is_dir_strict(destination):
            shutil.rmtree(destination)
        elif _lexists_strict(destination):
            destination.unlink()
        os.replace(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "to": str(destination),
        "obligations": len(data.get("obligations", [])),
        "messages": len(data.get("items", [])),
        "events": len(data.get("events", [])),
        "memory_pages": copied,
        "skill_overrides": len(overrides),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--to", type=Path,
                        default=Path(f"export-{date.today().isoformat()}"),
                        help="directory to write into")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export(args.to)))
    except ExportOverlapsWorkspace as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ExportEscapesWorkspace as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"could not write the export: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
