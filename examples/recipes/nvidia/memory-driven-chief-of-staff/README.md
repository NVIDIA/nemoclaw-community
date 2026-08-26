<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Memory-Driven Chief of Staff

Memory-Driven Chief of Staff is a recipe that keeps a local, revisable record
for each inbound email and Slack message. It re-judges those records on a
schedule and re-ranks them under fixed caps, on jobs it registers with the
runtime's scheduler. The user's own ignores and priority overrides change the
ranking. The recipe never writes back to the
source system.

Three phases are here: the store with its tests and an offline walkthrough,
the installer and scheduled jobs that run it without a person present, and a
Slack collector that reads the messages the user receives. The first two need
no account, no workspace and no network, and the walkthrough and the tests
still need none. The collector is optional; until it is set up it reports
itself unconfigured and the schedule runs over whatever the store holds. Only
the scheduled path needs an inference endpoint, and only when a job finds
work. A fixture corpus exercises the same code a
live source would. Two recorded model turns stand in for the two steps that
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
| Pre-step | The script a scheduled job runs before its agent turn. Hermes calls it the `--script`; it decides what the turn sees, and whether there is one. |
| Wake gate | The `{"wakeAgent": false}` line a pre-step prints when it found no work. Hermes reads only the last non-empty line, and skips the agent turn when that line is the gate. |
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
| `profile/scripts/migrate.py` | Schema versioning, forward-only. At v2: adds `body_cleared_at` to a v1 store in place, without touching what it holds |
| `profile/scripts/normalize.py` | Source payloads to store rows, kept separate from the network calls |
| `profile/scripts/_db.py` | Connection and transaction boundary |
| `profile/scripts/correct.py` | The user's writer: pins, ignores, and the only source of `actor='user'` events |
| `profile/scripts/load_fixtures.py` | Replays the fixtures through the real ingest path |
| `profile/scripts/walkthrough.py` | The fixture walkthrough, end to end, with no credentials and no model |
| `profile/scripts/select_intake.py` | The intake job's pre-step: what to judge, and whether to wake the model at all |
| `profile/scripts/select_review.py` | The review job's pre-step: the stalest open obligations, oldest review first |
| `profile/scripts/retention.py` | The retention job: clears message bodies past the window, keeps the record |
| `profile/scripts/exclusions.py` | Senders, domains and channels that are never written, applied in `insert_items` |
| `profile/scripts/export_store.py` | Writes the whole store and memory out as Markdown beside JSON |
| `profile/scripts/reset.py` | Removes the store, the memory and the learned policy together |
| `scripts/install.sh` | Installs the profile, inherits the runtime's model config, registers the jobs |
| `scripts/register-jobs.sh` | Registers the six scheduled jobs through the cron CLI. Re-runnable |
| `profile/skills/` | Five skills: judging, review, repair, consolidation, preference update. Retention needs none — it clears bodies and never wakes the agent |
| `fixtures/` | Eight synthetic messages, a seed memory, and one recorded model turn |

Slack is connected through `scripts/setup-slack.sh`; a Microsoft Graph
connector is still to come. Until a connector is set up, the scheduled jobs
judge and re-judge whatever the store already holds.

## Requirements

