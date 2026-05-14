---
title:
  page: "Collective Wisdom: Skill-Learning + Cross-Channel Demo"
  nav: "Collective Wisdom"
description:
  main: "A reproducible 15-minute demo where one user teaches the agent a custom report format, the new skill is captured by snapshot, survives a full sandbox tear-down, and a different user invokes the same skill from a different channel — proving that learned behavior is durable, transferable across users, and channel-agnostic."
  agent: "End-to-end demo for collective wisdom in the personal-community-sentiment-triage example. User A on Slack iteratively narrows a 'daily NemoClaw issue update' request, then expresses (without naming the mechanism) that they want this format to persist for future asks and for coworkers. The agent should infer that this is a candidate for a reusable skill, write SKILL.md under /sandbox/.hermes-data/skills/<agent-chosen-name>/, and reload via nemoclaw_reload_skills. Snapshot, tear down, bring up, restore — then User B on Outlook (or Slack) asks for the same kind of update via natural language and gets the identical format, proving snapshot/restore + cross-user + cross-channel persistence of learned behavior. Includes a Plan B path where a canonical SKILL.md (daily-issue-digest) is uploaded manually if the agent doesn't infer the durable mechanism."
keywords: ["hermes collective wisdom", "agent learns skill", "snapshot restore skill", "cross channel skill recall", "multi user agent skill"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "outlook", "slack", "skills", "collective-wisdom", "snapshot", "demo"]
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

# Collective Wisdom: Skill-Learning Across Users and Channels

This demo proves three durability properties of the agent in a single 15-minute walkthrough:

1. **Skills are learnable from conversation.** User A iteratively narrows a vague request into a specific output format, then expresses they'd like the same format next time and for coworkers — without ever using the words "skill," "save," or "write a file." The agent infers a reusable skill is the right durable mechanism, writes a `SKILL.md` under `/sandbox/.hermes-data/skills/`, and registers it via `nemoclaw_reload_skills` — see the `_reload_skills()` function in [`agents/hermes/plugin/__init__.py`](../agents/hermes/plugin/__init__.py).
2. **Skills survive a full sandbox rebuild.** `scripts/snapshot.sh` captures `/sandbox/.hermes-data/skills/` (see the state-dir list comment block at the top of that script). After `tear-down.sh` + `bring-up.sh`, `scripts/restore.sh` re-extracts the tarball, and the next session's `on_session_start` hook in [`plugin/__init__.py`](../agents/hermes/plugin/__init__.py) auto-rescans — no manual reload needed.
3. **Skills are not user-bound or channel-bound.** A different person, on a different channel, who never saw the original conversation, invokes the same skill and gets a structurally identical reply — because the skill (the file on disk), not the conversation, encodes the format.

The README's [§ Persistence: collective wisdom across restarts](../README.md#persistence-collective-wisdom-across-restarts) covers the snapshot/restore mechanics in prose. This guide turns those mechanics into a reproducible end-to-end demo.

## Prerequisites

| Check | One-liner |
|---|---|
| Sandbox is `Ready` | `openshell sandbox list \| grep hermes-direct` |
| Slack app handle | Note your bot's `@`-handle from the Slack app manifest (see [set-up-slack.md](set-up-slack.md)). The doc refers to it as `@<your-bot>` — substitute as you go. |
| At least one Slack user authorized | `grep SLACK_ALLOWED_IDS .env` lists ≥1 `U…` ID. The cross-user step (7) wants ≥2 — if you only have one, run that step yourself from a different channel and the cross-channel claim still holds. |
| Outlook bridge works | Send `ping` to `OUTLOOK_TARGET_MAILBOX` from any address in `OUTLOOK_ALLOWED_SENDERS` (or any sender if that var is empty); reply within ~30s. |
| ETL has data | `curl -sf http://localhost:3100/github_issues?limit=1 \| head -c 200` returns a non-empty array |
| Skills dir is writable | `openshell sandbox exec --name hermes-direct -- ls -la /sandbox/.hermes-data/skills/` lists 5 baked-in skills, all owned by `sandbox` |

