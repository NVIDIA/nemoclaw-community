<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Memory-Driven Chief of Staff Fixtures

This directory provides eight synthetic messages, a small seed memory, and one
file-backed recorded model turn. Together with a second envelope embedded in
the walkthrough, they run the parent recipe end to end without a mailbox,
Slack workspace, inference endpoint, credential, or network connection.

Start with the [parent recipe README](../README.md) if you want to understand
the complete system or install it in NemoClaw.

## Table of Contents

- [What It Covers](#what-it-covers)
- [Directory Structure](#directory-structure)
- [Quick Start](#quick-start)
- [Fixture Catalog](#fixture-catalog)
- [Configuration](#configuration)
- [Format Reference](#format-reference)
- [Recorded Model Turns](#recorded-model-turns)
- [Provenance and Safety](#provenance-and-safety)
- [Troubleshooting and FAQ](#troubleshooting-and-faq)
- [Fixture Metadata](#fixture-metadata)

## What It Covers

- Fixed source rows and decisions make every run deterministic.
- Messages cover ranking, addressing, skips, corrections, and the intent gate.
- Fixtures use the recipe's normalizers and SQLite writer.
- Two documented envelopes replace the only live model turns.

## Directory Structure

Paths in metadata and commands are relative to the parent recipe root.

<!-- markdownlint-disable MD013 -->
```text
fixtures/
├── README.md                                  # This fixture contract and catalog
├── graph_messages.json                        # 5 synthetic Graph delta-shaped rows
├── slack_messages.json                        # 3 synthetic Slack history-shaped rows
├── envelopes/
│   └── intake.json                            # Recorded intake decision envelope
└── memory/
    ├── index.md                               # Seed memory index
    ├── attention/
    │   └── current_priorities.md              # Work that can pass the intent gate
    ├── people/
    │   ├── dana_okoro.md                      # Synthetic collaborator page
    │   └── sam_ruiz.md                        # Synthetic collaborator page
    └── projects/
        └── billing_migration/
            └── billing_migration.md           # Synthetic active-project page
```
<!-- markdownlint-enable MD013 -->

The second recorded turn is the short review envelope embedded in
`profile/scripts/walkthrough.py`, next to the step whose correction-survival
behavior it exercises.

## Quick Start

Run from the **parent recipe root**, not from `fixtures/`.

```bash
export FIXTURE_TMP_HOME="$(mktemp -d)"
export HERMES_HOME="$FIXTURE_TMP_HOME"
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

Expected results:

```text
source messages: 8
skipped: 2
open obligations: 6
high tier: 3
exit status: 0
```

The output also shows that a user pin and an ignore survive re-judgment, that a
preference remains below its learning threshold, and that the memory checker
both passes and catches an introduced defect.

### Load without judgment

Use a fresh profile home if the walkthrough has already populated the previous
one.

```bash
export FIXTURE_LOAD_HOME="$(mktemp -d)"
export HERMES_HOME="$FIXTURE_LOAD_HOME"
python3 profile/scripts/load_fixtures.py --fixtures fixtures
python3 profile/scripts/load_fixtures.py --fixtures fixtures
```

The two runs report `"added": 8` and `"added": 0`. Ingestion is keyed by each
source's identifier, so replaying the same corpus is idempotent.

## Fixture Catalog

<!-- markdownlint-disable MD013 -->
| Record | Source shape | Expected control |
| --- | --- | --- |
| `msg-priorities-match` | Graph email | Matches `current_priorities.md`; passes the intent gate and reaches `high` |
| `msg-urgent-not-chosen` | Graph email | Explicit dated deadline labeled `URGENT`, but no chosen-work match; capped at `medium` |
| `msg-quiet-decay` | Graph email | Seven days older and priority-matched; starts in `high`, then a user pin moves it to `low` |
| `msg-automated-noise` | Graph email | No-action `noreply@` build notice; terminal `SKIP` |
| `msg-cc-only` | Graph email | User appears only on Cc; normalized as `broadcast`, later ignored by the user |
| `D0DIRECT01:1787055600.000100` | Slack DM | Direct message; normalized as `direct` without a mention |
| `C0TEAM0001:1787056200.000200` | Slack channel | Names the synthetic user and matches active work; `mentioned`, intent-gated, and `high` |
| `C0TEAM0001:1787056800.000300` | Slack channel | General no-action notice; `broadcast` and terminal `SKIP` |
<!-- markdownlint-enable MD013 -->

Two messages are skipped, leaving six obligations. Three pass the intent gate,
so `high` contains three rows rather than being padded to its cap of ten.

The key negative control is `msg-urgent-not-chosen`: it ranks fourth and has a
mandatory deadline, but cannot enter `high` because the recorded verdict says
the user did not choose that work.

## Configuration

### Dependencies

| Item | Path / value |
| --- | --- |
| Python dependency manifest | None; standard library only |
| Parent entry point | `profile/scripts/walkthrough.py` |
| Loader | `profile/scripts/load_fixtures.py` |
| Normalizer | `profile/scripts/normalize.py` |
| Transaction boundary | `profile/scripts/_db.py` |
| Required environment variable | `HERMES_HOME` |
| Network or credentials | None |

`HERMES_HOME` must name an existing fresh directory. The walkthrough and loader
refuse to guess a state location or create the profile home itself.

```yaml
environment:
  HERMES_HOME:
    required: true
    type: existing_directory
    recommended_for_fixtures: fresh_temporary_directory
```

## Format Reference

### Microsoft Graph-shaped wrapper

`graph_messages.json` retains the API-style `value` array and delta cursor. It
contains five hand-written message objects. The parent recipe also ships a live
Microsoft Outlook collector through Microsoft Graph; this fixture remains a
local wrapper and does not configure or contact it.

```json
{
  "source": "Synthetic Microsoft Graph delta response",
  "record_count": 5,
  "value": [
    {
      "id": "msg-priorities-match",
      "receivedDateTime": "2026-08-18T08:10:00Z",
      "subject": "Billing migration — need the cutover window confirmed",
      "from": {
        "emailAddress": {
          "name": "Dana Okoro",
          "address": "dana.okoro@example.com"
        }
      },
      "toRecipients": [
        {
          "emailAddress": {
            "address": "avery.chen@example.com"
          }
        }
      ],
      "ccRecipients": [],
      "body": {
        "contentType": "text",
        "content": "<synthetic body>"
      }
    }
  ],
  "@odata.deltaLink": "<synthetic delta URL>"
}
```

### Slack-shaped wrapper

`slack_messages.json` groups one API-style history response per channel because
Slack timestamps are unique only within a channel. The normalizer constructs a
stable source identifier from the channel ID and timestamp.

```json
{
  "source": "Synthetic Slack conversations.history responses",
  "record_count": 3,
  "channels": [
    {"id": "D0DIRECT01", "type": "im"},
    {"id": "C0TEAM0001", "type": "channel"}
  ],
  "history": {
    "D0DIRECT01": {
      "ok": true,
      "messages": [
        {
          "ts": "1787055600.000100",
          "user": "U0DANA0001",
          "text": "<synthetic body>"
        }
      ]
    }
  }
}
```

### Seed people pages

Each synthetic people page lists the provider identities that the user has
confirmed for that person. The fixture starts with one email identity per page;
live runs can add Slack or future-provider identities through
`link_identity.py`.

```yaml
name: Dana Okoro
identities:
  - email:dana.okoro@example.com
```

The recipe never joins pages from display names alone. Identity-linking tests
cover confirmations, rejections, composed relationships, and conflicts.

### Recorded intake envelope

`envelopes/intake.json` follows the writer contract documented in the parent
README. `intent_gated` is part of the recorded turn because deciding it requires
a model to read memory; tier assignment after that verdict is live recipe code.

```json
{
  "version": 1,
  "pass": "intake",
  "decisions": [
    {
      "source_id": "msg-priorities-match",
      "decision": "CREATE",
      "rank": 1,
      "intent_gated": true,
      "title": "Give Dana the billing-migration cutover window",
      "kind": "response",
      "est_effort": "minutes"
    },
    {
      "source_id": "msg-automated-noise",
      "decision": "SKIP"
    }
  ],
  "cursor": {
    "source": "email",
    "scope": "inbox",
    "value": "fixture-delta-1"
  }
}
```

## Recorded Model Turns

The deterministic walkthrough replaces exactly two inference calls:

1. `fixtures/envelopes/intake.json` supplies the intake judgment for all eight
   source rows.
2. `profile/scripts/walkthrough.py` contains the shorter step-5 review envelope
   that attempts, and fails, to override the user's earlier correction.

Everything downstream uses the recipe's normal execution paths: normalization,
SQLite writes, population ranking, cap and cascade behavior, user corrections,
audit attribution, preference counting, and memory invariant checking.

Removing `fixtures/memory/` does not alter recorded gate verdicts and therefore
does not alter the printed tiers. It does cause the final memory check to fail.
The walkthrough also reruns ranking with all gate verdicts withheld and prints
the resulting empty `high` tier.

## Provenance and Safety

These fixtures were written from scratch, not captured or anonymized from a
real account. All identities, projects, timestamps, URLs, and messages are
invented.

The shapes intentionally resemble the fields consumed from
[Microsoft Graph message delta](https://learn.microsoft.com/en-us/graph/api/message-delta)
and [Slack `conversations.history`](https://docs.slack.dev/reference/methods/conversations.history).
They are local wrappers, not preserved API responses. The Graph wrapper keeps a
`value` array and delta link; the Slack wrapper keeps one history result per
channel.

## Troubleshooting and FAQ

### The script says `HERMES_HOME` is required

Run from the parent recipe root and point the variable at an existing directory.

```bash
cd ..
export HERMES_HOME="$(mktemp -d)"
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

### The walkthrough says the profile home is not fresh

The walkthrough requires fresh state because old corrections would change its
results. Create a new directory and rerun.

```bash
export HERMES_HOME="$(mktemp -d)"
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

### The loader reports `"added": 0`

The same fixtures have already been loaded into that profile home. This is the
expected idempotency behavior. Use a new home if you need a clean corpus.

### Does deleting the seed memory test the intent gate?

No. The envelope already records each gate verdict. Deleting memory tests the
memory checker, while the walkthrough's gate-withheld comparison and the
ranking tests exercise the tier behavior directly.

### Can these files configure a live mailbox?

No. They are a deterministic corpus, not credentials or connector state. Live
Slack and Outlook setup is documented in the
[parent README](../README.md#connect-messaging-providers).

## Fixture Metadata

```yaml
name: memory-driven-chief-of-staff-fixtures
version: "0.1.0"
kind: synthetic-fixture-corpus
parent_recipe: memory-driven-chief-of-staff
path_base: parent_recipe_root
tech_stack:
  - JSON
  - Markdown
  - "Python 3.10+"
entry_point: profile/scripts/walkthrough.py
fixture_root: fixtures
message_count: 8
recorded_model_turns: 2
contains_real_data: false
requires_network: false
license: Apache-2.0
```
