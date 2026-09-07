<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Customizing a shipped skill

`hermes profile install --force` and `hermes profile update` both copy every
entry `skills/` has in the shipped distribution straight over whatever is
already installed, unconditionally. A hand-edited `skills/<name>/SKILL.md`
survives exactly until the next install or update, then is gone with no
warning. This is an instruction-authority boundary: a place a user can tune a
skill's instructions, or pin a fix for something the shipped version gets
wrong, that survives an update — and, just as important, a boundary that does
not let a stale customization silently block a shipped update from taking
effect either. Both failure directions matter; this document describes how
each is actually handled, not just the happy path.

All of it is implemented in `profile/scripts/skill_overrides.py`. Read that
file's own top-of-file docstring for the exact mechanics (locking, crash
recovery, path safety); this document is the model a user or an operator
needs, not the implementation.

## Where an edit actually lives

Never edit `skills/<name>/SKILL.md` directly — it is overwritten wholesale on
the next `hermes profile install`/`update`, with no warning. The one location
that survives is `workspace/skill-overrides/overrides/<name>/SKILL.md`. It is
never committed into this recipe's own distributed `profile/` source tree, so
Hermes's copy step — which only ever replaces a name present in the source it
is copying from — never touches it; it is also nested under `workspace/`,
which Hermes's installer treats as reserved regardless of any recipe's own
manifest, for a second, independent reason it survives.

An override sitting in that directory does nothing on its own. Hermes only
ever reads instructions from `skills/`, never from
`workspace/skill-overrides/`. Something has to copy a validated override's
text over the shipped copy — that is `--apply`, described next.

```bash
python3 profile/scripts/skill_overrides.py --fork <skill>    # start an override from the shipped copy
# edit workspace/skill-overrides/overrides/<skill>/SKILL.md by hand
python3 profile/scripts/skill_overrides.py --check           # report what --apply would do, write nothing
python3 profile/scripts/skill_overrides.py --apply           # validate and apply every override
python3 profile/scripts/skill_overrides.py --remove <skill>  # delete an override, restore the latest shipped version
```

## When it takes effect

`--apply` runs at two points, and only two: once, immediately, right after
`install.sh` finishes on a fresh setup or a `hermes profile update`; and again
on every scheduled tick a cron job fires — hourly, at :15, with no wake gate
(applying an override involves no judgment, so it never costs an agent turn).
That second point is what makes an override self-healing after a bare
`hermes profile update` run directly by the user, which never touches
`install.sh` at all: within the hour, the scheduled tick notices the shipped
file changed underneath the override and re-applies it — or, if the shipped
skill itself changed, refuses and says so (see "Staleness" below) rather than
guessing.

## Statuses and exit codes

Every run of `--check`, `--apply`, `--fork`, or `--remove` prints one JSON
finding per skill it looked at, each with a `kind`. The process exits
non-zero if any finding's `kind` is one that needs attention; a human or a
monitoring system watching the scheduled job's exit code should treat that,
not the presence of any particular text, as the signal.

<!-- markdownlint-disable MD013 -->
| Kind | Exit status | Meaning |
| --- | --- | --- |
| `applied` | 0 | The override is live and matches the shipped version it was forked from. |
| `forked` | 0 | `--fork` created a new override from the currently shipped copy. |
| `removed` | 0 | `--remove` restored the skill to the latest shipped content it has ever observed. |
| `skipped-exists` | 0 | `--fork` refused: an override for this skill already exists. |
| `skipped-no-override` | 0 | Nothing to do — this skill has no override and no record of one. |
| `reconciled-abandoned` | 0 | A pending operation's skill no longer exists; its record was cleared rather than left blocking forever. |
| `reconciled-complete` | 0 | A crash left a write's completion bookkeeping unfinished; this run finished it. |
| `reconciled-retry` | 0 | A crash left a write that never actually happened; it will be retried (`--apply` on its own schedule; `--remove`, only by running it again). |
| `skipped-stale` | **non-zero** | The override's shipped base has moved on since it was forked — see "Staleness" below. Not applied. |
| `orphaned-override` | **non-zero** | This skill is no longer shipped at all, but an override for it still exists. |
| `skipped-invalid` | **non-zero** | The override fails validation (missing frontmatter, an unrecognized `based_on_sha256`, or similar) and was not applied. |
| `skipped-no-base` / `skipped-missing-base` | **non-zero** | `--remove` has nothing safe to restore to — no retained shipped version, or the retained one is missing or corrupt. Nothing was touched. |
| `skipped-unknown-skill` | **non-zero** | `--fork` refused: no shipped skill by that name. |
| `blocked` | **non-zero** | A prior operation on this skill is still unresolved (diverged content, or a different kind of pending operation) — resolve it by hand before this skill is touched automatically again. |
| `reconciled-diverged` | **non-zero** | Live content matches neither what a pending operation expected before nor after — something outside this module changed it. Left untouched; automated apply/remove on this skill is blocked until a human resolves it. |
| `reconciled-error` / `error` | **non-zero** | This skill's own processing failed unexpectedly (a lock could not be acquired, the database is unreadable, and similar). Every other skill is still processed normally. |
<!-- markdownlint-enable MD013 -->