A few notes:

- **`forum_topics` may be sparse** (3 rows on a fresh fixture). The skill we're building handles this in its Pitfalls section — it falls back to filling "Discussions and forums" bullets from `github-discussions` only. That's expected behavior, not a failure.
- **Channels are session-bounded.** Each Outlook email opens a fresh session, so step 7's recall happens in a brand-new conversation context. That's exactly the property we're testing.

## Cast

The demo has two roles. Whoever fills them is up to you and what's in your allowlists.

| Role | Channel | What they do |
|---|---|---|
| **User A** | Slack DM | Iterates on a daily-update format, then expresses to the agent that they'd like the same format next time. |
| **User B** | Outlook email | Never participated in User A's conversation. Asks for the same kind of update from a fresh session and gets the same format. |

If you have a coworker whose Slack ID is in `SLACK_ALLOWED_IDS` and whose email is on the `OUTLOOK_ALLOWED_SENDERS` list (or who can send from any address if that variable is empty), they're a natural User B — the cross-user claim is fully proven. If you're running solo, you can play both roles on different channels (Slack DM in step 1, Outlook email in step 7); cross-channel still holds, and "cross-user" softens to "different sessions, same human."

> **Note**: Throughout this doc, `@<your-bot>` is a placeholder for the handle of your Slack app — whatever name you set in the manifest (see [set-up-slack.md](set-up-slack.md)). Replace with your actual handle as you go.

---

## The demo

Total time: ~15 minutes. Capture a transcript with `script -c bash /tmp/cw-dryrun-$(date +%s).log` if you want a paper trail.

### Step 0 — Pre-flight

```console
$ openshell sandbox list | grep hermes-direct
$ openshell sandbox exec --name hermes-direct -- ls /sandbox/.hermes-data/skills/
$ grep SLACK_ALLOWED_IDS .env
```

Expected: sandbox `Ready`; skills dir contains the 5 baked-in skills (`cross-source-gap-analysis`, `outlook-email-search`, `slack-channel-finder`, `slack-channel-summarizer`, `source-etl-query`); `SLACK_ALLOWED_IDS` lists at least one ID.

If a sixth, user-authored skill from a previous run is sitting in the skills directory, wipe anything that isn't one of the five baked-in names so the demo starts on a clean slate:

The command must be on a single line — `openshell sandbox exec` rejects literal newlines in the command argument (gRPC `InvalidArgument: command argument 2 contains newline or carriage return characters`). Use `;` separators instead of multi-line scripts.

```console
$ openshell sandbox exec --name hermes-direct -- bash -c 'cd /sandbox/.hermes-data/skills/ && for d in */; do case "${d%/}" in cross-source-gap-analysis|outlook-email-search|slack-channel-finder|slack-channel-summarizer|source-etl-query) ;; *) echo "removing ${d%/}"; rm -rf "$d" ;; esac; done'
```

### Step 1 — User A iterates on a format via Slack DM

User A sends three prompts in the same DM thread to `@<your-bot>`, each narrowing the previous reply. The third prompt is the load-bearing one: it expresses a desire for the format to stick around without naming the mechanism. The agent should infer that this is a candidate for a reusable skill on its own.

**Prompt 1.1 — start vague:**

> Give me a daily update on important issues for NemoClaw.

The agent will pick its own structure — probably calls `source-etl-query` and replies with prose plus some bullets. Read it. Decide what you'd want every day.

**Prompt 1.2 — pin down the format:**

> That's good but too long. Give me exactly 5 top issues and 3 discussions, each with the issue number, title, state, the GitHub URL, and a one-line "why it matters". Open with a bold header line `**NemoClaw Daily Issue Digest — {date}, last 7 days**` and close with `**Bottom line:**` in 2-3 sentences. No flowing prose anywhere else.

The reply should now look exactly like the format you want every day. This is the format you're about to crystallize as a skill.

