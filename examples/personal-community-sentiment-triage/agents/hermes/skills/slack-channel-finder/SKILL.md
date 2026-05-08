---
name: slack-channel-finder
description: Discover Slack channels by topic, team, or domain and infer what each channel is for. Use when the user wants to find which channels are relevant to a topic ("which channels does the inference team use", "where do we discuss deployments") or to understand what an unfamiliar channel is for. Pairs with slack-channel-summarizer for follow-up reads.
---

# slack-channel-finder

Use this skill to discover Slack channels matching a topic, team, or domain,
and to infer what each channel is for.

## When to use

- "Which channels does the X team use?"
- "Find me Slack channels about Y"
- "Where do we discuss Z?"
- "What is #cryptic-channel-name for?"
- The user wants to discover channels they don't already know by name
- The user wants to understand an unfamiliar channel before reading history

Do NOT use this skill when the user has already named a specific channel and
just wants its history summarized — use slack-channel-summarizer instead.

## Access model

- The bot token is available as `openshell:resolve:env:SLACK_BOT_TOKEN`.
- **Confirmed granted scopes**: `channels:history`, `channels:read`, `users:read`,
  `app_mentions:read`, `chat:write`, `reactions:write`
- **Scopes not in this token**: `pins:read`, `bookmarks:read`, `groups:read`
  - `pins.list` and `bookmarks.list` will return `missing_scope`; the scripts
    handle this gracefully and return empty lists — treat as normal
  - Private channels (`groups:read`) are not accessible; discovery is
    public-only
- **Two discovery modes**:
  - `users.conversations` — channels the bot is a **member** of (fast, restricted)
  - `conversations.list` — **all public** channels in the workspace (broader, used
    by `find_channel.py` and `list_accessible_channels.py --all-public`)
- History, thread replies, and user info all work with the current token.
- `search.messages` requires a user token (not a bot token) — not available.

## Scripts

All scripts are at:
```
/sandbox/.hermes-data/skills/slack-channel-finder/scripts/
```

| Script | Purpose |
|--------|---------|
| `find_channel.py` | Search and rank channels by query across the workspace |
| `list_accessible_channels.py` | List channels (bot-member or workspace-wide) |
| `describe_slack_channel.py` | Deep-describe a single channel with layered signals |

## Procedure

### 1. Search for candidate channels

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

### 2. List all channels (when you need the full inventory)

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

### 3. Describe a channel in depth

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

### 4. Read thread content

When a message has a high `reply_count` and you need the actual discussion
content, use `--replies` on `describe_slack_channel.py` or directly call
`conversations.replies`:

```bash
# Via describe (expands all threads in the sampled history)
/usr/bin/python3 .../describe_slack_channel.py --channel-id C0ASZUN3L5D --replies --replies-limit 10

# Direct API (for a specific thread you already know the ts for)
curl -s "https://slack.com/api/conversations.replies?channel=C0ASZUN3L5D&ts=1776809496.989829&limit=20" \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" | /usr/bin/python3 -m json.tool
```

### 5. Chain into summarization if requested

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

## Pitfalls

- Do not claim a channel doesn't exist when the bot simply hasn't been invited.
  `find_channel.py` searches all public channels via `conversations.list`; for
  channels that show up there with `is_member=false`, note that history is
  unavailable without the bot being added.
- Do not rely solely on `topic` and `purpose` — many channels leave them empty
  or stale. Channel name and message themes are usually stronger signals.
- Do not return archived channels unless the user explicitly asks for them.
- Do not invent channel IDs, names, or descriptions. Only return what the API
  actually returned.
- `pins.list` and `bookmarks.list` require `pins:read` and `bookmarks:read`
  scopes respectively. If the token lacks them, the scripts return empty lists —
  this is handled gracefully and is not an error to surface to the user.
- Do not run `describe_slack_channel.py` in full mode across many channels.
  Use `--no-history` for breadth scans, full mode for the final 1-3 candidates.
- Bot messages (GitHub, CI integrations) dominate volume in engineering channels
  and carry no topic signal. `describe_slack_channel.py` filters them
  automatically — `recent_human_messages` contains only real human posts.
- `search.messages` requires a user token, not the bot token. Do not attempt it.
- The API will 429 (rate limit) under heavy load. All scripts automatically
  retry with the `Retry-After` backoff — do not add extra delays.
