---
title:
  page: "Verify Skill Functionality"
  nav: "Verify Skills"
description:
  main: "Walk through 10 conversational prompts (2 per skill) that prove each Hermes skill works end-to-end across Slack DM, Slack thread, and Outlook email channels."
  agent: "End-to-end functional verification recipe for the personal-community-sentiment-triage example. Contains 10 copy-pasteable prompts (2 per skill: outlook-email-search, slack-channel-finder, slack-channel-summarizer, source-etl-query, cross-source-gap-analysis) split between Slack DM, Slack thread, and Outlook email channels. Each prompt has a stated expected behavior and a specific verification cue. Use after running scripts/bring-up.sh and confirming the README's plumbing checks pass — this guide picks up where the README's plumbing verification stops."
keywords: ["verify nemoclaw skills", "hermes skill verification", "slack outlook smoke test", "personal community sentiment triage verification"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "outlook", "slack", "verification", "smoke-test"]
content:
  type: how_to
  difficulty: intermediate
  audience: ["developer", "engineer"]
status: published
---

<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

![NVIDIA](../assets/nvidia_header.png)

# Verify Skill Functionality

Ten copy-pasteable prompts — two per skill — that prove each skill works end-to-end across Slack and Outlook. The README's [§ Verification](../README.md#verification-what-success-looks-like) only checks plumbing (the bridge runs, the sidecar exists, scripts return `ok: true`). This guide picks up where that stops: it checks whether the **agent** can use its skills correctly.

Once you've run all 10, head to [collective-wisdom.md](collective-wisdom.md) for the cross-channel skill-learning demo — where one user teaches the agent a new skill, the skill survives a full sandbox rebuild, and a different user invokes it from a different channel and gets the same output format.

## Prerequisites

Run through these once before starting.

| Check | One-liner |
|---|---|
| Sandbox is `Ready` | `openshell sandbox list \| grep hermes-direct` |
| Postgrest is on the OpenShell network | `curl -sf http://localhost:3100/github_issues?limit=1` (returns JSON; `[]` is fine — first sync may be pending) |
| Slack works | DM `ping` to `@myuser_nemoclaw` produces a reply within ~10s. Red ❌ reaction = your Slack ID isn't in `SLACK_ALLOWED_IDS`. |
| Outlook bridge works | Email `ping` to `OUTLOOK_TARGET_MAILBOX` from an allowed sender produces a reply within ~30s. |
| **Optional** — unlocks Outlook Q2 | The owner of `OUTLOOK_REPLY_TO` has granted the bot delegate access in Outlook (**File → Account Settings → Delegate Access**). Without it, Graph returns `403: Cannot find row based on condition` for searches against `OUTLOOK_REPLY_TO`. |

A few constraints to keep in mind:

- **ETL freshness.** github-etl and forums-etl run hourly. If `source-etl-query` returns zero rows, wait 10 min and retry — the skill isn't broken.
- **Session boundaries.** Each Outlook email opens a fresh session. Slack thread replies (same `thread_ts`) share one session. Cross-session continuity comes only from the memory subsystem.

---

## The 10 prompts

For each skill there's a **smoke** test (deterministic, proves the wiring) and a **realistic** test (exercises the full code path, judged by reading the reply). Channels alternate so both bridges get exercised.

### Quick reference

| #  | Skill                       | Type      | Channel       |
|----|-----------------------------|-----------|---------------|
| Q1 | outlook-email-search        | smoke     | Slack DM      |
| Q2 | outlook-email-search        | realistic | Outlook email |
| Q3 | slack-channel-finder        | smoke     | Slack DM      |
| Q4 | slack-channel-finder        | realistic | Outlook email |
| Q5 | slack-channel-summarizer    | smoke     | Slack DM      |
| Q6 | slack-channel-summarizer    | realistic | Slack thread  |
| Q7 | source-etl-query            | smoke     | Slack DM      |
| Q8 | source-etl-query            | realistic | Outlook email |
| Q9 | cross-source-gap-analysis   | smoke     | Slack DM      |
| Q10| cross-source-gap-analysis   | realistic | Outlook email |

Every question below uses the same shape:

> **Send via:** … (channel + addressing details)
>
> *(blockquoted prompt — this is what you copy-paste)*
>
> **Expected:** what the agent should do under the hood.
> **Verify:** the specific signal in the reply that proves it worked.