**Prompt 1.3 — express the desire, leave the mechanism to the agent:**

> Perfect, that's the format I want every day. Next time I ask for "the daily NemoClaw issue digest" or "what's hot on NemoClaw lately," it would be really helpful to get back exactly this format — same header, same 5 issues + 3 discussions shape, same `**Bottom line:**` closer — without me having to spell it out again. And if a coworker emails the bot for the same kind of update, they should get the same format too.

The phrasing deliberately doesn't mention "skill," "save," "write a file," or any plumbing. The whole point is to see whether the agent recognizes a recurring, format-stable, multi-user request and proposes the right durable mechanism on its own.

There are three valid ways the agent can respond — all of them count as a pass:

1. **Volunteer.** The agent says something like "I'll save this as a reusable skill so anyone asking for the daily NemoClaw issue digest gets the same shape" and proceeds to write a `SKILL.md` under `/sandbox/.hermes-data/skills/<some-name>/` and call `nemoclaw_reload_skills`. Best case — fully organic.
2. **Ask first.** The agent says "Want me to save this as a reusable skill so I respond with the same format next time?" — reply: `Yes, please.` Then it does the work.
3. **Stays silent.** The agent acknowledges the request but doesn't propose a durable mechanism. Soft-nudge once before falling back to Plan B:
   > Could you save this somewhere so I (and any coworker) get the same format next time without spelling it out? Use whatever the right place is for that on this agent.

   The agent should then create the skill. If it still doesn't, jump to **Plan B** at the bottom of this doc — you'll drop the canonical SKILL.md in via `openshell sandbox upload` and resume at step 2.

Whatever path you take, what should land on disk afterward is a new directory under `/sandbox/.hermes-data/skills/` that wasn't there before — agent-named in paths 1-2, canonical-named (`daily-issue-digest`) in Plan B. The verification in step 2 doesn't care which.

**This proves:** the agent can recognize a "make this repeatable for me and others" moment and durably encode the format from a conversational specification.

### Step 2 — Verify the new skill is on disk and loaded

The agent picked its own name and its own organizational layout — for example, it might place the skill flat at `skills/<name>/SKILL.md`, or it might categorize it under `skills/<category>/<name>/SKILL.md`. Both are fine: Hermes' skill scanner walks the skills tree recursively (see the `rglob("SKILL.md")` call in `agent/skill_commands.py` — searchable via [github.com/NVIDIA/NemoClaw](https://github.com/NVIDIA/NemoClaw)), so any depth works, and skills are identified by their YAML `name:` field rather than their directory path. Three short sub-steps: **find** → **inspect / capture** → **confirm gateway**.

#### 2a — Find the new SKILL.md

Look for any SKILL.md under `skills/`, then exclude the five baked-in skills. Capture the full path:

```console
$ NEW_SKILL_PATH=$(openshell sandbox exec --name hermes-direct -- bash -c \
    'find /sandbox/.hermes-data/skills -name SKILL.md' \
    | grep -vE "/(cross-source-gap-analysis|outlook-email-search|slack-channel-finder|slack-channel-summarizer|source-etl-query)/SKILL.md$")
$ echo "Path: $NEW_SKILL_PATH"
```

Expected: exactly one path. Possible shapes the agent may produce:

- `/sandbox/.hermes-data/skills/<name>/SKILL.md` — flat
- `/sandbox/.hermes-data/skills/<category>/<name>/SKILL.md` — categorized (e.g. under `reporting/`)

Either works. If the output is empty, the agent didn't write a SKILL.md → use **Plan B** at the bottom of this doc.

#### 2b — Inspect frontmatter and capture name + leaf dir

```console
$ openshell sandbox exec --name hermes-direct -- cat "$NEW_SKILL_PATH" | head -40
$ NEW_SKILL=$(openshell sandbox exec --name hermes-direct -- awk '/^name:/{print $2; exit}' "$NEW_SKILL_PATH")
$ NEW_SKILL_DIR=$(dirname "$NEW_SKILL_PATH")
$ echo "NEW_SKILL=$NEW_SKILL"
$ echo "NEW_SKILL_DIR=$NEW_SKILL_DIR"
```

