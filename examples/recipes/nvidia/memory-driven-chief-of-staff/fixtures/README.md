<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Fixtures

Eight messages, a small seed memory, and one recorded model turn — enough to
run the example end to end without connecting a mailbox or a Slack workspace.

## Provenance

Written from scratch for this example. The people, the company, the projects
and every message body are invented. Nothing here is derived from a real
mailbox, a real workspace, or an anonymized copy of either. The response
shapes match what Microsoft Graph's delta query and Slack's
`conversations.history` actually return for the fields this recipe selects, so
the same normalization code runs against the fixtures and against live
sources.

## What each record is a control for

| Record | Demonstrates |
| --- | --- |
| `msg-priorities-match` | Matches an entry in `attention/current_priorities.md`, so it passes the intent gate and can reach the top tier. |
| `msg-urgent-not-chosen` | Loud external urgency — a mandatory deadline, "URGENT" in the subject — matching nothing the user chose. **Capped at the middle tier.** This is the one worth watching: it is the behaviour a ranking without a memory cannot produce. |
| `msg-quiet-decay` | Seven days old with no follow-up anywhere in the batch. The walkthrough pins it down by hand, to show a correction outranking the memory. |
| `msg-automated-noise` | A build notification from a `noreply@` address. Skipped, and skipping is terminal, so it is never judged again. |
| `msg-cc-only` | The user is on Cc, not To. Being copied is not being asked; `addressing` is `broadcast`. |
| `D0DIRECT01` message | A direct message. `addressing` is `direct` with no mention needed. |
| `C0TEAM0001` mention | A channel message naming the user, about the migration doc — so it passes the gate too. `addressing` is `mentioned`. |
| `C0TEAM0001` notice | A channel announcement naming nobody. `addressing` is `broadcast`. |

## The seed memory

`fixtures/memory/` holds the pages the intent gate reads. Without them every
row fails the gate and the top tier is empty — which is itself the point being
made: the ranking is only as good as the memory behind it.

## The recorded model turn

`fixtures/envelopes/intake.json` is one decision envelope, written by hand,
standing in for what the model returns after reading the batch and the memory.
It exists so the walkthrough is deterministic and needs no inference endpoint.

It is the only part that is canned. Everything downstream of it — the intent
gate, the tier caps, the population ranking, the transactional writer, the
correction path and the re-ranking — is the shipped code, running for real.

## Running it

```bash
export HERMES_HOME=$(mktemp -d)
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

Run from the recipe root. Neither script will guess a profile home, so
`HERMES_HOME` has to be set.

The walkthrough prints seven steps: ingestion, judgment, two corrections, a
re-judgment that cannot undo them, the state of the preference threshold, and
the memory self-check — including one deliberate break, so you can see the
check fail as well as pass.

To load the messages without any of the judgment, use the loader on its own:

```bash
python3 profile/scripts/load_fixtures.py --fixtures fixtures
```

Both are idempotent. Running either twice adds nothing, because intake is
keyed on `source_id`.
