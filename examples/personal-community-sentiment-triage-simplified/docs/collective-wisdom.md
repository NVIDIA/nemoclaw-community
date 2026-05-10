---
title:
  page: "Collective Wisdom: Slack + Live Search Skill Demo"
  nav: "Collective Wisdom"
description:
  main: "A reproducible demo where a Slack user teaches the simplified personal community sentiment triage agent a durable digest format, snapshots it, rebuilds the sandbox, restores the snapshot, and proves the learned skill can be reused from a fresh Slack session."
  agent: "Collective-wisdom demo for personal-community-sentiment-triage-simplified. User A on Slack iteratively narrows a live community digest format using Slack, GitHub CLI, and Tavily evidence. The agent should infer a reusable skill, write SKILL.md under /sandbox/.hermes-data/skills, and reload skills. Snapshot, tear down, bring up, restore, then User B or a fresh Slack session invokes the same digest format by natural language."
keywords: ["hermes collective wisdom", "slack agent learns skill", "snapshot restore skill", "tavily github digest"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "slack", "tavily", "github", "skills", "collective-wisdom", "snapshot"]
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

![NVIDIA](../../assets/nvidia_header.png)

# Collective Wisdom: Slack + Live Search

This walkthrough proves that the simplified personal triage agent can turn a
conversation into reusable behavior:

1. A Slack user narrows a vague community update into a stable digest format.
2. The agent recognizes the request as durable, writes a `SKILL.md` under
   `/sandbox/.hermes-data/skills/`, and reloads skills with
   `nemoclaw_reload_skills`.
3. `scripts/snapshot.sh` captures the learned skill, `scripts/restore.sh`
   restores it after a full sandbox rebuild, and a fresh Slack session can
   invoke the same format from natural language.

Unlike the full personal demo, this version does not use Outlook or host ETL
mirrors. Evidence comes from Slack, `github-cli-search`, and `tavily-web-search`.

## Prerequisites

| Check | One-liner |
|---|---|
| Sandbox is ready | `openshell sandbox list \| grep hermes-direct` |
| Slack app handle | Note your bot handle from [set-up-slack.md](set-up-slack.md); this guide uses `@<your-bot>`. |
| At least one Slack user is authorized | `grep SLACK_ALLOWED_IDS .env` lists at least one `U...` ID. Two users are ideal; one user in a fresh session still proves durability. |
| Skills dir is writable | `openshell sandbox exec --name hermes-direct -- ls -la /sandbox/.hermes-data/skills/` |
| Live search works | Run the Tavily and GitHub checks in [verify-functionality.md](verify-functionality.md). |

## Step 0 — Start Clean

Remove any user-authored skills from previous dry runs. Keep the five baked-in
skills.

```console
$ openshell sandbox exec --name hermes-direct -- bash -c 'cd /sandbox/.hermes-data/skills/ && for d in */; do case "${d%/}" in cross-source-gap-analysis|github-cli-search|slack-channel-finder|slack-channel-summarizer|tavily-web-search) ;; *) echo "removing ${d%/}"; rm -rf "$d" ;; esac; done'
```

## Step 1 — User A Teaches A Digest Format In Slack

Send the prompts below in a Slack DM to `@<your-bot>`.

### Prompt 1.1 — Start Vague

> Give me a daily update on what is important for NemoClaw right now.

Let the agent choose its first structure. It should use some mix of Slack,
GitHub, and Tavily evidence.

### Prompt 1.2 — Pin The Format

> That's useful, but make it a repeatable digest. Give me exactly 5 GitHub items and 3 web/forum findings. For each item include the source, title, URL, status if available, and a one-line "why it matters". Open with `**NemoClaw Live Community Digest — {date}, last 7 days**` and close with `**Bottom line:**` in 2-3 sentences. No flowing prose outside those sections.

The reply should now have the format you want preserved.

### Prompt 1.3 — Ask For Durability Without Naming The Mechanism

> Perfect, that's the format I want every day. Next time I ask for "the live NemoClaw community digest" or "what's hot on NemoClaw lately," I want exactly this format — same header, same 5 GitHub items + 3 web/forum findings shape, same `**Bottom line:**` closer — without spelling it out again. If a coworker asks the bot in Slack, they should get the same format too.

There are three valid outcomes:

- The agent volunteers to save this as a reusable skill and writes a `SKILL.md`.
- The agent asks permission to save it; reply `Yes, please.`
- The agent only acknowledges; nudge once:

> Could you save this somewhere durable so I and coworkers get the same format next time? Use the right mechanism for this agent.

If it still does not create a skill, use the Plan B skill at the end of this doc.

