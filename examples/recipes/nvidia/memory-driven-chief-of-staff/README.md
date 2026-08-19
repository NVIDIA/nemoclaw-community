<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Memory-Driven Chief of Staff

Keeps a locally-authoritative, revisable record per inbound email and Slack
message — re-judged on a schedule, re-ranked under fixed caps, and updated by
the user's own ignores and priority overrides — without ever writing back to
the source.

This first contribution is the store, its tests, and a walkthrough that runs
the whole mechanism end to end. It needs no email account, no Slack workspace,
no network, and no inference endpoint: a fixture corpus exercises the same code
path a live source would, and one recorded model turn stands in for the one
step that would otherwise need a model.

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
| `profile/distribution.yaml` | The manifest: what an install replaces, and what it leaves alone |
| `profile/SOUL.md` | The persona, including the rule that answers come from the memory or not at all |
| `profile/schema.md` | The memory contract: six page types, index rules, provenance, decay, growth ceilings |
| `profile/scripts/schema.sql` | The ledger: items, obligations, an append-only audit trail, and source cursors |
| `profile/scripts/ranking.py` | Cap-and-cascade tier assignment, deterministic |
| `profile/scripts/memory_check.py` | Invariant detection over the memory, deterministic |
| `profile/scripts/preferences.py` | Correction counting against a fixed threshold |
| `profile/scripts/apply_decisions.py` | Applies model decisions; the model never emits SQL |
| `profile/scripts/migrate.py` | Schema versioning, forward-only |
| `profile/scripts/normalize.py` | Source payloads to store rows, kept separate from any I/O |
| `profile/scripts/_db.py` | Connection and transaction boundary |
| `profile/scripts/correct.py` | The user's writer: pins, ignores, and the only source of `actor='user'` events |
| `profile/scripts/load_fixtures.py` | Replays the fixtures through the real ingest path |
| `profile/scripts/walkthrough.py` | The fixture walkthrough, end to end, with no credentials and no model |
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
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

Seven steps, about a screen and a half of output:

1. **Collect.** The fixtures go through the same normalization and writer path
   a live collector uses. Nothing is judged yet — this is what ingestion alone
   produces.
2. **Judge.** One recorded model turn (`fixtures/envelopes/intake.json`) is
   applied by the real writer. Three rows pass the intent gate, so the top tier
   holds three, not ten; it is never padded. The mandatory expense-attestation
   deadline ranks fourth and is capped at the middle tier, because the user
   never chose it. That is the behaviour a ranking without a memory cannot
   produce.
3. **Correct.** The user pins a gate-passing row down. It leaves the top tier,
   because a pin outranks what the memory inferred, and the whole open list is
   re-ranked around it.
4. **Correct again.** A row is ignored outright and leaves the open list.
5. **Re-judge.** A later pass tries to restore the pinned row and cannot. An
   agent pass never clears `manual_priority`.
6. **Learn.** The corrections on record are counted against the threshold a
   policy rule needs. Two do not reach it, and the walkthrough says so rather
   than manufacturing a third.
7. **Verify.** The memory is checked against its own schema — then a field is
   removed on purpose so you can watch the check fail, and restored.

The one recorded model turn is the only thing standing in for inference.
Everything downstream of it is the shipped code. The walkthrough says which is
which on screen, and `fixtures/README.md` says it again.

To watch ingestion on its own, or to confirm it is idempotent:

```bash
python3 profile/scripts/load_fixtures.py --fixtures fixtures
python3 profile/scripts/load_fixtures.py --fixtures fixtures
```

The second run adds nothing, because intake is keyed on the source's own id.
Keeping `HERMES_HOME` across both runs is what makes that observable; a fresh
directory each time would simply load the fixtures twice.

The individual pieces are callable on their own:

```bash
python3 profile/scripts/memory_check.py                          # invariants
python3 profile/scripts/correct.py priority <source_id> low      # pin a tier
python3 profile/scripts/correct.py ignore <source_id>            # stop tracking
```

## Verify

```bash
cd profile/scripts
for t in tests/*.py; do python3 "$t" || break; done
```

One hundred and seventeen tests, no network and no credentials. They cover the ten
acceptance criteria agreed on the proposal issue, plus three areas the issue
does not
enumerate:

| Criterion | Where |
| --- | --- |
| Schema migration | `tests/test_migration.py` |
| Invariant repair, idempotency, compaction detection | `tests/test_memory_check.py` |
| Concurrency, crash recovery, reinstall survival, no source mutation, profile-home resolution, installation | `tests/test_durability.py` |
| Bounded ranking | `tests/test_ranking.py` |
| Preference updates | `tests/test_preferences.py` |
| Source normalization | `tests/test_normalize.py` |
| Writer behaviour, audit trail, caps across batches | `tests/test_apply_decisions.py` |
| The walkthrough, and every claim it prints | `tests/test_walkthrough.py` |

Two of the three are constraints rather than observations. One scans every
module for write verbs and source-mutating calls, so "never writes back to the
source" stays true as the code grows. The other asserts that no path is both
user-owned and distribution-owned, since a name in both sets would be destroyed
silently on every update.

The third runs the walkthrough and asserts what it printed. Documentation that
executes is worth shipping only while its narration is still true, so each
claim it makes on screen — the gate bounding the top tier, loud urgency staying
out of it, the pin surviving a later pass — is an assertion against the store it
produced.

## Where state lives

The store is at `$HERMES_HOME/workspace/ledger/state.db` and the memory at
`$HERMES_HOME/workspace/memory/`. Both are under `workspace`, which a
distribution install and update leave alone — measured, not assumed: a row
written there survived both `hermes profile install --force` and
`hermes profile update` on Hermes 0.19.0.

Both directories are created with owner-only permissions (`0700`). That is a
filesystem access control, not encryption: it stops another account on the same
machine from reading the store, and it does nothing against anyone who can read
the disk. The ledger holds message subjects, senders, and bodies once a real
source is connected, so before a connector stores real messages this recipe
requires either an encrypted volume underneath `$HERMES_HOME` or an
application-level encryption design. That requirement is separate from
credential custody, which is the gateway's job and never the store's.

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
  immediately — **for Microsoft Graph only**, whose delta query reports
  deletions explicitly. Slack has no equivalent on the surface this recipe
  reads: a deleted message simply stops appearing in `conversations.history`,
  and its absence from a bounded, paginated read is indistinguishable from it
  being outside the window. Reliable deletion notice needs the Events API or
  RTM, which this design does not use. So for Slack the guarantee is the weaker
  one it can actually keep: content ages out on the scheduled body-clearing
  pass, rather than at the moment of deletion.
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
  the walkthrough and the tests; job registration arrives with the installer.
- The walkthrough's judgment step is a recorded envelope, not a live model
  turn. It is the honest limit of a fixture corpus: everything downstream of
  that one file is the shipped code, and nothing upstream of it is.
- Compaction is detected but not performed here. Detection is mechanical and
  testable; deciding what to compact needs the skill, which needs a model.
- The memory ships with a seed that passes its own checks. It illustrates the
  schema; it is not a starting point for real use.
- Paths in the skills are written against `$HERMES_HOME` rather than relative
  to a working directory. This is not stylistic: the agent's working directory
  is not the profile home, and a relative path resolves to nothing. An
  unreadable memory is indistinguishable from an empty one, so the failure is
  silent — the agent answers confidently from nothing rather than reporting an
  error.

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
