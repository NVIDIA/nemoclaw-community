---
name: slack-channel-summarizer
description: Read and summarize Slack channel history from inside the NemoClaw sandbox.
---

# slack-channel-summarizer

Use this skill to resolve a Slack channel and produce a summary that is bounded
to retrieved history and linked to source messages.

## When to use

- Summarize recent activity in a channel.
- Review conversation history for a time range.
- Check what was discussed in a channel before answering a question.

## Instructions

- Use the provided Python helpers. Do not use direct `curl` requests or create
  another Slack client.
- `SLACK_BOT_TOKEN` contains a placeholder that OpenShell resolves on egress.
- Do not print the access token or include it in a command argument.
- Summarize only messages returned by `fetch_slack_history.py`.

## Procedure

### 1. Resolve the channel ID

If the user gives a direct Slack mention like `<#C0ALN454EH4>`, use that ID
directly.

If the request comes from a tagged Slack channel and the runtime context already
gives you the current channel ID, treat that as the resolved channel ID for
phrases like "this channel".

Otherwise, use your Slack channel finder skill.

### 2. Read bounded channel history

For a recent-message request, run:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/slack-channel-summarizer/scripts/fetch_slack_history.py \
  --channel-id CHANNEL_ID --message-limit 10 --page-cap 10
```

For a time range, pass inclusive `--oldest` and `--latest` boundaries as Slack
timestamps or ISO 8601 timestamps. For example:

```bash
oldest="$(date -u -d '7 days ago' +%s)"
latest="$(date -u +%s)"
/usr/bin/python3 /sandbox/.hermes-data/skills/slack-channel-summarizer/scripts/fetch_slack_history.py \
  --channel-id CHANNEL_ID \
  --oldest "$oldest" --latest "$latest" \
  --message-limit 100 --page-cap 10 \
  --replies --thread-cap 10 --reply-limit 20 --thread-page-cap 3
```

The helper filters bot and system messages while it paginates. The limits and
page caps bound the amount of channel and thread history that it returns. The
hard maxima are 200 human channel messages, 25 history pages, 10 thread roots,
20 human replies per thread, and 5 pages per thread.

### 3. Check the evidence contract

Read these fields before you summarize:

- `ok`: required history and source links were retrieved.
- `empty`: the completed query returned no matching human messages.
- `coverage.requested_range`: boundaries sent to Slack.
- `coverage.retrieved_range`: oldest and latest messages inspected.
- `coverage.inspected_messages`, `coverage.human_messages`, and
  `coverage.pages`: the amount of history processed.
- `coverage.complete` and `coverage.truncation_reasons`: whether the history
  query reached its boundary without hitting a cap.
- `threads.complete` and `threads.truncation_reasons`: whether requested thread
  expansion reached its bounds.
- `messages[].timestamp`, `messages[].permalink`, and `messages[].citation`:
  source metadata for each message.
- `messages[].text_truncated`: whether the helper capped that message's text.
- `messages[].thread_replies[]`: bounded replies. Each reply includes
  `thread_root_ts` so that its relationship to the root is explicit.

Do not summarize when `ok` is `false`. Report the returned `stage`, `error`, and
actionable fields instead. Common errors include:

- `invalid_auth`: check the configured bot access token.
- `not_in_channel`: invite the bot to the channel.
- `missing_scope`: add the scope named in `needed`, then reinstall the app.
- `rate_limited`: wait for the returned `retry_after` interval.
- `channel_not_found`: check the channel ID and the bot's access.

An `ok: true` result with `empty: true` and `coverage.complete: true` means that
the requested range contains no matching human messages. If
`coverage.complete` is false, disclose the truncation reasons. Do not describe
an incomplete empty result as no channel activity.

### 4. Write the grounded summary

Start with a short coverage statement that gives the requested range, retrieved
range, number of messages inspected, number of human messages used, and any
history or thread truncation.

Use only retrieved message text for these sections:

- Main topics
- Active participants
- Decisions and action items
- Unresolved questions

Copy the `citation` value at the end of every factual bullet about a theme,
decision, action item, or unresolved question. Cite more than one representative
message when a conclusion combines several messages. A citation is a Slack
permalink and preserves the workspace's existing access controls.

If there is not enough retrieved evidence for a requested conclusion, say that
the retrieved messages do not establish it. Do not add general patterns,
background assumptions, or conclusions from channel metadata alone.