- Python 3.10 or newer. Nothing else is needed for the fixture path.
- The fixture path — everything under [Try it](#try-it) and
  [Verify](#verify) — runs on Linux, macOS, or Windows under Windows Subsystem
  for Linux. Every command is written for a POSIX shell.
- **The scheduled path is Linux only**, including WSL. All five shipped skills
  declare `platforms: [linux]`, and Hermes refuses to load a skill outside its
  declared platforms. On macOS the jobs would still fire and the model would
  still be called — with no skill attached and a "skill not found" notice in
  its prompt. Registering them there buys a scheduled expense and no
  assistant.
- No credentials for the fixture path. The scheduled path is different: a
  woken job runs an agent turn, so the profile it fires under needs a model it
  can reach and a credential of its own. The installer carries over the model
  settings and never a key, because a key is not a thing to copy — you set one
  on the new profile with `hermes -p <profile> config set model.api_key`. It is
  not inherited: a profile without one sends the literal placeholder
  `no-key-required`, so every scheduled job would fail to authenticate. The
  installer stops before registering any job when either the model or the
  credential is missing.

Nothing in the fixture path needs Hermes. Installing the profile and running
it on a schedule does: `profile/distribution.yaml` declares
`hermes_requires: ">=0.19.0"`. On 0.19.x the manifest's `distribution_owned`
list is validated but not yet honored by the copy — the path-aware allowlist
first shipped in 0.20.0 — which changes nothing for this recipe, because what
it ships and what it declares are the same set, and a test keeps them so. The
same 0.19.0 figure under [Where state lives](#where-state-lives) records the
version the persistence claim was measured against.

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

Expected result: every file ends with `OK`, the eleven files report 403 tests in
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
| Selector output, the wake gate, and the scheduler contract | `tests/test_selectors.py` |
| Retention, exclusion, export and reset | `tests/test_lifecycle.py` |
| The Slack collector: watermarks, partial failure, scope probing, thread discovery and rotation, the credential never reaching a stream, and the lifecycle controls applying to what it writes | `tests/test_ingest_slack.py` |

Four points are worth calling out.

- `TestNoSourceMutation` in `tests/test_durability.py` scans every module for
  the common shapes of an HTTP write — `requests.post`, a `.patch(` call, and
  their siblings — and a companion test proves the scan fires on real
  examples, including `urlopen(url, data=…)` and a `subprocess` call to
  `curl`. Read it as a tripwire rather than a proof: it matches call shapes, so
  a write spelled in some further way could still pass it. What actually holds
  the property is enforced twice on the connector path: the provider profile
  declares `slack.com` at `access: read-only` with `enforcement: enforce`, so
  a write is refused at the egress boundary before any test runs, and the
  collector reaches no other host.
- `test_nothing_this_example_ships_lands_on_a_user_owned_path`, also in
  `tests/test_durability.py`, asserts that nothing this recipe ships occupies a
  user-owned name, and that the user-owned and distribution-owned sets stay
  disjoint. Both directions fail, and neither is loud. Hermes never installs a
  shipped path whose top-level name is user-owned, so a shipped `workspace`
  would never land at all; and a store placed under a distribution-owned path
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

## Running it on a schedule

Everything above runs by hand. To have it run on its own, install the profile
into a Hermes runtime and register the jobs:

```bash
scripts/install.sh
```

From the recipe root. It does three things: `hermes profile install` for the
distribution, a carry-over of the model settings so the new profile inherits a
model, and `scripts/register-jobs.sh` for the schedule. `PROFILE_NAME`
overrides the profile it installs into.

The carry-over is three named settings — `model.default`, `model.provider` and
`model.base_url` — transferred through `hermes config set`. No file is copied
and no key is: the `model:` block is documented to hold an inline `api_key`,
and a copy would write that key into a second file. Set the key on the new
profile instead. Each transfer fails closed and is read back off the target
profile afterwards, so a setting that could not be written — or that reports
success without sticking — ends the run rather than leaving a profile that
took some of its configuration. The installer then checks both — that a model
resolves and that a credential is present — and exits before registering any
job if either is missing, rather than scheduling six jobs that would each
fail. If your endpoint genuinely needs no key, pass `ALLOW_NO_API_KEY=1` to
say so.

Re-running it is safe: the registration looks each job up by name and edits it
rather than adding another copy.

Six jobs are registered:

| Job | Schedule | Pre-step | Skill |
| --- | --- | --- | --- |
| intake | every 30 minutes | `select_intake.py` | `inbound-judging` |
| review | every 6 hours | `select_review.py` | `obligation-review` |
| retention | daily 02:00 | `retention.py` | — |
| memory repair | daily 03:00 | — | `memory-repair` |
| memory consolidation | daily 04:00 | — | `memory-consolidation` |
| preference update | daily 04:30 | — | `preference-update` |

**An idle tick costs nothing.** Each of the first two jobs runs its pre-step
script first, then one agent turn over that script's output. When the script
finds no work it prints `{"wakeAgent": false}` as its last line, and Hermes
skips the agent entirely — no model call, no delivery. That last-line detail
is the whole mechanism: Hermes reads only the final non-empty line of the
script's output, so a gate printed anywhere else is ignored and the model
wakes. A test asserts the gate exactly the way the scheduler parses it, rather
than looking for the string somewhere in the output.

The intake pre-step also runs whichever collectors are present. The Slack
one ships with the recipe and reports `{"unconfigured": true}` until
`scripts/setup-slack.sh` has run, exiting zero so an idle tick still costs
nothing. A Graph collector is not here yet, so it is reported as
`"absent": true`. Either way the tick carries on with whatever the store
already holds.

**Registering is not starting.** Under the builtin scheduler the jobs fire
only while a gateway is serving the profile, and starting one takes two steps
on Linux:

```bash
hermes -p memory-driven-chief-of-staff gateway install  # once
hermes -p memory-driven-chief-of-staff gateway start
hermes -p memory-driven-chief-of-staff cron status
```

`gateway start` fails with "Gateway service is not installed" until `gateway
install` has run. Where no service manager is available — WSL without
systemd — run it in the foreground instead: `hermes -p
memory-driven-chief-of-staff gateway run`.

`cron status` says plainly whether the scheduler is running, and lists the
active jobs and the next run. A registered job on a profile with no running
gateway does not tick and reports nothing. Two paths do fire without one:
`hermes cron tick` runs anything due once and exits, and an external cron
provider takes over from the in-process ticker.

**The job store is not part of the distribution.** `distribution.yaml` does not
declare `cron`. An update replaces what it does declare — `SOUL.md`,
`schema.md`, `skills`, `scripts` and the manifest — and leaves the jobs and
their run history alone. This is worth being deliberate about: `profile
update` lists `cron/` among the directories it overwrites, and it leaves ours
alone only because the manifest never claims it. Measured, not assumed: six
jobs registered, `hermes profile update` run on Hermes 0.19.0, six jobs still
there with the same ids. A test asserts the manifest never claims `cron` or
`workspace`.

To undo, remove the jobs individually. Deleting the profile removes its
`workspace` too, which is where the store and the memory live; removing the
jobs does not. `profile delete` prompts unless given `-y`:

```bash
hermes -p memory-driven-chief-of-staff cron remove <job-id>
hermes profile delete memory-driven-chief-of-staff
```

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

The fixture path reaches no network and reads no real account. The Slack
collector does both, once you have configured it, and everything below is
written for that case rather than for the fixtures.

One reduction already ships, because it is part of the schema under review:
recipient lists are never stored. Ingest reduces them to a single `addressing`
value — `direct`, `mentioned`, or `broadcast` — so the store never holds a
copy of who else was on a thread. `normalize.py` does this today, and
`tests/test_normalize.py` asserts it.

Four controls over what is kept ship alongside it, and they were in place
before the collector that fills the store was. They apply to real Slack
messages exactly as they apply to the fixtures, because the collector writes
through the same function every other writer does. The commands, the rules
file and the exact boundaries are in
[docs/data-lifecycle.md](docs/data-lifecycle.md); what follows is why they are
drawn where they are.

**Message bodies are cleared on a schedule.** `retention.py` runs daily and
clears the text of anything past the window — thirty days by default,
`RETENTION_DAYS` to change it. What stays is the record: sender, subject,
timestamp, addressing, the obligation and its title, and every event with its
actor. A month later you can still see that Dana asked about the cutover on the
third, that it ranked high, and that you ignored it on the fifth. You cannot
re-read Dana's words, which is the point. `body_cleared_at` marks a body that
was cleared, so it is not confused with one that never existed.

**Senders, domains and channels can be excluded at ingest.** Rules live in
`workspace/exclusions.json` and are applied in `insert_items`, which is the one
place every writer passes through — the fixture loader, the Slack collector,
and anything added later — so an excluded message is never written by any of
them. Filtering at display would leave the text on disk, which is no use to
somebody excluding their doctor. A test drives the collector against a rule
and asserts the row never appears, rather than reading the call chain and
concluding it should not.

**Everything can be exported and everything can be removed.**
`export_store.py` writes the store and the memory as Markdown beside JSON —
the first to read, the second to process — and omits nothing.
`reset.py --yes` removes the store, the memory and the learned preference
policy together, and reports each; a partial reset would answer the question
wrongly. It also prints how to revoke the credential, which lives with the
gateway rather than here, because somebody withdrawing consent wants both.

Three things about the connectors themselves:

- Attachments are not fetched. The collector stores a file-sharing message's
  text and never requests the file behind it.
- For Microsoft Graph, an item deleted at the source will be tombstoned locally
  and its body cleared at once, because the delta query reports deletions
  explicitly.
- For Slack, that guarantee is not available. A deleted message stops appearing
  in `conversations.history`, and its absence from a bounded, paginated read
  cannot be told apart from it lying outside the window. Reliable notice
  requires the Slack Events API, which this design does not use. Slack's legacy
  Real Time Messaging (RTM) API carries the event too, but Slack states that
  granular-permission apps cannot use it and that classic apps can no longer be
  created, so it is not an option this collector could take. Slack content
  therefore ages out on the scheduled body-clearing pass rather than at the
  moment of deletion — the weaker guarantee, kept, rather than the stronger one
  implied.

## Fixtures

The fixtures were written from scratch. The people, the company, the projects,
and every message body are invented. Nothing is derived from a real mailbox or
from an anonymized copy of one. See [`fixtures/README.md`](fixtures/README.md)
for what each record is a control for.

### Before a connector: encrypted storage

The fixture path stores invented messages. A connector changes that — the store
then holds real subjects, senders and bodies — so the profile home must sit on
an encrypted volume before one is attached. Owner-only permissions are not
encryption: they stop another account reading the file on a running system and
do nothing for a disk that is lost, imaged, or backed up.

`scripts/setup-slack.sh` checks what it can and refuses to attach a provider
until the rest is confirmed. What it inspects is the **host** filesystem under
the sandbox's storage, because `HERMES_HOME` inside a sandbox is an overlay
with no block device behind it — encryption is not observable from in there.
[`docs/encrypted-storage.md`](docs/encrypted-storage.md) has the verification
commands per platform, and what to do when the answer is no.

### Connecting Slack

The scheduled intake reads whichever collectors are present in
`profile/scripts/`. Slack is one of them, and it is read-only: direct
messages, group DMs, and the public channels you name. It never posts.

```bash
bash scripts/setup-slack.sh
```

Run it on the host, not in the sandbox — it needs `openshell`, which the
sandbox does not have. It reuses a Slack credential already attached when it
finds one, and otherwise walks you through authorizing the app. Full
walkthrough, including what to do when a workspace admin grants less than the
app asked for: [`docs/set-up-slack.md`](docs/set-up-slack.md).

Three things are deliberate. The recipe needs a **user** token, not a bot
token — a bot cannot read your direct messages, and using one produces an
assistant that quietly never sees them, so the collector checks the prefix and
names the mistake. That token **rotates**: the gateway holds it and refreshes
it every twelve hours, and a non-rotating one is refused, because a user token
that never expires is a permanent key to your entire Slack. And public
channels are read only when you **name** them in
`workspace/slack_channels.json` — Slack allows one history request per minute
for affected apps, so a workspace sweep cannot finish inside a scheduled tick,
and reading every channel you happen to be in collects more than the job
needs.

Until this is set up the collector still runs — it ships with the recipe — but
reports `{"unconfigured": true}` and exits zero, so the schedule runs over
whatever is already in the store and an idle tick still costs nothing. That is
a supported state, not a broken one.

### When a collector fails

A collector that exits non-zero, or prints something the selector cannot read,
is recorded in the batch as a failure with its exit code and a stable error
class, and the tick wakes the agent even when nothing is pending. An idle tick
is free; a broken one must not be quiet.

What nothing carries is the collector's own output. A collector is a
subprocess talking to a mail or chat API, so its stderr can hold a bearer
token, a signed URL, or someone's message body, and both of the places that
wanted it are wrong: the batch is the agent's prompt, and the selector's own
stderr is captured by the scheduler into the job log, where something
transient becomes a file that outlives the token in it.

So both get the same sanitized triple — which collector, what exit code, which
error class. After the connector phase supplies a collector, run that collector
directly to read what it actually said. For example, once `ingest_graph.py` is
installed:

```bash
HERMES_HOME="/path/to/profile" python3 profile/scripts/ingest_graph.py
```

That prints to your terminal rather than to a file. The text is dropped rather
than redacted on purpose: a pattern-matching redactor cannot promise it caught
everything, and a stored log is the wrong place to discover that it did not.

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

- Under the builtin scheduler the jobs fire only while a gateway is serving
  this profile, and registering them starts nothing. `hermes cron tick` runs
  what is due once without one, and an external cron provider replaces the
  in-process ticker entirely.
- The scheduled path is Linux only, including WSL, because every shipped skill
  declares `platforms: [linux]`. See [Requirements](#requirements).
- The installer transfers three named model settings and no file, so nothing
  it writes can carry a secret. It checks that a model resolves and that a
  credential is present, and stops before registering anything if either is
  missing. What it cannot do is prove the credential is *valid*: that is one
  request to your provider away, and the installer does not make it. A wrong
  key still installs cleanly and fails at the first scheduled run.
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

Every script except the Slack collector reaches no network. They read the
recipe's files from the checkout and write application state only inside the
profile home, and they also leave a Python bytecode cache beside the scripts —
see [Cleanup](#cleanup). The five skill files a runtime loads add nothing to
that.

The collector reaches exactly one host, `slack.com`, and only for reads. That
is declared in `providers/slack-user.yaml` as `access: read-only` with
`enforcement: enforce`, so the egress proxy refuses anything else — the
property is enforced by policy rather than promised by prose. The credential
never enters the sandbox: the gateway holds it and substitutes it at the
boundary, so the collector handles a placeholder it cannot spend.

The scheduled path does reach one. A job that wakes runs an agent turn, and the
runtime calls whichever inference provider it is configured for, over its own
egress path — the recipe holds no credential and opens no connection itself.
A job that does not wake makes no call at all.

Egress to a message source is here, and it is narrow: the Slack collector
reaches `slack.com` and nothing else, declared in the provider profile at
`access: read-only` with `enforcement: enforce`, so a write is refused at the
boundary rather than caught by a test. The credential it uses is held by the
gateway and substituted there — see
[Connecting Slack](#connecting-slack).

## Startup

The scripts run on demand and need nothing started.

The scheduled jobs need a gateway. Registration and firing are separate: a
registered job on a profile with no running gateway does not run and reports
nothing.

### After a reboot

Three separate questions, with three different answers.

**Do the jobs survive?** Yes. They live in `$HERMES_HOME/cron/jobs.json`, which
is ordinary disk state — not part of the distribution, so a profile update
leaves it alone, and not tied to any process, so shutting everything down and
starting again finds the same six jobs with the same ids.

**Do they start firing again on their own?** Only if the gateway was installed
as a service. `hermes -p <profile> gateway install` registers one — a launchd
agent on macOS, a systemd unit on Linux — and both are configured to come back
after a reboot. `hermes -p <profile> gateway run` is a foreground process and
is not: after a restart you run it again yourself. `cron status` tells you
which situation you are in.

**What about the runs that were missed while it was down?** One of them
happens, not all of them. Hermes collapses a backlog rather than replaying it:
when a recurring job's scheduled time is more than one period in the past, it
fast-forwards to the next future occurrence and fires once now. A machine that
was off for two days does not wake to ninety-six intake runs; it wakes to one,
which judges whatever accumulated, and then resumes its half-hourly rhythm.
That suits this recipe, whose jobs act on the current state of the store rather
than on a history of events.

## Provenance

NVIDIA-authored. Proposed and reviewed in
[NemoClaw Community #122](https://github.com/NVIDIA/nemoclaw-community/issues/122).