Expected:

- First line is `---`, then `name: <something>`, then `description: <something>`, then `---`
- Body contains the format scaffolding from step 1.2: `**NemoClaw Daily Issue Digest …**`, `**Top issues**`, `**Bottom line:**`
- `$NEW_SKILL` is the **frontmatter `name`** — whatever the agent picked (or `daily-issue-digest` if you used Plan B). This is the canonical identity the gateway uses, regardless of how the agent organized the directory tree
- `$NEW_SKILL_DIR` is the leaf dir holding `SKILL.md` (used by later steps for snapshot/restore/reset)

#### 2c — Confirm the gateway sees it

Two ways to check:

- DM `@<your-bot>` with:

  > Can you list your skills you have now.

  The reply lists `$NEW_SKILL` alongside the other five.
- Or look at the `nemoclaw_reload_skills` output the agent printed in step 1.3 — the tool returns the full registry inline.

If the skill is on disk (2a) but not yet visible in the registry (2c), tell the agent `Reload skills using nemoclaw_reload_skills`. The plugin's `on_session_start` hook also auto-rescans on the next message in any new session, so the skill becomes visible automatically there.

**This proves:** the skill is registered and invokable, regardless of whether the agent placed it flat or under a category dir. The gateway recognizes it by its `name:` field, not its path.

### Step 3 — Snapshot

First confirm `$NEW_SKILL` is populated in this shell (it was set in step 2b). If `echo $NEW_SKILL` is empty, re-run step 2a + 2b before continuing.

```console
$ echo "NEW_SKILL=$NEW_SKILL"        # must print the skill's name (agent-picked, or 'daily-issue-digest' from Plan B)
$ SNAP=$(bash scripts/snapshot.sh)
$ echo "Snapshot tarball: $SNAP"
$ tar tzf "$SNAP" | grep "/$NEW_SKILL/"
```

Expected: the `tar tzf` grep prints the skill's directory and its files inside the tarball — e.g. `./skills/<your-skill-name>/SKILL.md` for a flat layout, or `./skills/<category>/<your-skill-name>/SKILL.md` for a categorized one. The grep matches `$NEW_SKILL` as a path component, so it works regardless of whether the agent flat or nested the skill, and regardless of the `./` prefix `tar` adds when capturing from `-C $STATE_ROOT .`.

The snapshot script's credential filter (file-name match on `.env`, `*token*`, `*secret*`, etc.) leaves regular `.md` and `.py` files untouched — see the state-dir list and the `# ── Credential filter ───` block in `scripts/snapshot.sh`.

**This proves:** snapshots capture user-authored skills, not just memories.

### Step 4 — Tear down + bring up fresh

```console
$ bash scripts/tear-down.sh
$ bash scripts/bring-up.sh
```

Wait until `openshell sandbox list` shows `hermes-direct` as `Ready` again. The whole writable layer of the old container is gone — every byte of `/sandbox/.hermes-data/` is reset to whatever was image-baked.

### Step 5 — Confirm the fresh sandbox has no trace of the new skill

Re-run the same `find` from step 2a — it should return empty (no SKILL.md outside the five baked-in ones):

```console
$ openshell sandbox exec --name hermes-direct -- bash -c \
    'find /sandbox/.hermes-data/skills -name SKILL.md' \
    | grep -vE "/(cross-source-gap-analysis|outlook-email-search|slack-channel-finder|slack-channel-summarizer|source-etl-query)/SKILL.md$"
$ echo "(empty output = clean slate)"
```

Expected: zero non-baked-in SKILL.md files. The category dir the agent created (if any) is gone too — the entire `/sandbox/.hermes-data/` tree was rebuilt from the image.

**This proves:** the clean slate is genuinely clean — anything visible after step 6 came from the snapshot, not from build-time bake-in.