---

### outlook-email-search

#### Q1 — smoke

**Send via:** Slack DM to `@myuser_nemoclaw`

> Search the bot's own mailbox (`OUTLOOK_TARGET_MAILBOX`) for any email from the last 30 days. Return just the count and the most recent subject line.

**Expected:** agent loads `outlook-email-search` and runs `search_emails.py --since 30d --top 5` against the bot's own mailbox.
**Verify:** reply contains a numeric count and a quoted subject line; no 403 errors. Targeting the bot's mailbox sidesteps the delegate-access requirement.

#### Q2 — realistic

**Send via:** email to `OUTLOOK_TARGET_MAILBOX`
**Subject:** `External chatter check`

> Pull external-sender emails from my inbox (`OUTLOOK_REPLY_TO`) over the last 14 days and group them by topic — 3-5 categories max. Use the skill's compact summary format.

**Expected:** agent uses `--external-only --since 14d`, possibly `get_thread.py` for one or two threads, replies with the documented `**Inbox — {date}, {N} messages**` block followed by `**Bottom line:**`.
**Verify:** reply contains the literal string `**Bottom line:**` (the skill's required suffix per its own format spec).

**If `OUTLOOK_REPLY_TO` isn't ready yet:** there are two distinct failure modes for searching that mailbox, and you should know which you're hitting before re-running Q2:

| Graph status | What it means | Fix |
|---|---|---|
| `403: Cannot find row based on condition` | Mailbox exists but the bot lacks delegate access | Grant delegate access in Outlook (File → Account Settings → Delegate Access) |
| `404: ResourceNotFound` (or "not found") | Mailbox isn't provisioned as an Entra user in this tenant | Set `OUTLOOK_REPLY_TO` to a real mailbox you own (e.g., your corporate address), then `bash scripts/tear-down.sh && bash scripts/bring-up.sh` to bake the new value in |

In either case, the agent may **loop trying to satisfy "from my inbox"** rather than abandoning quickly — it can spend 10+ minutes bouncing between REPLY_TO and TARGET_MAILBOX before max-turns terminates the session. If you see this, kill the bridge to abort the current request: `openshell sandbox exec --name hermes-direct -- pkill -f outlook-bridge.py`. Then substitute `OUTLOOK_TARGET_MAILBOX` (the bot's mailbox) into the Q2 prompt to exercise the same code path.

---

### slack-channel-finder

#### Q3 — smoke

**Send via:** Slack DM to `@myuser_nemoclaw`

> List 5 public channels in this workspace by name. Just names, no descriptions.

**Expected:** agent runs `list_accessible_channels.py --all-public`.
**Verify:** 5 distinct channel names, all confirmable via Slack's channel browser.

#### Q4 — realistic

**Send via:** email to `OUTLOOK_TARGET_MAILBOX`
**Subject:** `Where do we talk about deployments?`

> Find Slack channels where deployments, infra, or release work is discussed. Rank the top 3 by relevance and explain in one line each what the channel is for.

**Expected:** agent uses `find_channel.py --query "deployments infra release"`, then `describe_slack_channel.py --no-history` on the top hits.
**Verify:** reply names 3 specific channel IDs (`C…`) and includes match-reason language pulled from the skill's `match_reasons` field (e.g., `name:deploy`, `purpose:release`). Reasons should reference name/topic/purpose tokens, not invented context.

---

### slack-channel-summarizer

#### Q5 — smoke

**Send via:** Slack DM to `@myuser_nemoclaw`

> Pick any channel the bot is a member of and summarize the most recent 10 messages.

**Expected:** agent uses `users.conversations` to pick a member channel, then `conversations.history` with `limit=10`, then a short summary.
**Verify:** reply names the chosen channel by ID (`C…`) and gives a bulleted summary covering ≤10 messages. **If the bot isn't in any channels yet**, the skill correctly reports `not_in_channel` and asks to be invited — that's also a valid pass; invite `@myuser_nemoclaw` to a channel and retry.

#### Q6 — realistic

**Send via:** thread reply in any channel the bot is a member of, mentioning `@myuser_nemoclaw`

> Summarize the last 7 days of this channel — main topics, who's most active, and any unresolved questions.

**Expected:** agent uses the thread's channel ID directly, pulls history with `oldest=` set to 7 days ago, replies in-thread.
**Verify:** reply has sections for time range, main topics, active participants, and decisions/action items — the documented summary structure. Bonus credibility: a participant name you recognize.

---

### source-etl-query

Sanity-check the postgrest bridge first (host shell):

```console
$ curl -sf http://localhost:3100/github_issues?limit=1 | head -c 300
```

Empty array `[]` is fine — bridge is up but ETL hasn't finished first sync. A `404` or refusal means re-run `bash scripts/00-host-services.sh`.

#### Q7 — smoke

**Send via:** Slack DM to `@myuser_nemoclaw`

> Show me the 3 most recently mirrored GitHub issues from the source-etl postgrest bridge — title and number only.

**Expected:** agent runs `query_source_etl.py github-issues --limit 3`.
**Verify:** response contains 3 numbered items. The agent should *not* claim GitHub is unreachable — that path is correctly blocked by sandbox policy; the postgrest mirror is the supported route.

#### Q8 — realistic

**Send via:** email to `OUTLOOK_TARGET_MAILBOX`
**Subject:** `NemoClaw forum activity`

> What are the top recurring concerns in NVIDIA forum topics tagged for NemoClaw over the last month? Group them and cite topic IDs.

**Expected:** agent runs `query_source_etl.py forum-topics --limit 50` (possibly `--search nemoclaw`), groups topics into 3-5 themes, cites topic IDs/titles.
**Verify:** reply includes at least 3 specific forum topic IDs/URLs — proves the agent read rows rather than fabricated themes. If the mirror is empty (first sync incomplete), the agent should say so per the skill's "empty mirror" guidance, not invent content.

---

### cross-source-gap-analysis

#### Q9 — smoke

**Send via:** Slack DM to `@myuser_nemoclaw`

> Use cross-source-gap-analysis. Compare one Slack channel related to NemoClaw against the github-issues mirror. Just confirm both sources returned data and report the row count from each — no analysis yet.

**Expected:** agent loads `cross-source-gap-analysis`, then `slack-channel-finder` and `source-etl-query`, fetches a small slice from each.
**Verify:** reply mentions both source counts as concrete numbers. No actual gap analysis yet — wiring proof only.

#### Q10 — realistic

**Send via:** email to `OUTLOOK_TARGET_MAILBOX`
**Subject:** `Slack-vs-GitHub gaps for NemoClaw`

> Run a cross-source-gap-analysis: pick one NemoClaw-related Slack channel, sample the last 7 days, and compare against open GitHub issues in the mirror. Tell me which topics are discussed in Slack but have no corresponding GitHub issue, and which GitHub issues have no Slack discussion. Use the skill's documented "scope / agree / gaps / follow-ups" structure.

**Expected:** agent picks a channel via `slack-channel-finder`, summarizes via `slack-channel-summarizer`, queries `source-etl-query github-issues`, normalizes both, presents a 4-section reply.
**Verify:** reply contains all four documented section headings — `scope and time window`, `what all sources agree on`, `gaps or mismatches`, `concrete follow-ups` — and grounds each gap in a specific channel message or GitHub issue number, not generic abstractions.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Outlook search Q2 returns 403 | Bot lacks delegate access to `OUTLOOK_REPLY_TO`. Either grant it (Outlook → File → Account Settings → Delegate Access) or substitute `OUTLOOK_TARGET_MAILBOX` in the prompt. |
| Outlook search Q2 hangs without ever replying | `OUTLOOK_REPLY_TO` returns 404 from Graph — the address isn't a real Entra user in your tenant. Confirm via the sidecar log (`openshell sandbox exec --name hermes-direct -- tail -50 /tmp/ms-graph-sidecar.log \| grep 404`). Fix: set `OUTLOOK_REPLY_TO` to a real mailbox you own and rebuild. To unblock the in-flight request: `openshell sandbox exec --name hermes-direct -- pkill -f outlook-bridge.py`. |
| `source-etl-query` returns 0 rows for everything | Run `curl -sf http://localhost:3100/github_issues?limit=1`. Empty → ETL hasn't completed first sync (wait 10 min). Unreachable → re-run `bash scripts/00-host-services.sh`. |
| `grep: /sandbox/.hermes-data/...: No such file or directory` (running side-checks against the sandbox) | `openshell sandbox exec` doesn't run a shell, so `*.md` and other globs don't expand. Wrap in `bash -c '…'`, or pass explicit filenames. |
