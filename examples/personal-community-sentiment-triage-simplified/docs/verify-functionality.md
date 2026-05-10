---
title:
  page: "Verify Simplified Skill Functionality"
  nav: "Verify Skills"
description:
  main: "Copy-pasteable Slack prompts that verify the simplified community sentiment triage skills: Slack discovery, Slack summarization, Tavily live web/forum search, GitHub CLI search, and cross-source gap analysis."
  agent: "End-to-end functional verification recipe for the personal-community-sentiment-triage-simplified example. Use after scripts/bring-up.sh and the README plumbing checks pass. Contains Slack prompts and expected verification cues for slack-channel-finder, slack-channel-summarizer, tavily-web-search, github-cli-search, and cross-source-gap-analysis."
keywords: ["nemoclaw simplified verification", "hermes slack verification", "tavily github cli smoke test"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "slack", "tavily", "github", "verification"]
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

# Verify Simplified Skill Functionality

This guide verifies the simplified demo at the agent level. The README plumbing
checks prove the sandbox, providers, and health endpoint are up; these prompts
prove Hermes can use the skills that make the Slack-first triage workflow useful.

All prompts are written for Slack because this demo intentionally removes the
Outlook bridge. Replace `@<your-bot>` with the bot handle from
[set-up-slack.md](set-up-slack.md).

## Prerequisites

| Check | One-liner |
|---|---|
| Sandbox is ready | `openshell sandbox list \| grep hermes-direct` |
| Slack responds | DM `ping` to `@<your-bot>` from an allowlisted Slack user. |
| Tavily script works | `openshell sandbox exec --name hermes-direct -- /usr/bin/python3 /sandbox/.hermes-data/skills/tavily-web-search/scripts/tavily_search.py --query "NemoClaw NVIDIA forums" --max-results 2` |
| GitHub CLI script works | `openshell sandbox exec --name hermes-direct -- /usr/bin/python3 /sandbox/.hermes-data/skills/github-cli-search/scripts/gh_search.py search --query "repo:NVIDIA/NemoClaw is:issue" --limit 2` |

## Quick Reference

| # | Skill | Type | Send via |
|---|---|---|---|
| Q1 | `slack-channel-finder` | smoke | Slack DM |
| Q2 | `slack-channel-summarizer` | smoke | Slack DM or thread |
| Q3 | `tavily-web-search` | smoke | Slack DM |
| Q4 | `github-cli-search` | smoke | Slack DM |
| Q5 | `cross-source-gap-analysis` | realistic | Slack DM or thread |

## The Prompts

### Q1 — Slack Channel Discovery

**Send via:** Slack DM to `@<your-bot>`

> List 5 public Slack channels this bot can see. Return channel names and IDs only.

**Expected:** Hermes uses `slack-channel-finder` and the Slack Web API.

**Verify:** The reply contains channel IDs that begin with `C`. If the bot has
limited workspace access, a smaller list is acceptable as long as it says what
it could access.

### Q2 — Slack Channel Summary

**Send via:** Slack DM or a thread in a channel where the bot is a member.

> Pick one channel you can access and summarize the most recent 10 messages. Include the channel ID and the time window.

**Expected:** Hermes uses `slack-channel-summarizer`.

**Verify:** The reply names a channel ID, stays grounded in recent messages, and
does not claim Slack is unavailable unless the API returns a concrete error.

### Q3 — Tavily Live Web / Forum Search

**Send via:** Slack DM to `@<your-bot>`

> Search the live web for recent NVIDIA forum or docs discussion about NemoClaw. Return the top 5 results with title, URL, and a one-line why it matters.

**Expected:** Hermes uses `tavily-web-search`.

**Verify:** The reply includes live URLs and uses cautious language such as
"not observed in this search" rather than claiming the web has no results.

### Q4 — GitHub CLI Search

**Send via:** Slack DM to `@<your-bot>`

> Search GitHub for open issues in NVIDIA/NemoClaw related to Slack, skills, or sandbox setup. Return issue number, title, state, URL, and one-line relevance.

**Expected:** Hermes uses `github-cli-search` through the configured GitHub
provider token.

**Verify:** The reply includes GitHub issue numbers or explicitly says no
matching issues were observed for the query. It should not try to reach GitHub
through an unapproved ad hoc path.

### Q5 — Cross-Source Gap Analysis

**Send via:** Slack DM or a thread in a channel where the bot is a member.

> Run a cross-source-gap-analysis for NemoClaw onboarding friction. Compare recent Slack discussion you can access, live GitHub issues, and Tavily web/forum results. Use sections: scope and time window, what all sources agree on, gaps or mismatches, concrete follow-ups.

**Expected:** Hermes combines `slack-channel-finder` or
`slack-channel-summarizer`, `github-cli-search`, `tavily-web-search`, and
`cross-source-gap-analysis`.

**Verify:** The reply includes all four requested sections and grounds each
claim in at least one observed source. It should distinguish "not observed in
this sample" from "does not exist."

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Slack returns a red reaction or no answer | Your Slack user ID may be missing from `SLACK_ALLOWED_IDS`; update `.env` and rebuild. |
| Tavily returns auth errors | Check `TAVILY_API_KEY` and rerun `bash scripts/02-providers.sh` or `bash scripts/bring-up.sh`. |
| GitHub CLI returns auth errors | Check `GITHUB_TOKEN` or `GH_TOKEN`; the sandbox maps both to the GitHub CLI path. |
| The bot invents web/forum certainty | Re-prompt it to use `tavily-web-search` and report only observed results. The skill explicitly requires scoped uncertainty. |