## Staleness: what happens when the shipped skill moves on

`based_on_sha256`, a field in every override's frontmatter, records exactly
which shipped version the override was forked from. `--apply` compares that
against the latest shipped version this module has actually observed for
that skill — not against whatever happens to be live right now, since live
may already be the override itself.

When they match, the override applies normally. When they do not — the
shipped skill changed since the fork, whether from a real `hermes profile
update` or simply time passing — `--apply` refuses to apply it, reports
`skipped-stale`, and exits non-zero. It does not try to merge the two, and it
does not silently let either one win: the update is left in effect (or, if
this is the first tick to notice, the override is simply not written over
it), and the override is left exactly as the user wrote it, untouched.

This is deliberate, and it runs in both directions on purpose. An override
that always won regardless of staleness would mean a newer shipped safety or
correctness fix could be silently reverted by content nobody had reviewed
against it — the quieter of the two dangers a customization layer like this
one has to guard against, the louder one being an update that discards a
user's tuning outright. Refusing avoids the quiet failure without
reintroducing the loud one: the user's edit is never discarded, and a routine
shipped update is never silently overwritten by something older either.

**Resolving it** is one command: `--fork <skill>` again. That starts a fresh
override validated against the current shipped version; the user then
re-applies whatever they changed by hand into the new file. There is no
automatic three-way merge — a fork is a deliberate, reviewed act, and staying
that way is what keeps the "is this override still coherent with what's
shipped" question mechanical rather than guessed at.

## Orphaned overrides

If a skill an override exists for is no longer shipped at all (removed
upstream, or renamed), `--check`/`--apply` report `orphaned-override` rather
than silently ignoring it. `--remove` still works on an orphaned override —
it restores the last known content into a fresh `skills/<name>/` directory,
which a subsequent install leaves alone (its copy step only ever
adds/overwrites names present in its own staged source, never deletes a
target name absent from it) — an orphan the user is then free to delete by
hand.

## Rollback

Two levels, both already covered above:

- **One skill:** `--remove <skill>` deletes that skill's override and
  restores the latest shipped content this module has ever observed for it —
  regardless of whether an override file currently exists for it (a
  completed application, or an application still pending when the write
  crashed, both count as customized state to undo).
- **Everything:** `python3 profile/scripts/reset.py --yes` restores every
  currently active override to shipped content and deletes the whole
  `workspace/skill-overrides/` tree, as part of the same full-profile reset
  documented in [docs/data-lifecycle.md](data-lifecycle.md#be-rid-of-all-of-it).
  If any skill's restoration cannot be completed safely — a missing retained
  base, a genuinely diverged pending operation — reset deletes nothing at
  all rather than leave a partial result that reads as success.

## Export and restore limitations

`python3 profile/scripts/export_store.py` copies each override's own text,
byte-for-byte, but deliberately not the retained shipped-version history its
`based_on_sha256` validates against, nor the operation journal. Both are this
feature's own internal bookkeeping, not something the user wrote, and both
stay behind. The practical effect: copying an exported override straight
back into `workspace/skill-overrides/overrides/<skill>/` and running
`--apply` is not guaranteed to fail, and not guaranteed to succeed — it
depends on whether the shipped skill moved between export and restore, the
same staleness check described above. If it did not move, the copy applies
cleanly. If it did, `--apply` refuses with `skipped-invalid` (the
`based_on_sha256` was never observed on that profile) rather than silently
applying stale content, and the way back is the same one-command fork
described in "Staleness." A full self-contained recovery bundle — one an
`import` command could restore from regardless of whether the shipped skill
moved on — does not exist; it is a larger, separate feature this export
intentionally does not attempt. See
[docs/data-lifecycle.md](data-lifecycle.md#take-a-copy) for what export
covers more broadly.

## Compatibility with a possible future skill-evolution module (#159)

[#159](https://github.com/NVIDIA/nemoclaw-community/issues/159) proposes an
optional, off-by-default module that would let `inbound-judging` and
`obligation-review` evolve from evidence, writing its findings to a sibling
file — `LEARNED.md` — under `workspace/`, with each shipped `SKILL.md`
carrying a small "read this file if present" instruction. That module does
not exist yet; nothing in this recipe implements it. The design intentionally
does not collide with what this document describes: this module patches
`SKILL.md`'s own instruction text directly, while #159 proposes a separate
file the instructions merely point to, so the two would touch different
files rather than the same one. The one interaction worth naming now, before
either changes: a `--fork`ed override is a full copy of the shipped
`SKILL.md`, including whatever "read `LEARNED.md`" instruction the shipped
version carries at fork time. A user who edits that part out (deliberately
or by accident) while customizing a skill would stop that skill from
consulting #159's evidence-driven notes, the same way editing out any other
shipped instruction would — this module has no special awareness of that
line and does not protect it differently from the rest of the file.
