---
title:
  page: "Verify Skill Functionality"
  nav: "Verify Skills"
description:
  main: "Walk through 21 conversational prompts plus live GitHub and optional GitLab checks that prove the core Hermes workflow skills, all eight NVTeam role lenses, Rich Blocks, and interactive clarification end-to-end across Slack DM, Slack thread, and Outlook email channels."
  agent: "End-to-end functional verification recipe for the developer-community-chief-of-staff example. Contains 21 copy-pasteable prompts covering outlook-email-search, slack-channel-finder, slack-channel-summarizer, source-etl-query, cross-source-gap-analysis, and all eight role-first nemoclaw-nvteam lenses, plus live github-readonly-live and optional gitlab-readonly-live checks. Each prompt has a stated expected behavior and a specific verification cue. Use after running scripts/bring-up.sh and confirming the README's plumbing checks pass."
keywords: ["verify nemoclaw skills", "hermes skill verification", "slack outlook smoke test", "developer community chief of staff verification"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "outlook", "slack", "github", "gitlab", "verification", "smoke-test"]
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

Twenty-one copy-pasteable prompts plus live GitHub and optional GitLab checks prove each skill works end-to-end across Slack and Outlook. The README's [§ Verification](../README.md#verification-what-success-looks-like) checks plumbing. This guide checks whether the **agent** can use its skills correctly.

Once you've run all 21, head to [collective-wisdom.md](collective-wisdom.md) for the cross-channel skill-learning demo, where one user teaches the agent a new skill and another user invokes it after a rebuild.

## Prerequisites

Run through these once before starting.

| Check | One-liner |
|---|---|
| Sandbox is `Ready` | `openshell sandbox list \| grep hermes-direct` |
| Postgrest bridge is reachable | `curl -sf http://localhost:3100/github_discussions?limit=1` (returns JSON; `[]` is fine — first sync may be pending) |
| Slack works | DM `ping` to `@myuser_nemoclaw` produces a reply within ~10s. Red ❌ reaction = your Slack ID isn't in `SLACK_ALLOWED_IDS`. |
| Outlook bridge works | Email `ping` to `OUTLOOK_TARGET_MAILBOX` from an allowed sender produces a reply within ~30s. |
| **Optional** — unlocks Outlook Q2 | The owner of `OUTLOOK_REPLY_TO` has granted the bot delegate access in Outlook (**File → Account Settings → Delegate Access**). Without it, Graph returns `403: Cannot find row based on condition` for searches against `OUTLOOK_REPLY_TO`. |

A few constraints to keep in mind:

- **ETL freshness.** Source ETLs run hourly for mirrored discussions/forums. If `source-etl-query` returns zero rows, wait 10 min and retry — the skill isn't broken. Live GitHub checks use `github-readonly-live` and do not depend on the mirror.
- **Session boundaries.** Each Outlook email opens a fresh session. Slack thread replies (same `thread_ts`) share one session. Cross-session continuity comes only from the memory subsystem.

---

## The 21 prompts

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
| Q11| nemoclaw-nvteam             | smoke     | Slack DM      |
| Q12| nemoclaw-nvteam             | smoke     | Slack DM      |
| Q13| nemoclaw-nvteam             | realistic | Slack DM      |
| Q14| nemoclaw-nvteam             | realistic | Slack DM      |
| Q15| nemoclaw-nvteam             | realistic | Slack DM      |
| Q16| nemoclaw-nvteam             | realistic | Slack DM      |
| Q17| nemoclaw-nvteam             | realistic | Slack DM      |
| Q18| nemoclaw-nvteam             | realistic | Slack DM      |
| Q19| nemoclaw-nvteam             | realistic | Slack DM      |
| Q20| nemoclaw-nvteam             | realistic | Slack DM      |
| Q21| nemoclaw-nvteam             | interactive | Slack DM    |

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

### github-readonly-live

Sanity-check the live GitHub path from the host shell:

```console
$ openshell sandbox exec --name hermes-direct -- sh -lc \
    '/usr/bin/python3 /sandbox/.hermes-data/skills/github-readonly-live/scripts/github_readonly.py rate-limit'
```

**Expected:** the response shows the authenticated GitHub REST rate limit when
`GITHUB_TOKEN` is configured. The token itself should never appear
in output.

Ask the agent:

> How many issues does the configured GitHub repo have? Use live GitHub, not the ETL mirror.

**Expected:** agent uses the generic helper pattern, for example
`github_readonly.py get issues --param state=all --paginate --count --exclude-pulls`.
It should not use `gh`, `git`, GitHub search, GraphQL, or the source ETL
mirror for this live count.

Also ask:

> How many pull requests are currently open in the configured GitHub repo? Use live GitHub, not the ETL mirror.

**Expected:** agent uses the generic helper pattern, for example
`github_readonly.py get pulls --param state=open --paginate --count`; it should
not estimate from a single `pulls --limit` page.

---

### gitlab-readonly-live

When `GITLAB_TOKEN` and `GITLAB_READONLY_PROJECTS` are configured, verify the
authenticated identity and initial project from the host shell:

```console
$ openshell sandbox exec --name hermes-direct -- sh -lc \
    '/usr/bin/python3 /sandbox/.hermes-data/skills/gitlab-readonly-live/scripts/gitlab_readonly.py identity'
$ openshell sandbox exec --name hermes-direct -- sh -lc \
    '/usr/bin/python3 /sandbox/.hermes-data/skills/gitlab-readonly-live/scripts/gitlab_readonly.py get . --fields path_with_namespace,visibility,default_branch'
```

With multiple projects, add `--project group/project` to the `get` command.
Expected: the authenticated username and configured project metadata appear;
the token itself never does. Requests for unlisted projects, sensitive routes,
and arbitrary URLs must fail without being retried through another tool.

Verify local route validation inside the sandbox. This command must fail before
making a network request:

```console
$ openshell sandbox exec --name hermes-direct -- sh -lc \
    '/usr/bin/python3 /sandbox/.hermes-data/skills/gitlab-readonly-live/scripts/gitlab_readonly.py get variables'
```

To inspect the enforced network boundary, replace `PROJECT_ID` with one of the
numeric IDs printed during bring-up. Both calls below must be denied with `403`;
the value shown in the header is an OpenShell placeholder, not the token:

```console
$ openshell sandbox exec --name hermes-direct -- sh -lc \
    'curl -sS -o /dev/null -w "%{http_code}\\n" -H "Authorization: Bearer openshell:resolve:env:GITLAB_TOKEN" "$GITLAB_API_URL/projects/PROJECT_ID/variables"'
$ openshell sandbox exec --name hermes-direct -- sh -lc \
    'curl -sS -o /dev/null -w "%{http_code}\\n" -X POST -H "Authorization: Bearer openshell:resolve:env:GITLAB_TOKEN" "$GITLAB_API_URL/projects/PROJECT_ID/issues"'
```

---

### source-etl-query

Sanity-check the postgrest bridge first (host shell):

```console
$ curl -sf http://localhost:3100/github_discussions?limit=1 | head -c 300
```

Empty array `[]` is fine — bridge is up but ETL hasn't finished first sync. A `404` or refusal means re-run `bash scripts/00-host-services.sh`.

#### Q7 — smoke

**Send via:** Slack DM to `@myuser_nemoclaw`

> Show me the 3 most recently mirrored GitHub discussions from the source-etl postgrest bridge — title and number only.

**Expected:** agent runs `query_source_etl.py github-discussions --limit 3`.
**Verify:** response contains 3 numbered items. The agent should identify this
as mirrored PostgREST data, not live GitHub data. Current GitHub issues and PRs
should use the separate `github-readonly-live` skill for `GITHUB_READONLY_REPO`.

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

> Use cross-source-gap-analysis. Compare one Slack channel related to NemoClaw against live GitHub issues for the configured repo. Just confirm both sources returned data and report the row count from each — no analysis yet.

**Expected:** agent loads `cross-source-gap-analysis`, then `slack-channel-finder` and `github-readonly-live`, fetches a small slice from each.
**Verify:** reply mentions both source counts as concrete numbers. No actual gap analysis yet — wiring proof only.

#### Q10 — realistic

**Send via:** email to `OUTLOOK_TARGET_MAILBOX`
**Subject:** `Slack-vs-GitHub gaps for NemoClaw`

> Run a cross-source-gap-analysis: pick one NemoClaw-related Slack channel, sample the last 7 days, and compare against live open GitHub issues in the configured repo. Tell me which topics are discussed in Slack but have no corresponding GitHub issue, and which GitHub issues have no Slack discussion. Use the skill's documented "scope / agree / gaps / follow-ups" structure.

**Expected:** agent picks a channel via `slack-channel-finder`, summarizes via `slack-channel-summarizer`, queries live issues through `github-readonly-live`, normalizes both, presents a 4-section reply.
**Verify:** reply contains all four documented section headings — `scope and time window`, `what all sources agree on`, `gaps or mismatches`, `concrete follow-ups` — and grounds each gap in a specific channel message or GitHub issue number, not generic abstractions.

---

### nemoclaw-nvteam

