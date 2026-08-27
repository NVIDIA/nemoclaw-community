<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Slack App Setup

Create the Slack app from
[`../../../config/slack-app-manifest.yml`](../../../config/slack-app-manifest.yml).
The manifest declares Socket Mode, direct-message events, and the bot scopes
used by this recipe.

## Create and install

1. Open <https://api.slack.com/apps>.
2. Select **Create New App**, then **From a manifest**.
3. Select the workspace and paste the recipe manifest.
4. Under **Basic Information**, create an app-level token with
   `connections:write`. Save its `xapp-` value as `SLACK_APP_TOKEN`.
5. Under **OAuth & Permissions**, install the app. Save the `xoxb-` bot token
   as `SLACK_BOT_TOKEN`.

A managed workspace can require administrator approval. Complete that approval
before running onboarding.

Direct messages do not require inviting the bot to a channel. A channel is
optional; invite the bot before expecting it to receive channel mentions.

## Why the manifest settings matter

- `chat:write` permits replies.
- `im:history`, `im:read`, and `im:write` enable direct messages.
- `app_mentions:read` and channel-history scopes enable optional channel use.
- `messages_tab_enabled: true` with
  `messages_tab_read_only_enabled: false` enables the DM composer.
- Socket Mode creates an outbound connection and needs no public request URL.

## Validate tokens

From the host that will run NemoClaw:

```bash
bash scripts/check-slack-tokens.sh
```

For optional channel use:

```bash
bash scripts/check-slack-tokens.sh --channel <CHANNEL_ID>
```

For a shared workspace, set `SLACK_ALLOWED_USERS` in `.env` before onboarding.
If the allowlist is empty and OpenClaw issues a pairing code, approve a known
sender with:

```bash
bash scripts/slack-pair.sh approve <code>
```

Do not run `slack-pair.sh watch --yes` as a persistent service; that mode
approves every request it observes during the selected window.