## Step 2 — Verify The Skill Exists

Find any new `SKILL.md` outside the baked-in skills:

```console
$ NEW_SKILL_PATH=$(openshell sandbox exec --name hermes-direct -- bash -c 'find /sandbox/.hermes-data/skills -name SKILL.md' | grep -vE "/(cross-source-gap-analysis|github-cli-search|slack-channel-finder|slack-channel-summarizer|tavily-web-search)/SKILL.md$")
$ echo "$NEW_SKILL_PATH"
```

Inspect it:

```console
$ openshell sandbox exec --name hermes-direct -- cat "$NEW_SKILL_PATH" | head -40
$ NEW_SKILL=$(openshell sandbox exec --name hermes-direct -- awk '/^name:/{print $2; exit}' "$NEW_SKILL_PATH")
$ echo "NEW_SKILL=$NEW_SKILL"
```

Expected:

- Frontmatter starts with `name:` and `description:`.
- Body mentions the digest header, 5 GitHub items, 3 web/forum findings, and
  `**Bottom line:**`.
- The agent either already ran `nemoclaw_reload_skills` or can do so when asked.

## Step 3 — Snapshot

```console
$ SNAP=$(bash scripts/snapshot.sh)
$ echo "$SNAP"
$ tar tzf "$SNAP" | grep "$NEW_SKILL"
```

Expected: the tarball includes the learned skill.

## Step 4 — Rebuild Fresh

```console
$ bash scripts/tear-down.sh
$ bash scripts/bring-up.sh
```

Confirm the learned skill is gone before restore:

```console
$ openshell sandbox exec --name hermes-direct -- bash -c 'find /sandbox/.hermes-data/skills -name SKILL.md' | grep -vE "/(cross-source-gap-analysis|github-cli-search|slack-channel-finder|slack-channel-summarizer|tavily-web-search)/SKILL.md$"
$ echo "(empty output = clean slate)"
```

## Step 5 — Restore

```console
$ bash scripts/restore.sh "$SNAP"
$ openshell sandbox exec --name hermes-direct -- bash -c 'find /sandbox/.hermes-data/skills -name SKILL.md' | grep "$NEW_SKILL"
```

Expected: the learned skill path returns. The next new Slack session will rescan
skills on session start; if you want immediate confirmation, DM:

> Reload your skills and list the ones you have now.

## Step 6 — User B Or A Fresh Slack Session Invokes It

From a different authorized Slack user if available, or from a new DM/thread if
running solo, send:

> Give me the live NemoClaw community digest for the last 3 days.

Expected:

- Header follows `**NemoClaw Live Community Digest — {date}, last 3 days**`.
- Output includes 5 GitHub items and 3 web/forum findings when the sources have
  enough evidence.
- The reply closes with `**Bottom line:**`.
- The agent uses live source skills and does not depend on the original
  conversation context.

## Plan B — Canonical Skill

If the agent does not create a skill on its own, create a local file named
`/tmp/live-community-digest-SKILL.md` with this content and upload it to
`/sandbox/.hermes-data/skills/live-community-digest/SKILL.md`:

```markdown
---
name: live-community-digest
description: Produce the saved NemoClaw live community digest format using Slack, GitHub CLI, and Tavily evidence.
---

# Live Community Digest

Use this skill when the user asks for the live NemoClaw community digest, what
is hot on NemoClaw lately, or a daily community update.

Gather recent evidence from:

- `github-cli-search` for GitHub issues and pull requests.
- `tavily-web-search` for NVIDIA forum, docs, and broader web findings.
- Slack skills when the user asks to include workspace discussion.

Reply in this exact shape:

`**NemoClaw Live Community Digest — {date}, last {N} days**`

## GitHub items

Exactly 5 bullets when available. Each bullet includes source, title, URL,
status if available, and one-line why it matters.

## Web/forum findings

Exactly 3 bullets when available. Each bullet includes source, title, URL, and
one-line why it matters.

`**Bottom line:**` 2-3 sentences.

Do not invent missing evidence. Say "not observed in this search" when a source
does not return enough results.
```

Then run:

```console
$ SANDBOX_NAME=${SANDBOX_NAME:-hermes-direct}
$ openshell sandbox exec --name "$SANDBOX_NAME" -- mkdir -p /sandbox/.hermes-data/skills/live-community-digest
$ openshell sandbox upload --no-git-ignore "$SANDBOX_NAME" /tmp/live-community-digest-SKILL.md /sandbox/.hermes-data/skills/live-community-digest/SKILL.md
```

Ask the agent to reload skills, then continue from Step 2.