For every NVTeam prompt below, verify that a newly routed response starts with
the literal `<Name> (<Role>) active —` receipt and ends with
exactly one execution-status line beginning `RESULT`, `PARTIAL`, or `BLOCKED`.
On the first response of each fresh conversation, also verify that the agent
first renders a compact `Your NVTeam` table with all eight names and roles. The
table should be a native Rich Block table while remaining readable as text.
For the substantive prompts Q13–Q20, no accepted mission is supplied, so the
response must also mark mission alignment `NOT VERIFIED`. Labels such as “PM
person (River)” identify a role lens; they do not identify a real person or
grant authority.

#### Q11 — PM person (River), availability smoke

**Send via:** a fresh Slack DM thread to `@myuser_nemoclaw`

> Is River available?

**Expected:** agent loads `nemoclaw-nvteam`, the River persona card,
and the Slack response profile without inspecting or changing model or runtime
configuration.
**Verify:** after the one-time team table, reply begins `River (Product Manager) active —`, does not present River as a model,
configuration, or separate agent, and ends `RESULT — River activated.`

#### Q12 — PM person (River), explicit activation smoke

**Send via:** a second fresh Slack DM thread to `@myuser_nemoclaw`

> use nvteam river

**Expected:** same activation behavior as Q11 through the explicit NVTeam form.
**Verify:** reply begins `River (Product Manager) active —`, grants no permission or authority,
and ends `RESULT — River activated.`

#### Q13 — PM person (River), sparse-evidence decision

**Send via:** a third fresh Slack DM thread to `@myuser_nemoclaw`

> Desired outcome: community growth. No confirmed user segment, problem evidence, baseline, target, owner, date, mentor capacity, API stability, dependency evidence, or accepted mission is supplied. Frame the product decision without filling the gaps.

**Expected:** automatic routing selects River, preserves community growth as
the only supplied outcome, and proposes one coherent learning-oriented V0.
**Verify:** the substantive response labels unsupported current state `NOT
VERIFIED`; labels every new target, threshold, date, owner, dependency, sample
size, measure, and V0 `PROPOSED`; invents no commitment; asks for the next
product decision; and ends with one `RESULT`, `PARTIAL`, or `BLOCKED` line.

#### Q14 — TPM person (Quinn), cross-functional readiness

**Send via:** a fresh Slack DM thread to `@myuser_nemoclaw`

> Run a wear-all-the-hats launch-readiness review for a synthetic candidate. Product scope is accepted. Engineering reports the feature complete but supplies no commit. QA reports 18 of 20 cases passing with two unexplained timeouts. SRE has not exercised rollback. Security reviewed the design but provides no control evidence. The demo requires an undocumented H100 image. Identify what is verified, what is not, what truly must wait, what can safely proceed in parallel, owners or ownership gaps, and a recommendation without inventing approvals.

**Expected:** automatic routing selects the TPM lens (Quinn) and covers the
product, engineering, data and ML, quality, SRE, security, and TME lenses.
**Verify:** the reply preserves `18 of 20` as `VERIFIED AS REPORTED`, writes
`Critical path: NOT VERIFIED`, writes `Owner: NOT VERIFIED` where needed,
labels any recommended gate or sequence `PROPOSED`, proposes parallel
workstreams that state what they advance or unblock and where they converge,
identifies what still needs confirmation before treating them as independent,
and infers no approval.

#### Q15 — backend and systems engineering person (Akira)

**Send via:** a fresh Slack DM thread to `@myuser_nemoclaw`

> A 10% canary raised p99 latency from 180 ms to 410 ms and has intermittent OOM kills. The code diff adds an unbounded retry queue. Trace the failure to the implementation contract and propose the smallest compatible code change, observability, and implementation-owned unit and integration tests.

**Expected:** automatic routing selects the backend and systems engineering
lens (Akira).
**Verify:** the reply separates the observed queue change and symptoms from a
`NOT VERIFIED` root cause, proposes a small compatible design and focused
proof, and does not claim release, incident, or merge authority.

#### Q16 — QA person (Robin)

**Send via:** a fresh Slack DM thread to `@myuser_nemoclaw`

> Seven H100 test failures remain, four sharing a timeout signature. The canary readiness check still passes, rollback has not been tested this quarter, and no agreed latency threshold was supplied. Give an independent quality recommendation, group failures, and identify the smallest evidence that should gate resumption.

**Expected:** automatic routing selects the QA lens (Robin).
**Verify:** the reply does not turn similar timeout signatures into a verified
failure cluster, cause, flake, or regression; labels any new resumption gate,
threshold, or rerun count `PROPOSED`; and keeps the recommendation within the
quality lens.

#### Q17 — SRE person (Alex)

**Send via:** a fresh Slack DM thread to `@myuser_nemoclaw`

