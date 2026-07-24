---
name: slack-channel-summarizer
description: Read and summarize Slack channel history from inside the NemoClaw sandbox.
---

# slack-channel-summarizer

Use this skill to resolve a Slack channel and read its history.

## When to use

- Summarize recent activity in a channel
- Review conversation history for a time range
- Check what was discussed in a channel before answering a question

## Instructions

- The best way to access slack given the sandbox is through the provided python scripts.
- Direct curl requests, or Python scripts, are unlikely to succeed
- The SLACK_BOT_TOKEN contains a placeholder env var that is resolved by the sandbox on egress
- Only refer to helper scripts that actually exist in this sandbox image


## Procedure

### 1. Resolve the channel ID

If the user gives a direct Slack mention like `<#C0ALN454EH4>`, use that ID
directly.

If the request comes from a tagged Slack channel and the runtime context already
gives you the current channel ID, treat that as the resolved channel ID for
phrases like "this channel".

Otherwise, use your slack channel finder skill.

### 2. Read channel history

Use the existing channel-description helper with the resolved channel ID. It
includes recent human messages and channel metadata that are sufficient for a
summary:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/slack-channel-finder/scripts/describe_slack_channel.py \
  --channel-id CHANNEL_ID --history-limit 15
```

Useful variants:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/slack-channel-finder/scripts/describe_slack_channel.py \
  --channel-id CHANNEL_ID --history-limit 30 --replies
```

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/slack-channel-finder/scripts/describe_slack_channel.py \
  --channel-id CHANNEL_ID --history-limit 15 --resolve-users
```

Interpret common failures explicitly:

- `not_in_channel`
  The bot is not a member of that channel.
- `missing_scope` with `needed=channels:history`
  The bot cannot read public-channel history.
- `missing_scope` with `needed=groups:history`
  The bot cannot read private-channel history.
- `channel_not_found`
  The ID is wrong or unavailable to the token.

### 3. Summarize

Summarize only what the user asked for. Good defaults are:

- time range covered
- main topics
- active participants
- decisions or action items
