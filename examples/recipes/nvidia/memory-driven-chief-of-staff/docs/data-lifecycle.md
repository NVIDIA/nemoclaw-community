<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# What is kept, and how to be rid of it

Four controls, all of them local, none of them requiring a connector. They
work on the fixture corpus today, which is how they are tested, and they apply
unchanged to real messages when a connector lands. That order is deliberate:
the controls ship before the thing that would need them.

Every command below runs from `profile/scripts/`, against the store belonging
to the profile named by `HERMES_HOME`.

## Bodies age out; the record does not

`retention.py` runs daily at 02:00 and clears the text of anything past the
window. Thirty days by default:

```bash
python3 retention.py --dry-run   # what would go, nothing changes
python3 retention.py             # clear it
RETENTION_DAYS=7 python3 retention.py
```

Those two change the run in front of you. To change every run after it, put
the value in the profile's environment file — `hermes config env-path` prints
where it is, `$HERMES_HOME/.env`:

```bash
ENV=$(hermes -p <profile> config env-path)
echo 'RETENTION_DAYS=7' >> "$ENV"
```

That file is the supported path and the only one that persists. `hermes cron
create` and `cron edit` take no environment argument, so a variable exported
in a shell reaches the manual invocation and nothing scheduled. A value set
there and never checked is the failure worth naming: the window looks changed
and the nightly pass keeps using thirty days.

Values below 1 or above 3650 are refused: a zero
would clear the message that arrived a minute ago, and a negative one would
put the cutoff in the future and clear everything ever stored. Both are the
kind of mistake found only afterwards.

What a cleared row keeps:

| Kept | Gone |
| --- | --- |
| sender, subject, timestamp, addressing, state | the message body |
| the obligation and the title the judging turn wrote | |
| every event, with its actor and its before and after | |

So a month later you can still see that Dana asked about the cutover on the
third, that it ranked high because the memory said you had chosen that work,
and that you ignored it on the fifth. You cannot re-read Dana's words. That is
the intended line, not a limitation of the implementation.

`subject` stays with the metadata. On email it is often the only
human-readable handle a row has, it is what the obligation title came from,
and it is short enough that keeping it is not keeping the message.

`body_cleared_at` records that a body was cleared. Without it a message
somebody wrote and a join notice that never had a body are the same row —
`body IS NULL` — and only one of them is a loss.

## Some things are never written at all

Rules live in `$HERMES_HOME/workspace/exclusions.json`:

```json
{
  "senders":  ["recruiter@agency.example", "U01RECRUIT"],
  "domains":  ["agency.example"],
  "channels": ["C0SALARY01", "D0PRIVATE1"]
}
```

A sender matches `sender` — a display name or an address, depending on the
source — and also the raw id when the collector knows one, so a Slack user can
be excluded by `U…` rather than by a name they can change. A domain matches
the part after `@`. A channel matches `scope`, which is the mail folder or the
Slack channel id.

Matching is case-insensitive and exact. There are no globs: a pattern language
here is a way to exclude more than intended by accident, and the failure is
silent — nothing arrives, and nothing says why.

The rules are applied in `insert_items`, the one function every writer passes
through, rather than in any collector. So an excluded message is never written
by the fixture loader, by the Slack collector when it lands, or by anything
added later, without each of them having to remember — and a new writer cannot
quietly opt out. Filtering at display would leave the text on disk, which is
no use to somebody excluding their doctor.

A dropped message is reported on stderr as a count, never as content:

```
exclusions: 2 message(s) not stored
```

A malformed `exclusions.json` stops the insert. Nothing is written until it
is fixed, and the error names the file, the line and the column.

That is the opposite of what an earlier version did, and the reasoning is
worth stating because the other direction is tempting. Failing open keeps
collection running through a typo, at the cost of writing exactly what the
file was created to keep out — and the user learns about it from the row on
disk. A stalled pipeline is loud and recoverable; a silent breach of the one
guarantee this file provides is neither.

Fail-closed means strict about shape as well as syntax. An unknown key is
rejected rather than ignored: `{"sender": [...]}` parses cleanly, matches
nothing, and reads as a working rule. A non-string entry is rejected rather
than coerced, for the same reason — `123` would become the rule `"123"` and
match nothing.

## Take a copy

```bash
python3 export_store.py              # to ./export-<date>/
python3 export_store.py --to ~/out
```

Writes `store.md` and `store.json` side by side — the first to read, the
second to process — and copies the memory and the learned preference policy
whole.

Each export is a snapshot rather than an accumulation. The whole thing is
built beside the destination and moved into place at the end, so a previous
export cannot leave a deleted page behind in the next one — which the
date-based default directory makes likely, since the same path is reused all
day — and a failure part-way leaves no directory at all rather than one that
looks complete.

Nothing outside the workspace is read. A symbolic link under `memory/` that
points elsewhere on the machine stops the export rather than pulling that file
into something the user is about to hand to somebody. Nothing is summarised
and nothing is omitted; an export that quietly
left something out would answer the question wrongly.

A body cleared by the retention pass appears as `text cleared <timestamp>`
rather than as an empty line, so the export distinguishes the same two cases
the schema does.

## Be rid of all of it

```bash
python3 reset.py --dry-run
python3 reset.py --yes
```

Removes the store, the memory, the learned policy and the collection
bookkeeping, and reports each. It refuses without `--yes`, and if any part
cannot be removed it says so and exits non-zero — a reset that half worked
must not read as one that worked. The policy goes with the rest because it
encodes what its subject ignores, which is about them.

The credential is not removed, because it was never held here: it lives with
the OpenShell gateway. `reset.py` prints the commands to revoke it, since
somebody withdrawing consent wants both and would otherwise stop after the one
that felt complete.

## Where the guarantee is weaker

For Microsoft Graph, an item deleted at the source is tombstoned locally and
its body cleared at once, because the delta query reports deletions
explicitly.

Slack offers no such notice. A deleted message stops appearing in
`conversations.history`, and its absence from a bounded, paginated read cannot
be told apart from it lying outside the window. Reliable notice needs the
Events API, which this design does not use; the legacy RTM API carries the
event too, but Slack states that granular-permission apps cannot use it and
that classic apps can no longer be created. So Slack content ages out on the
scheduled pass rather than at the moment of deletion. That is the weaker
guarantee, stated rather than implied.

## Upgrading a store that predates this

`body_cleared_at` arrived with schema v2. An existing v1 store is brought
forward in place:

```bash
python3 migrate.py            # bring the store to the current schema
python3 migrate.py --check    # report the version, change nothing
```

You rarely need either. Migration happens on its own: `ensure_store()` is the
only way anything opens the store, and every executable here goes through it,
so the first job to run after an upgrade migrates it. The command exists for
doing it deliberately, before a scheduled job does it unattended.

The column is added if it is absent and the version is recorded; running it
twice does nothing the second time. `schema-v1.sql` is kept beside
`schema.sql` as the frozen text of what actually shipped, so the migration is
tested against the real prior state rather than against the current schema
with a column removed.
