<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Memory-Driven Chief of Staff

Memory-Driven Chief of Staff is a recipe that keeps a local, revisable record
for each inbound email and Slack message. It re-judges those records on a
schedule and re-ranks them under fixed caps. That re-judging runs on its own
once the next phase registers the scheduler jobs. The user's own ignores and
priority overrides change the ranking. The recipe never writes back to the
source system.

This first phase contains the store, its tests, and a walkthrough that runs it
from end to end. It needs no email account, no Slack workspace,
no network, and no inference endpoint. A fixture corpus exercises the same code
a live source would. Two recorded model turns stand in for the two steps that
would otherwise need a model: the intake judgment, in
`fixtures/envelopes/intake.json`, and the scheduled re-judgment, recorded
inline in `profile/scripts/walkthrough.py`.

## Concepts

These terms appear throughout this document and in the code.

| Term | Meaning |
| --- | --- |
| [Hermes](https://github.com/NousResearch/hermes-agent) | The agent runtime this recipe is packaged for. |
| Profile | One Hermes configuration: a persona, a set of skills, and the user's own data. The [profile guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/profiles.md) describes the layout. |
| Profile home | The directory holding one profile. The `HERMES_HOME` environment variable names it. |
| Store | The SQLite database of messages, obligations, and an audit trail, at `$HERMES_HOME/workspace/ledger/state.db`. |
| Memory | The Markdown pages describing the person, at `$HERMES_HOME/workspace/memory/`. |
| Obligation | One message that needs an action, with a tier, a position, and its own history. |
| Tier | The priority band an obligation sits in: `high`, `medium`, or `low`. |
| Envelope | The JSON document a model turn returns: a list of decisions for the writer to apply. The recipe's recorded turns are envelopes. |
| Addressing | Whether a message was aimed at the user: `direct`, `mentioned`, or `broadcast`. Ingest derives it from the recipient list, which is not stored. |
| Intent gate | The rule that admits an obligation to the `high` tier only if the memory shows the user chose that work. External urgency alone does not qualify. |
| Cascade | What happens to an un-gated row that ranked inside the top ten: it drops into the competition for `medium` rather than out of the list. |
| Reservation | The rule that keeps `high` for gate-passing rows. If fewer pass than the cap allows, the tier stays smaller rather than being filled from the remainder. |
| Gate verdict | The recorded per-message answer to the intent gate: whether the memory shows the user chose this work. Stored as `intent_gated`. |

## Why it exists

A personal assistant is only useful if it remembers one person accurately: who
they work with, what they are accountable for, and what they have already
decided. Hermes's built-in memory holds that as free-form notes in `MEMORY.md`
and `USER.md`, under a fixed character budget. Nothing indexes a note, links it
to related notes, ages it, or repairs it. As the budget fills, the agent is
asked to consolidate by hand, and nothing detects a note that has quietly
drifted out of date. Hermes also ships optional external memory providers; this
recipe requires none of them, and keeps its own record local under a schema it
can check.

A second kind of record is not a fact but a judgment about a message that
another system owns. Examples: this message needs a reply, it ranks third this
week, it is snoozed until Thursday, it was demoted because the user overrode
the ranking twice. A mailbox has no field for a judgment like that. Writing one
back into the mailbox would change the user's real data to store the
assistant's opinion.

The clearest consequence is how the recipe treats a message that announces its
own urgency. A message whose subject reads `URGENT: expense policy
attestation closes Friday`, matching nothing the person chose to work on, is
capped at the middle tier. A quieter request that maps to
their stated priorities is not. A ranking with no memory behind it cannot tell
those two apart.

## What is in this recipe

| Path | What it is |
| --- | --- |
| `profile/distribution.yaml` | The manifest: what an install replaces, and what it leaves alone |
| `profile/SOUL.md` | The persona, including the rule that answers come from the memory or not at all |
| `profile/schema.md` | The memory contract: six page types, index rules, provenance, decay, growth ceilings |
| `profile/scripts/schema.sql` | The store: items, obligations, an append-only audit trail, and source cursors |
| `profile/scripts/ranking.py` | Cap-and-cascade tier assignment, deterministic |
| `profile/scripts/memory_check.py` | Invariant detection over the memory, deterministic |
| `profile/scripts/preferences.py` | Correction counting against a fixed threshold |
| `profile/scripts/apply_decisions.py` | Applies model decisions; the model returns an envelope and never writes SQL |
| `profile/scripts/migrate.py` | Schema versioning, forward-only. This recipe ships at v1, so there is nothing to upgrade from yet |
| `profile/scripts/normalize.py` | Source payloads to store rows, kept separate from the network calls |
| `profile/scripts/_db.py` | Connection and transaction boundary |
| `profile/scripts/correct.py` | The user's writer: pins, ignores, and the only source of `actor='user'` events |
| `profile/scripts/load_fixtures.py` | Replays the fixtures through the real ingest path |
| `profile/scripts/walkthrough.py` | The fixture walkthrough, end to end, with no credentials and no model |
| `profile/skills/` | Five skills: judging, review, repair, consolidation, preference update |
| `fixtures/` | Eight synthetic messages, a seed memory, and one recorded model turn |

Later phases add the host-side installer and scheduler integration, then the
optional Microsoft Graph and Slack connectors.

## Requirements

- Python 3.10 or newer. Nothing else is needed for the fixture path.
- Linux, macOS, or Windows under Windows Subsystem for Linux. Every command
  below is written for a POSIX shell. The shipped skill files declare
  `platforms: [linux]`, which applies from the installer phase onward rather
  than to the fixture path.
- No credentials of any kind.

Installing the profile into a Hermes runtime is out of scope for this phase;
the installer arrives with the next one. When that phase lands, installing will
require Hermes 0.19.0 or newer: `profile/distribution.yaml` declares
`hermes_requires: ">=0.19.0"`. On 0.19.x the manifest's `distribution_owned`
list is validated but not yet honoured by the copy — the path-aware allowlist
first shipped in 0.20.0 — which changes nothing for this recipe, because what
it ships and what it declares are the same set, and a test keeps them so.

Nothing in the fixture path needs Hermes. The same 0.19.0 figure under
[Where state lives](#where-state-lives) records the version the persistence
claim was measured against.

## Try it

Run the walkthrough from the recipe root. It prints seven steps and exits `0`.
From the repository root:

```bash
cd examples/recipes/nvidia/memory-driven-chief-of-staff
export HERMES_HOME=$(mktemp -d)
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

The seven steps:

1. **Collect.** The fixtures go through the same normalization and writer path
   a connector will use. Nothing is judged yet. This is what ingestion alone
   produces.
2. **Judge.** The first recorded turn (`fixtures/envelopes/intake.json`) is
   applied by the real writer. Three rows pass the intent gate, so the `high`
   tier holds three rather than its maximum of ten. The tier is never padded.
   The mandatory expense-attestation deadline ranks fourth and is capped at
   `medium`, because the recorded verdict says the user never chose that work.
   The step ends by re-running the shipped ranking over the same rows with the
   gate verdicts withheld: the `high` tier then holds none, which is what the
   reservation buys.
3. **Correct.** The user pins a gate-passing row to the bottom tier. It leaves
   the `high`
   tier, because a pin outranks what the memory inferred, and the whole open
   list is re-ranked around it.
4. **Correct again.** A row is ignored outright and leaves the open list.
5. **Re-judge.** The second recorded turn, written inline in the script rather
   than in `fixtures/`, tries to restore the pinned row and cannot. An agent
   pass never clears a user's pin.
6. **Learn.** The recorded corrections are counted against the threshold that a
   preference rule requires. Two corrections do not reach the threshold of
   three. The walkthrough reports that rather than inventing a third.
7. **Verify.** The memory is checked against its own schema. A required field
   is then removed on purpose, so the check is seen to fail as well as pass,
   and restored.

The two recorded turns are the only parts standing in for inference.
Everything downstream of them is the shipped code. One consequence is worth
being explicit about: the gate verdict on each row is part of the recorded
intake turn, because deciding it means reading the memory, which needs a model.
Deleting the seed memory therefore does not change the tiers this run
prints. It does change step 7, which checks the memory itself. What
the run does show is everything those verdicts feed into — the caps, the
reservation, the cascade, the writer, the correction path and the re-ranking —
and the contrast printed in step 2. For the ranking behavior itself, the
evidence is `tests/test_ranking.py` and `tests/test_apply_decisions.py`, which
drive the gate flags directly. The walkthrough states which parts are recorded
on screen, and [`fixtures/README.md`](fixtures/README.md) states it again.

To watch ingestion by itself, and to confirm that it is idempotent, use a
profile home the walkthrough has not already filled:

```bash
export HERMES_HOME=$(mktemp -d)
python3 profile/scripts/load_fixtures.py --fixtures fixtures
python3 profile/scripts/load_fixtures.py --fixtures fixtures
```

The first run reports `"added": 8` and the second reports `"added": 0`, because
intake is keyed on the source's own identifier. Both runs must use the same
profile home, or the second run has nothing to recognize.

The individual pieces are callable on their own, from the recipe root:

```bash
python3 profile/scripts/memory_check.py                     # invariants
python3 profile/scripts/correct.py priority <source_id> low # pin a tier
python3 profile/scripts/correct.py ignore <source_id>       # stop tracking
python3 profile/scripts/correct.py unignore <source_id>     # track it again
```

`correct.py` needs `HERMES_HOME` to name an existing profile home, and creates
or migrates the store there if it is absent. `memory_check.py` is the
exception: with no `HERMES_HOME` it falls back to `workspace/memory` under the
current directory, and it needs no store at all. Neither creates the profile
home itself.

A correction applies only where it means something, so on a populated store:

- All three refuse an obligation that is `done` and exit `3`. A completed
  obligation is history, and rewriting it would turn finished work into a
  standing instruction.
- `priority` also refuses an ignored row and exits `3`, printing the exact
  `unignore` command that restores it, ready to copy. The walkthrough ignores
  `msg-cc-only` in step 4, so a `priority` command against that row right
  afterwards reaches this.
- Repeating a correction that is already in force changes nothing. It prints
  `"changed": false` and exits `0`.
- With no matching obligation, `correct.py` exits `3`. With `HERMES_HOME`
  unset it exits `1` with an unhandled `RuntimeError` naming the variable, and
  `memory_check.py` exits `2` reporting that it found no memory.

## Verify

Run the test suite from `profile/scripts`. It needs no network and no
credentials. From the recipe root:

```bash
cd profile/scripts
fail=0
for t in tests/*.py; do python3 "$t" || fail=1; done
echo "failed=$fail"
cd ../..
test "$fail" -eq 0
```

Expected result: every file ends with `OK`, the eight files report 157 tests in
total, and the last line is `failed=0`. Do not use `|| break` here; a `for`
loop reports the status of its last command, so a failing test would still
leave the loop exiting `0`.

| What it covers | Where |
| --- | --- |
| Schema versioning | `tests/test_migration.py` |
| Invariant detection, idempotency, compaction detection | `tests/test_memory_check.py` |
| Concurrency, crash recovery, reinstall survival, profile-home resolution, installation, failed-write cause reporting, skill-path anchoring and existence | `tests/test_durability.py` |
| Bounded ranking, including user pins | `tests/test_ranking.py` |
| Preference counting | `tests/test_preferences.py` |
| Source normalization | `tests/test_normalize.py` |
| Writer behavior, audit trail, caps across batches, correction idempotency, correction state transitions, displaced-row audit | `tests/test_apply_decisions.py` |
| The walkthrough, and its central claims | `tests/test_walkthrough.py` |

Four points are worth calling out.

- `TestNoSourceMutation` in `tests/test_durability.py` scans every module for
  the common shapes of an HTTP write — `requests.post`, a `.patch(` call, and
  their siblings — and a companion test proves the scan fires on real
  examples, including `urlopen(url, data=…)` and a `subprocess` call to
  `curl`. Read it as a tripwire rather than a proof: it matches call shapes, so
  a write spelled in some further way could still pass it. What actually holds
  the property in this phase is that the recipe reaches no network at all;
  policy takes over once the connectors land.
- `test_nothing_this_example_ships_lands_on_a_user_owned_path`, also in
  `tests/test_durability.py`, asserts that nothing this recipe ships occupies a
  user-owned name, and that the user-owned and distribution-owned sets stay
  disjoint. Both directions fail, and neither is loud. Hermes never installs a
  shipped path whose top-level name is user-owned, so a shipped `workspace`
  would simply never land; and a store placed under a distribution-owned path
  is removed and replaced on every update, because that is what installing a
  distribution means.
- `tests/test_walkthrough.py` runs the walkthrough and asserts its central
  claims against the store the run produced: the gate bounding the top tier,
  loud urgency staying out of it, the pin deciding the tier and surviving a
  later pass, and both corrections being attributed to the user.
- Several of its tests assert against the printed output instead, because what
  is printed is itself a claim. They check six of them:
  - the run names which part is recorded;
  - it discloses both recorded turns;
  - it says the gate verdict is recorded;
  - it scopes the seed-memory claim to the tiers;
  - it shows the top tier emptying without the gate;
  - the memory check is seen to fail as well as pass.

  It does not assert every line the script prints.

## Where state lives

The store is at `$HERMES_HOME/workspace/ledger/state.db` and the memory is at
`$HERMES_HOME/workspace/memory/`. Both sit under `workspace`, which a
distribution install and update leave alone. That was measured rather than
assumed: a row written there survived both `hermes profile install --force` and
`hermes profile update` on Hermes 0.19.0.

Both directories are created with owner-only permissions (`0700`). That is a
filesystem access control rather than encryption. It stops another account on
the same machine from reading the store. It does nothing against anyone who can
read the disk.

Once a connector is attached, the store holds message subjects, senders, and
bodies. Before that happens, this recipe requires either an encrypted volume
underneath `$HERMES_HOME` or an application-level encryption design. That
requirement is separate from credential custody, which belongs to the runtime's
own credential handling — Hermes keeps provider credentials outside
`workspace` — and never to the store.

## Privacy

Nothing in this phase reaches a network or reads a real account.

One reduction already ships, because it is part of the schema under review:
recipient lists are never stored. Ingest reduces them to a single `addressing`
value — `direct`, `mentioned`, or `broadcast` — so the store never holds a
copy of who else was on a thread. `normalize.py` does this today, and
`tests/test_normalize.py` asserts it.

The rest of the handling below is not implemented yet. It describes what the
optional connectors will do, and is stated here because it shapes the schema.

Once a connector is attached:

- Attachments will not be fetched.
- Message bodies will be cleared on a schedule. Metadata and the audit trail
  will be kept, so history stays inspectable without content sitting on disk.
- For Microsoft Graph, an item deleted at the source will be tombstoned locally
  and its body cleared at once, because the delta query reports deletions
  explicitly.
- For Slack, that guarantee is not available. A deleted message stops appearing
  in `conversations.history`, and its absence from a bounded, paginated read
  cannot be told apart from it lying outside the window. Reliable notice
  requires the Slack Events API, which this design does not use. Slack's legacy
  Real Time Messaging (RTM) API carries the event too, but Slack states that
  granular-permission apps cannot use it and that classic apps can no longer be
  created, so it is not an option a connector could take today. Slack content
  will therefore age out on the scheduled body-clearing pass rather than at the
  moment of deletion.
- Senders, domains, and channels will be excludable at ingest, before anything
  is written.

## Fixtures

The fixtures were written from scratch. The people, the company, the projects,
and every message body are invented. Nothing is derived from a real mailbox or
from an anonymized copy of one. See [`fixtures/README.md`](fixtures/README.md)
for what each record is a control for.

## Cleanup

The fixture path writes application state only inside the profile home passed
to it:

```bash
rm -rf "$HERMES_HOME"
```

Each `mktemp -d` in this document creates a separate profile home. Remove each
one you made, not only the last.

Running the scripts also leaves a Python bytecode cache at
`profile/scripts/__pycache__/` in the checkout, unless the interpreter is
configured not to write one (`python3 -B`, or `PYTHONPYCACHEPREFIX`). The
repository `.gitignore` covers it, so it never appears in `git status`. Remove
it as well if you want the checkout byte-for-byte as you found it.

## Known limitations

- Scheduled jobs are not part of this phase. The store is exercised by the
  walkthrough and the tests; job registration arrives with the installer.
- The walkthrough's two judgment steps are recorded envelopes rather than live
  model turns. That is the limit of a fixture corpus, and the limit falls in a
  specific place: the gate verdict is recorded, so this run cannot show the
  memory producing it. Everything the verdicts feed into is the shipped code.
- Compaction is detected but not performed here. Detection is mechanical and
  testable. Deciding what to compact needs the skill, which needs a model.
- The memory ships with a seed that passes its own checks. It illustrates the
  schema; it is not a starting point for real use.
- The audit trail records one row per obligation a correction displaces, and
  `events` is append-only. That is deliberate — the store has to be able to
  explain why a row moved — but the cost scales with the open list: on a
  200-row list, one ignore writes a row for every obligation below the
  corrected one: 199 when it sat at the top, none when it sat at the bottom.
  A long-lived store with
  a large open list will need a compaction path for `reranked` events, which
  this phase does not provide.
- Paths in the skills are written against `$HERMES_HOME` rather than relative
  to a working directory. This is not a style choice. The agent's working
  directory is not the profile home, so a relative path resolves to nothing.
  An unreadable memory cannot be told apart from an empty one, so the failure
  is silent: the agent answers confidently from nothing instead of reporting an
  error.

## Intended users and support boundary

One person's own work stream, on a machine they control. This is a recipe
rather than a product. There is no support commitment, and catalog placement is
for discovery rather than a maturity claim.

## Dependencies

Standard library only. No module in this recipe imports a third-party Python
package, so nothing is added to the repository's third-party notices.

## Sandbox and policy

This phase reaches no network and requires no policy grant. It ships five skill
files that a runtime loads, and scripts that read the recipe's own files from
the checkout and write application state only inside the profile home. They
also leave a Python bytecode cache beside the scripts — see
[Cleanup](#cleanup). Network egress and provider permissions arrive with the
connectors in a later phase and will be documented there.

## Startup

Nothing to start. The scripts run on demand. Scheduled jobs arrive with the
installer in a later phase.

## Provenance

NVIDIA-authored. Proposed and reviewed in
[NemoClaw Community #122](https://github.com/NVIDIA/nemoclaw-community/issues/122).
