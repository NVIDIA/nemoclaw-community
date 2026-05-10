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

## Access model

- The bot token is available as `openshell:resolve:env:SLACK_BOT_TOKEN`.
- Slack Web API access is allowed from the sandbox.
- The bot must be invited to a channel before it can read its history.

## Procedure

### 1. Resolve the channel ID

If the user gives a direct Slack mention like `<#C0ALN454EH4>`, use that ID
directly.

If the user gives only a channel name, use the bundled resolver script:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/slack-channel-summarizer/scripts/resolve_slack_channel.py --name 'CHANNEL_NAME'
```

Interpret the result this way:

- `ok: true`
  Use the returned `channel_id`.
- `missing_private_discovery_scope`
  Public lookup did not find the channel and private discovery by name is not
  available with this token. Ask the user for a direct Slack channel mention or
  a Slack channel URL.
- `channel_not_found`
  The channel could not be found through the allowed lookup path.

### 2. Read channel history

Use `conversations.history` with the resolved channel ID:

```bash
curl -s "https://api.slack.com/api/conversations.history?channel=CHANNEL_ID&limit=15" \
  -H "Authorization: Bearer openshell:resolve:env:SLACK_BOT_TOKEN"
```

If needed, add `oldest=` and `latest=` to constrain the time range.

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

## Pitfalls

- Do not use `session_search` to discover Slack channel IDs.
- Do not start discovery with `users.conversations?types=public_channel,private_channel`.
- Do not say Slack access is unavailable just because `groups:read` is missing.
  That only blocks private-channel discovery by name.
- If the channel ID is already known, skip discovery and go straight to
  `conversations.history`.
