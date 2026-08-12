---
name: slack-channel-finder
description: Discover Slack channels by topic, team, or domain and determine the channel ID.
---

# slack-channel-finder

Use this skill to discover Slack channels ID by name or topic

## When to use

Do NOT use this skill when the user has already provided a slack channel ID 

## Instructions

- Because of the sandbox, the best path is to use the provided helper scripts
- Avoid writing custom curl or python commands
- Only customize if the existing scrips fail, and in that case follow their 
authorization patterns closely
- Be aware that slack access is through a Slack bot, whose token might have certain
scopes or might be missing scopes


## Scripts

Check for scripts at:
```
/sandbox/.hermes-data/skills/slack-channel-finder/scripts/
```

or at 

```
/sandbox/.hermes/skills/slack-channel-finder/scripts
```


| Script | Purpose |
|--------|---------|
| `find_channel.py` | Search and rank channels by query across the workspace |
| `list_accessible_channels.py` | List channels (bot-member or workspace-wide) |
| `describe_slack_channel.py` | Deep-describe a single channel with layered signals |

## Procedure


### 1. Distinguish summary requests from discovery requests

- If the user is asking to summarize or inspect a specific Slack channel, and
  they likely know the channel already but did not provide the exact name or
  ID, ask them for the channel name.
- If the user is asking you to help find which Slack channel is relevant to a
  topic, team, or project, use the discovery flow below instead of asking for a
  channel name first.

### 2. If you are given a channel name, start with `list_accessible_channels.py` and try to match channel name to ID

/usr/bin/python3 .../list_accessible_channels.py


### 3. If you are unclear on what channel the user is talking about, ask them for the channel name

### 4. If the user wants help finding a channel, attempt to find one based on the user's topic or query

For topic or team queries, use `find_channel.py` — it searches all discoverable
public channels (not just bot-member channels) and returns scored matches:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/slack-channel-finder/scripts/find_channel.py \
  --query "nemoclaw inference" --top 5
```

Output:
```json
{
  "ok": true,
  "query": "nemoclaw inference",
  "query_tokens": ["nemoclaw", "inference"],
  "total_searched": 78,
  "count": 2,
  "discovery_mode": "workspace",
  "results": [
    {
      "channel_id": "C0ASZUN3L5D",
      "name": "lopp-nemoclaw-staging",
      "is_member": true,
      "num_members": 8,
      "topic": "",
      "purpose": "This is a channel to discuss NemoClaw technical updates...",
      "score": 9,
      "match_reasons": ["name:nemoclaw", "purpose:nemoclaw"]
    }
  ]
}
```

Scoring weights: name token match = 3 pts, purpose match = 2 pts, topic match = 1 pt.

The `is_member` flag tells you whether the bot is in the channel — full history
and thread signals are available only for member channels.

**Options:**

| Flag | Description |
|------|-------------|
| `--query TEXT` | Required. Matched against name, topic, purpose. |
| `--top N` | Max results (default 5) |
| `--member-only` | Restrict to bot-member channels only |
| `--min-score N` | Minimum score to include (default 1) |

## Information on other scripts

###  List all channels (when you need the full inventory)

For cases where you need the complete channel list rather than a scored search:

```bash
# Bot-member channels only (fast)
/usr/bin/python3 .../list_accessible_channels.py

# All public channels in the workspace
/usr/bin/python3 .../list_accessible_channels.py --all-public
```

Output: `{ "ok": true, "count": N, "channels": [...], "discovery_mode": "workspace" }`

Each channel: `{id, name, is_archived, is_private, is_member, num_members, topic, purpose, created}`

For `--all-public`, `is_member=false` channels exist in the workspace but the bot
hasn't been added — you can see name/topic/purpose but NOT read their history.

**Options:**

| Flag | Description |
|------|-------------|
| `--all-public` | Use `conversations.list` for workspace-wide discovery |
| `--include-archived` | Include archived channels |
| `--types TYPES` | Comma-separated types (default `public_channel`) |

### Describe a channel in depth

When you need to understand a specific channel — what it's for, who's active, what
they're discussing — use `describe_slack_channel.py`:

```bash
# Full mode (name + topic + purpose + pins + bookmarks + recent history)
/usr/bin/python3 .../describe_slack_channel.py --channel-id C0ASZUN3L5D

