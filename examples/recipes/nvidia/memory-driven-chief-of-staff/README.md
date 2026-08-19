<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Memory-Driven Chief of Staff

Keeps a locally-authoritative, revisable record per inbound email and Slack
message — re-judged on a schedule, re-ranked under fixed caps, and updated by
the user's own ignores and priority overrides — without ever writing back to
the source.

This first contribution is the store and its tests. It runs with no email
account, no Slack workspace, and no network: a fixture corpus exercises the
same code path a live source would.

## Why it exists

Agent runtimes give you somewhere to put what the agent knows, but it is a
notepad. Nothing validates an entry, indexes it, links it, ages it, or repairs
it, so over weeks the store either bloats or drifts and nothing detects
either.

A second kind of thing also needs remembering, and it is not a fact. It is a
judgment about an item some other system owns: this needs a reply, it ranks
third this week, it is snoozed until Thursday, and it was demoted because the
user overrode the ranking twice. A mailbox has no field for that, and writing
it back would mutate the user's real data to store the agent's opinion.

The consequence worth watching is what happens to a message that shouts. An
"URGENT, closes Friday" notice that matches nothing the person chose to work
on is capped at the middle tier, while a quieter request that maps to their
stated priorities is not. A ranking with no memory behind it cannot tell those
two apart.

## What is in this contribution

| Path | What it is |
| --- | --- |
| `profile/schema.md` | The memory contract: six page types, index rules, provenance, decay, growth ceilings |
| `profile/scripts/schema.sql` | The ledger: items, obligations, an append-only audit trail, and source cursors |
| `profile/scripts/ranking.py` | Cap-and-cascade tier assignment, deterministic |
| `profile/scripts/memory_check.py` | Invariant detection over the memory, deterministic |
| `profile/scripts/preferences.py` | Correction counting against a fixed threshold |
| `profile/scripts/apply_decisions.py` | Applies model decisions; the model never emits SQL |
| `profile/scripts/migrate.py` | Schema versioning, forward-only |
| `profile/scripts/normalize.py` | Source payloads to store rows, kept separate from any I/O |
| `profile/scripts/_db.py` | Connection and transaction boundary |
| `profile/scripts/load_fixtures.py` | Replays the fixtures through the real ingest path |
| `profile/skills/` | Five skills: judging, review, repair, consolidation, preference update |
| `fixtures/` | Eight synthetic messages and a seed memory |

Later contributions add the host-side installer and scheduler integration, then
the optional Microsoft Graph and Slack connectors.

## Requirements

- Python 3.10 or newer. Nothing else for the fixture path.
- Hermes 0.19.0 or newer if you install the profile into a runtime. The
  measurements in this README were taken against 0.19.0, the version the
  current NemoClaw agent image pins.

No credentials of any kind are required to run everything below.

## Try it

```bash
cd examples/recipes/nvidia/memory-driven-chief-of-staff
export HERMES_HOME=$(mktemp -d)
python3 profile/scripts/load_fixtures.py --fixtures fixtures
python3 profile/scripts/load_fixtures.py --fixtures fixtures
```

The loader replays the fixtures through the same normalization and writer path
a live collector uses, and prints how many records it stored. The second run
adds nothing, because intake is keyed on the source's own id. Keeping
`HERMES_HOME` in the environment across both runs is what makes that
observable; a fresh directory each time would simply load the fixtures twice.

Check the seeded memory against its own schema:

```bash
python3 profile/scripts/memory_check.py
```

## Verify

```bash
cd profile/scripts
for t in tests/*.py; do python3 "$t" || break; done
```

Fifty-nine tests, no network and no credentials. They cover the ten acceptance
criteria agreed on the proposal issue, plus two areas the issue does not
enumerate:

| Criterion | Where |
| --- | --- |
| Schema migration | `tests/test_migration.py` |
| Invariant repair, idempotency, compaction detection | `tests/test_memory_check.py` |
| Concurrency, crash recovery, reinstall survival, no source mutation | `tests/test_durability.py` |
| Bounded ranking | `tests/test_ranking.py` |
| Preference updates | `tests/test_preferences.py` |
| Source normalization | `tests/test_normalize.py` |
| Writer behaviour and audit trail | `tests/test_apply_decisions.py` |

Two of these are constraints rather than observations. One scans every module
for write verbs and source-mutating calls, so "never writes back to the source"
stays true as the code grows. The other asserts that no path is both user-owned
and distribution-owned, since a name in both sets would be destroyed silently
on every update.

## Where state lives

The store is at `$HERMES_HOME/workspace/ledger/state.db` and the memory at
`$HERMES_HOME/workspace/memory/`. Both are under `workspace`, which a
distribution install and update leave alone — measured, not assumed: a row
written there survived both `hermes profile install --force` and
`hermes profile update` on Hermes 0.19.0.

Both directories are created private to their owner. The ledger holds
message subjects, senders, and bodies once a real source is connected.

## Privacy

Nothing in this contribution reaches a network or reads a real account. The
handling below applies once the optional connectors land, and is stated here
because it shapes the schema you are reviewing.

- Attachments are never fetched.
- Recipient lists are reduced at ingest to one value — addressed, mentioned, or
  merely copied — rather than retained.
- Message bodies are cleared on a schedule; metadata and the audit trail are
  kept, so history stays inspectable without content sitting on disk.
- An item deleted at the source is tombstoned locally and its body cleared
  immediately.
- Senders, domains, and channels can be excluded at ingest, before anything is
  written.

## Fixtures

Written from scratch. The people, the company, the projects, and every message
body are invented; nothing is derived from a real mailbox or an anonymized copy
of one. See `fixtures/README.md` for what each record is a control for.

## Cleanup

The fixture path writes only inside the `HERMES_HOME` you pass it. Remove that
directory and nothing remains.

## Known limitations

- Scheduled jobs are not part of this contribution. The store is exercised by
  the loader and the tests; job registration arrives with the installer.
- Compaction is detected but not performed here. Detection is mechanical and
  testable; deciding what to compact needs the skill, which needs a model.
- The memory ships with a seed that passes its own checks. It is a
  demonstration, not a starting point for real use.

## Intended users and support boundary

One person's own work stream, on a machine they control. It is an example
rather than a product: there is no support commitment, and catalog placement
is for discovery rather than a maturity claim.

## Dependencies

Standard library only. No third-party Python package is imported by any module
in this contribution, so nothing is added to the repository's third-party
notices.

## Sandbox and policy

This contribution reaches no network and requires no policy grant. It ships
five skill files that a runtime loads, and scripts that read and write only
inside `HERMES_HOME`. Network egress and provider permissions arrive with the
connectors in a later phase and will be documented there.

## Startup

Nothing to start. The scripts run on demand; scheduled jobs arrive with the
installer in a later phase.

## Provenance

NVIDIA-authored. Proposed and reviewed in issue #122.
