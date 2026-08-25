<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Fixtures

Eight messages, a small seed memory, and one of the two recorded model turns.
Together they run the recipe from end to end without a mailbox, a Slack
workspace, or an inference endpoint. See the
[recipe README](../README.md) for what the recipe does and for the terms used
below.

## Provenance

These fixtures were written from scratch. The people, the company, the
projects, and every message body are invented. Nothing is derived from a real
mailbox, a real workspace, or an anonymized copy of either. The response shapes
match what
[Microsoft Graph's delta query](https://learn.microsoft.com/en-us/graph/api/message-delta)
and
[Slack's `conversations.history`](https://docs.slack.dev/reference/methods/conversations.history)
return for the fields this recipe selects, so the same normalization code will
run against the fixtures and against a live source.

The files themselves are local wrappers rather than captured responses. The
Graph file keeps the API's own `value` array and `@odata.deltaLink`; the Slack
file keys its histories by channel, because a real `conversations.history` call
returns one `{"ok": true, "messages": [...]}` response per channel and the
loader would otherwise need one file each. What the normalizer reads — the
message objects inside — matches what each API returns.

## What each record is a control for

| Record | What it controls for |
| --- | --- |
| `msg-priorities-match` | Matches an entry in `memory/attention/current_priorities.md`, so a judging turn admits it through the intent gate and it can reach the `high` tier. |
| `msg-urgent-not-chosen` | Loud external urgency that matches nothing the user chose: a mandatory deadline, with "URGENT" in the subject. Capped at `medium`. |
| `msg-quiet-decay` | Dated seven days before the rest of the batch, and nothing later in the corpus follows up on it. It is named in `memory/attention/current_priorities.md`, so it passes the gate too. The walkthrough pins it to the bottom tier by hand, to show a correction outranking the memory. |
| `msg-automated-noise` | A build notification from a `noreply@` address. Skipped, and skipping is terminal, so it is never judged again. |
| `msg-cc-only` | The user is on Cc rather than To. Being copied is not being asked, so `addressing` is `broadcast`. |
| `D0DIRECT01` message | A direct message. `addressing` is `direct`, with no mention needed. |
| `C0TEAM0001` mention | A channel message that names the user, about the migration document, so it passes the gate too. `addressing` is `mentioned`. |
| `C0TEAM0001` notice | A channel announcement that names nobody. `addressing` is `broadcast`. |

Two of the eight are skipped rather than tracked: `msg-automated-noise` and the
`C0TEAM0001` notice. That is why the walkthrough reports `"skipped": 2` and
carries six obligations rather than eight.

Three of the eight pass the intent gate: `msg-priorities-match`, the
`C0TEAM0001` mention, and `msg-quiet-decay`. That is why the walkthrough prints
`high=3`.

`msg-urgent-not-chosen` is the record to watch. It is a real, dated, mandatory
deadline, and the recorded turn ranks it fourth. It still cannot reach the
`high` tier, because the recorded verdict says the user never chose that work.
This is the behavior a ranking without a memory behind it cannot produce.

## The seed memory

`memory/` holds the pages a live judging turn reads before it decides, for each
message, whether the user chose that work. In this fixture path that decision
is already recorded in `envelopes/intake.json`, so removing `memory/` does not
change the tiers the walkthrough prints. The pages are here because the memory
is what a live run reads, and because the memory self-check in step 7 runs
against them.

What the ranking does with a gate verdict is shipped code, and the walkthrough
shows it directly: step 2 re-runs the ranking over the same rows with the
verdicts withheld, and the `high` tier empties.
Two tests assert the same property directly:
`test_no_row_passes_the_gate_high_is_empty_and_all_cascade`, in
`profile/scripts/tests/test_ranking.py`, and
`test_an_ungated_population_leaves_the_high_tier_empty`, in
`profile/scripts/tests/test_apply_decisions.py`.

## The recorded model turns

The walkthrough records two turns, so that it is deterministic and needs no
inference endpoint:

- `envelopes/intake.json`, the intake judgment. It stands in for what a model
  returns after reading the batch and the memory.
- A shorter review envelope for step 5, written inline in
  `profile/scripts/walkthrough.py` rather than stored here.

Those two are the only recorded parts. Everything downstream of them is the
shipped code, running for real: the tier caps, the ranking across the whole
open population, the transactional writer, the correction path, and the
re-ranking. The gate verdict on each row sits inside the intake envelope,
because deciding it needs a model reading the memory.

## Running it

Run from the recipe root, not from this directory:

```bash
export HERMES_HOME=$(mktemp -d)
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

`HERMES_HOME` must be set. `walkthrough.py` and `load_fixtures.py` both refuse
to guess a profile home.

The walkthrough prints seven steps: ingestion, judgment, two corrections, a
re-judgment that cannot undo them, the state of the preference threshold, and
the memory self-check. Step 7 breaks one page on purpose, so the check is seen
to fail as well as pass.

To load the messages without any of the judgment, use the loader on its own in
a profile home the walkthrough has not already filled:

```bash
export HERMES_HOME=$(mktemp -d)
python3 profile/scripts/load_fixtures.py --fixtures fixtures
```


Each `mktemp -d` above makes a profile home that is not removed for you. See
[Cleanup](../README.md#cleanup) in the recipe README.

Ingestion is idempotent: a second `load_fixtures.py` run against the same
profile home adds nothing, because intake is keyed on the source's own
identifier.

The walkthrough is not. It narrates a first run, and a second run against the
same profile home would inherit the first run's corrections, so the commentary
would no longer match the tables beneath it. It detects that and stops, telling
you to point `HERMES_HOME` at a fresh directory.
