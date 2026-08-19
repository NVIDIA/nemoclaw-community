<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Demo fixtures

Eight messages and a small seed memory, enough to watch the ranking work
without connecting a mailbox or a Slack workspace.

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
| `msg-quiet-decay` | Seven days old with no follow-up anywhere in the batch. The reviewer should push it down rather than let it hold a position it earned a week ago. |
| `msg-automated-noise` | A build notification from a `noreply@` address. Skipped, and skipping is terminal, so it is never judged again. |
| `msg-cc-only` | The user is on Cc, not To. Being copied is not being asked; `addressing` is `broadcast`. |
| `D0DIRECT01` message | A direct message. `addressing` is `direct` with no mention needed. |
| `C0TEAM0001` mention | A channel message that names the user. `addressing` is `mentioned`. |
| `C0TEAM0001` notice | A channel announcement naming nobody. `addressing` is `broadcast`. |

## The seed memory

`fixtures/memory/` holds the pages the intent gate reads. Without them every
row fails the gate, the top tier is empty, and the demo shows nothing
interesting — which is itself the point being made: the ranking is only as
good as the memory behind it.

## Running it

The demo loader replays these through the same normalization and writer path
the live collectors use:

```bash
python3 profile/scripts/load_fixtures.py --fixtures fixtures
```

It is idempotent. Running it twice adds nothing, because intake is keyed on
`source_id`.