### Step 6 — Restore

```console
$ bash scripts/restore.sh
$ openshell sandbox exec --name hermes-direct -- bash -c \
    'find /sandbox/.hermes-data/skills -name SKILL.md' \
    | grep -vE "/(cross-source-gap-analysis|outlook-email-search|slack-channel-finder|slack-channel-summarizer|source-etl-query)/SKILL.md$"
$ openshell sandbox exec --name hermes-direct -- cat "$NEW_SKILL_PATH" | head -10
```

Expected: the `find` returns the same path you captured in step 2a (same depth, same parent dir — the agent's chosen layout is preserved end-to-end). The `cat` prints the SKILL.md byte-identical to what step 2b captured.

The `on_session_start` hook in `plugin/__init__.py` auto-rescans on the next message in any new session, so the next conversation will see the restored skill without a manual reload.

**This proves:** restore is byte-faithful for skills, and the gateway picks them up automatically.

### Step 7 — User B invokes the format from Outlook

User B — who never participated in step 1's conversation, never saw the format negotiation, and is using a different channel — emails `OUTLOOK_TARGET_MAILBOX` from an address on the `OUTLOOK_ALLOWED_SENDERS` list. Note: the prompt below uses the same natural language User A would, never the skill's filename. The agent should match it against the skill via the skill's `description:` field.

**Subject:** `Daily NemoClaw digest`

> Give me the daily NemoClaw issue digest — the last 3 days, please.

Wait ~30s for the bridge to reply by email.

Expected: the email reply opens with `**NemoClaw Daily Issue Digest — {date}, last 3 day(s)**`, contains exactly 5 issue bullets and 3 discussion/forum bullets, and closes with `**Bottom line:**` followed by 2-3 sentences. Actual issue numbers and titles are pulled live from the mirror — they will be specific real `NVIDIA/NemoClaw` issues, not placeholders.

**This proves:** a different user, on a different channel, who never saw the seeding conversation, gets the same output shape — and got there from natural language, not the skill's internal name. The skill, not the conversation, holds the format.

### Step 8 — Cross-verify on Slack

User A DMs `@<your-bot>` from a *new* DM thread (not the one from step 1, so no conversational context carries over):

> Daily NemoClaw digest, last 3 days please.

Expected: structurally identical reply to User B's email — same bold header form, same 5+3 bullet structure, same `**Bottom line:**` closer. Issue numbers may differ slightly if the mirror updated between requests; that's acceptable variance because the data is live.

**This proves:** the skill is channel-stable as well as user-stable.

### Step 9 — Diff the structural lines (optional, compelling)

Save User A's reply (from Slack) and User B's reply (from email) to local text files, then diff just the bold-prefixed lines:

```console
$ diff <(grep -E '^\*\*' user-a-reply.txt) <(grep -E '^\*\*' user-b-reply.txt)
```

Expected: zero diff on the bold-line scaffolding (the structural lines starting with `**`). The body bullets *will* diff because the times are different and the data may have shifted by a few minutes.

**This proves:** the skill enforces format invariants, not just content.

### Step 10 — Reset (optional)

If you want to leave the sandbox in a clean state for further work, remove the agent's leaf skill directory and prune any now-empty category parent up to (but not including) `skills/`:

```console
$ openshell sandbox exec --name hermes-direct -- bash -c "
    rm -rf '$NEW_SKILL_DIR';
    P='$NEW_SKILL_DIR';
    while [ \"\$(dirname \"\$P\")\" != /sandbox/.hermes-data/skills ]; do
      P=\$(dirname \"\$P\");
      rmdir \"\$P\" 2>/dev/null || break;
    done;
    echo OK"
```

The skill cache won't be re-cleared until the next session start, but a fresh DM or email kicks `on_session_start` and the skill drops from the registry naturally. Or DM the agent: `Reload skills` — it'll call `nemoclaw_reload_skills` and the slate is clean.

---

## Why this proves what it proves

| Claim | Evidence |
|---|---|
| Skill was actually learned (not just chatted about) | `SKILL.md` exists on disk after step 2; appears in `nemoclaw_reload_skills` output; gateway slash-command registry contains it. The agent picked the name and the body itself — neither was dictated. |
| Pattern recognition was the agent's, not the user's | Step 1.3's prompt never said "skill," "save," or "write a file." The agent inferred a durable mechanism was wanted. |
| Survived rebuild | Step 5 shows empty skill dir on fresh sandbox; step 6 shows it back, byte-identical. |
| Cross-user | User B's identity was never mentioned in the seeding conversation. The format negotiation is User A's alone. |
| Cross-channel | User A used Slack DM; User B used Outlook email. Reply shape matches. |
| Trigger maps via natural language, not filename | Step 7's email asks for "the daily NemoClaw issue digest" — it never names `$NEW_SKILL`. The agent matches via the skill's `description:` field. |
| Format-stable | Step 9 diff on `^\*\*` lines is empty — the skill enforces the structural scaffolding identically across calls. |

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Step 1.3: agent doesn't propose a durable mechanism after the soft nudge | Some model variants won't infer "make a skill" from natural language. Use **Plan B** below — manually upload the canonical SKILL.md (named `daily-issue-digest`) and resume at step 2 with `NEW_SKILL=daily-issue-digest`. |
| Step 1.3: agent writes the SKILL.md to `/sandbox/.hermes-data/skills/<some path>/SKILL.md` (flat or nested) | This is fine. Hermes' scanner walks the tree recursively (`scan_dir.rglob("SKILL.md")` in `agent/skill_commands.py`) and identifies skills by their YAML `name:` field, not their directory path. Step 2a's `find -name SKILL.md` works at any depth. Don't move the file — let the agent's chosen layout stand. |
| Step 2a: `$NEW_SKILL_PATH` came back empty or contained multiple paths | Empty = the agent didn't write a SKILL.md → use Plan B. Multiple = a stale skill from a previous run wasn't cleaned in step 0; re-run step 0's cleanup loop and step 1. |
| Step 2: SKILL.md missing or has extra frontmatter keys | Agent wrote a malformed file. Either re-prompt with stricter language ("frontmatter has exactly two keys: `name:` and `description:` — no other keys"), or use Plan B. |
| Step 7 reply lacks `**Bottom line:**` closer | The agent didn't actually load the skill — it improvised. Re-prompt with a slightly more specific cue: `Use the daily NemoClaw issue digest format you've saved — same header, same 5+3 bullets, same **Bottom line:** closer.` |
| Step 7 and step 8 replies look structurally different | Skill's procedure is underspecified. Inspect the SKILL.md (`openshell sandbox exec --name hermes-direct -- cat "$NEW_SKILL_PATH"`) and tighten the format block, or rerun the demo from step 1 using Plan B's canonical text. |
| `forum_topics` returns fewer than 3 rows | Known sparse-fixture state. Skill should fall back to `github_discussions` to fill the bottom 3 bullets. If the agent-authored skill doesn't have a fall-back rule in its Pitfalls section, the canonical Plan B text does — swap to it for a deterministic rerun. |
| Step 6: skill not showing up after restore | Tarball may not actually contain it — re-run `tar tzf $SNAP \| grep "$NEW_SKILL"` against the snapshot to confirm (the skill name appears in its directory path regardless of the agent's flat-vs-nested choice). If it's there but not on disk after restore, check `scripts/restore.sh` output for tar errors. |

---

## Plan B — manual SKILL.md upload

Use this path if step 1.3 fails (agent declines, writes to a wrong path, or produces malformed YAML). It's not a workaround — it's the supported path for stricter model variants and for any case where you want bit-perfect reproducibility.

The canonical SKILL.md text is below. Copy it into a host-side file, upload it, and trigger a reload. The outer fence uses four backticks so the inner triple-backtick fences inside the SKILL.md body render correctly.

````console
$ cat > /tmp/SKILL.md << 'SKILLEOF'
---
name: daily-issue-digest
description: Produce a fixed-format daily digest of important NemoClaw GitHub issues, discussions, and forum topics over a recent time window.
---

# daily-issue-digest

Use this skill when a user asks for a "daily update", "issue digest", "what's
hot on NemoClaw", or any recurring summary of community activity scoped to
the configured ETL mirror. Always render the output in the **fixed format**
defined below — that fixed format is the entire reason this skill exists.

## When to use

- "Give me my daily NemoClaw issue update"
- "What are the important issues this week?"
- "Daily digest, last 3 days"
- Any phrasing that combines a recurring cadence with a community-issues focus

## Access model

- Use the existing `source-etl-query` skill's helper script for all data access.
- Do not invent new ETL endpoints; do not attempt live GitHub or forum requests.
- Read three tables in this order: github-issues, github-discussions, forum-topics.

## Required Environment

- SOURCE_ETL_API_URL, or SOURCE_ETL_API_HOST plus SOURCE_ETL_API_PORT
  (the same env the source-etl-query skill consumes — already set in the sandbox).

## Procedure

### 1. Pull recent activity from each source

Default window is 7 days. If the user gave a different window (e.g. "last 3 days"),
adjust --limit upward to be safe — the script returns most-recent first, so
caller-side filtering is fine.

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py github-issues --limit 30
/usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py github-discussions --limit 20
/usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py forum-topics --limit 20
```

### 2. Rank by an importance heuristic

The mirror returns number, state, updated_at, title for issues. Approximate
importance by:

- **Recency** — items updated within the requested window come first.
- **State** — open issues outrank closed ones inside the window.
- **Title keyword weight** — give a +1 bump if the title contains any of:
  crash, regression, security, breaking, gpu, cuda, oom, release, roadmap,
  live stream. (Sentinels of high-attention community traffic on this repo.
  Adjust to taste — the list is not load-bearing.)

Pick the top **5 issues** and the top **3 discussions/forum topics combined**.

### 3. Render in fixed format

Output exactly this shape — no flowing prose, no extra headers:

```
**NemoClaw Daily Issue Digest — {YYYY-MM-DD}, last {N} day(s)**

**Top issues**
- #{number} — {title} — `{state}` — updated {YYYY-MM-DD}
  https://github.com/NVIDIA/NemoClaw/issues/{number}
  Why it matters: {one sentence, grounded in the title or a sibling row}
- … (4 more, total of 5)

**Discussions and forums**
- {discussion or forum title} — {YYYY-MM-DD}
  {URL if available}
  Why it matters: {one sentence}
- … (2 more, total of 3)

**Bottom line:** {2-3 sentences synthesizing the day. Mention any
multi-source theme — e.g. "two issues and one discussion all flag the
same upcoming live-stream demo."}
```

The **Bottom line:** line is **mandatory** — it is the verification cue the
human uses to confirm the skill ran (mirrors the convention in
outlook-email-search).

## Pitfalls

- The mirror refreshes hourly, so very-recent issues may not appear.
- forum_topics is sparsely populated on some fixtures (3 rows is normal).
  If forum-topics returns fewer than 3 rows, fill the "Discussions and forums"
  block from github-discussions only — do not invent forum activity.
- Issue numbers are unique IDs; never substitute one for another. If a row is
  missing a number, omit it rather than guessing.
- Keep the output under ~25 lines — this is a digest, not a full report.
SKILLEOF
$ openshell sandbox exec --name hermes-direct -- mkdir -p /sandbox/.hermes-data/skills/daily-issue-digest
$ openshell sandbox upload hermes-direct /tmp/SKILL.md /sandbox/.hermes-data/skills/daily-issue-digest/SKILL.md
$ # Then DM the agent: "Reload skills using nemoclaw_reload_skills"
````

After the manual upload, the demo resumes at **step 2** (verify on disk). Steps 3-9 are unchanged.