> The canary has intermittent OOM kills, p99 is 410 ms versus 180 ms before the change, and rollback has not been exercised this quarter. Decide the immediate operational action, blast radius, observability needed, and rollback or recovery sequence.

**Expected:** automatic routing selects the SRE lens (Alex).
**Verify:** the reply distinguishes observed symptoms from healthy, ready,
incident, severity, and blast-radius conclusions; marks rollback `NOT
VERIFIED`; proposes a reversible path; and does not authorize a live change.

#### Q18 — security person (Morgan)

**Send via:** a fresh Slack DM thread to `@myuser_nemoclaw`

> A worker asks an agent to summarize one private repository and post the result to one approved internal destination. A shared long-lived production credential is available, but its effective permissions and delegation are not verified. Design the maximum safe capability and fallback.

**Expected:** automatic routing selects the security lens (Morgan).
**Verify:** the reply rejects unverified broad credentials; makes a scoped,
short-lived, revocable read capability conditional on verified identity and
delegation; keeps posting or other writes denied unless separately authorized;
keeps residual-risk ownership `NOT VERIFIED`; and preserves a useful
credential-free fallback.

#### Q19 — DevRel/TME person (Parker)

**Send via:** a fresh Slack DM thread to `@myuser_nemoclaw`

> A beta feature measured 3x faster in one internal benchmark, but the GPU type was not recorded and public availability is not approved. Its demo uses latest main, assumes VPN and H100 access, and has no reset path. Make the developer journey inspiring and independently reproducible without overstating readiness.

**Expected:** automatic routing selects the DevRel/TME lens (Parker).
**Verify:** the reply lowers the barrier to first success, replaces latest main
with an immutable candidate, includes preflight, proof, reset, and next steps,
and keeps the 3x and availability claims bounded to supplied evidence.

#### Q20 — data and ML engineering person (Jordan)

**Send via:** a fresh Slack DM thread to `@myuser_nemoclaw`

> Design a community-signal pipeline from GitHub, Slack, and forum extracts for evaluating documentation friction. The sources have different schemas and no supplied data owner, classification, baseline, or drift threshold. Preserve provenance, propose the smallest useful evaluation, and state how schema change and silent failure are detected.

**Expected:** automatic routing selects the Data and ML Engineer lens (Jordan).
**Verify:** after the one-time team table, the reply starts `Jordan (Data and
ML Engineer) active —`, uses a lineage or evaluation table, keeps each source
distinct, marks missing ownership and classification `NOT VERIFIED`, labels a
new threshold `PROPOSED`, checks schema changes and plausible bias, and prefers
a deterministic baseline before adding ML.

#### Q21 — interactive clarification buttons

**Send via:** a fresh Slack DM thread to `@myuser_nemoclaw`

> Use River. Before planning, I must choose exactly one V0 outcome: reduce setup abandonment, reduce time to first success, or improve recovery completion. No supplied evidence favors one. Ask me to choose before continuing.

**Expected:** River uses Hermes's normal clarification tool with three concise,
mutually exclusive choices. The recipe's compatibility layer presents the
choices as Block Kit buttons.
**Verify:** Slack shows three one-tap outcome buttons plus `Other`. Clicking one
replaces the controls with the selected answer and the agent continues the
normal turn. The click does not approve, publish, deploy, or perform another
side effect. A typed answer remains a valid fallback.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Outlook search Q2 returns 403 | Bot lacks delegate access to `OUTLOOK_REPLY_TO`. Either grant it (Outlook → File → Account Settings → Delegate Access) or substitute `OUTLOOK_TARGET_MAILBOX` in the prompt. |
| Outlook search Q2 hangs without ever replying | `OUTLOOK_REPLY_TO` returns 404 from Graph — the address isn't a real Entra user in your tenant. Confirm via the bridge log (`openshell sandbox exec --name hermes-direct -- tail -50 /tmp/outlook-bridge.log \| grep 404`). Fix: set `OUTLOOK_REPLY_TO` to a real mailbox you own and rebuild. To unblock the in-flight request: `openshell sandbox exec --name hermes-direct -- pkill -f outlook-bridge.py`. |
| `source-etl-query` returns 0 rows for everything | Run `curl -sf http://localhost:3100/github_discussions?limit=1` and `curl -sf http://localhost:3100/forum_topics?limit=1`. Empty → ETL hasn't completed first sync (wait 10 min). Unreachable → re-run `bash scripts/00-host-services.sh`. |
| `grep: /sandbox/.hermes-data/...: No such file or directory` (running side-checks against the sandbox) | `openshell sandbox exec` doesn't run a shell, so `*.md` and other globs don't expand. Wrap in `bash -c '…'`, or pass explicit filenames. |