# Fast mode (skips conversations.history — useful for breadth scans)
/usr/bin/python3 .../describe_slack_channel.py --channel-id C0ASZUN3L5D --no-history

# With thread content (expands reply threads for high-activity messages)
/usr/bin/python3 .../describe_slack_channel.py --channel-id C0ASZUN3L5D --replies

# With resolved user display names on top contributors
/usr/bin/python3 .../describe_slack_channel.py --channel-id C0ASZUN3L5D --resolve-users
```

**Options:**

| Flag | Description |
|------|-------------|
| `--channel-id ID` | Required. Slack channel ID (e.g. C0ASZUN3L5D) |
| `--history-limit N` | Max messages to fetch (default 50) |
| `--no-history` | Skip conversations.history (faster, cheaper) |
| `--no-pins` | Skip pins.list |
| `--no-bookmarks` | Skip bookmarks.list |
| `--replies` | Fetch first few replies for threaded messages (reply_count > 0) |
| `--replies-limit N` | Max replies per thread when --replies is set (default 5) |
| `--resolve-users` | Resolve contributor user IDs to display names via users.info |

Output structure:
```json
{
  "ok": true,
  "channel_id": "C0ASZUN3L5D",
  "name": "lopp-nemoclaw-staging",
  "is_archived": false,
  "is_private": false,
  "num_members": 8,
  "signals": {
    "name_tokens": ["lopp", "nemoclaw", "staging"],
    "topic": "",
    "topic_stale": true,
    "purpose": "This is a channel to discuss NemoClaw...",
    "pinned_messages": [],
    "bookmarks": [],
    "recent_human_messages": [
      {
        "user": "UR0A4QL5N",
        "text": "<@U0AUN68FSNT> tell me a joke",
        "ts": "1777589708.784719",
        "thread_ts": "1777589708.784719",
        "reply_count": 2,
        "thread_messages": [...]
      }
    ],
    "top_contributors": [
      {"user_id": "U0887Q5UVV4", "message_count": 13, "display_name": "Scott Lopp"}
    ],
    "human_message_count": 22
  },
  "confidence": "medium"
}
```

The script does NOT produce a natural-language description. Synthesize one from
the `signals` dict, weighting in this order:

1. Pinned messages (often a charter or intro)
2. Channel name tokens
3. Topic and purpose (if not stale)
4. Bookmarks
5. Recent human message themes
6. Top contributors

The `confidence` field (`high`, `medium`, `low`) reflects how many independent
signals were available. For `low`-confidence channels, hedge ("appears to be
about ...") or ask the user to confirm.


## Other 

###  Read thread content

When a message has a high `reply_count` and you need the actual discussion
content, use `--replies` on `describe_slack_channel.py` or directly call
`conversations.replies`:

```bash
# Via describe (expands all threads in the sampled history)
/usr/bin/python3 .../describe_slack_channel.py --channel-id [channel-id] --replies --replies-limit [n]
```


### Chain into summarization if requested

If the user's goal goes beyond discovery ("tell me what the X team is working
on"), once channels are identified, hand off to `slack-channel-summarizer`
for each top channel. Cap at 5 channels per query; surface the ranking so the
user can ask for more.

## Common patterns

**Find channels matching a topic:**
```bash
/usr/bin/python3 .../find_channel.py --query "nemoclaw deployments"
```

**See all public channels in the workspace:**
```bash
/usr/bin/python3 .../list_accessible_channels.py --all-public
```

**Understand a specific channel (fast, no history):**
```bash
/usr/bin/python3 .../describe_slack_channel.py --channel-id C0ASZUN3L5D --no-history
```

**Understand a channel with thread context and user names:**
```bash
/usr/bin/python3 .../describe_slack_channel.py --channel-id C0ASZUN3L5D --replies --resolve-users
```

