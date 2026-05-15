---
title:
  page: "Set Up Slack with Hermes"
  nav: "Set Up Slack"
description:
  main: "Register a Slack app from the bundled manifest, enable Socket Mode, install to your workspace, and capture the bot/app tokens used by the personal-community-sentiment-triage example."
  agent: "Explains how Slack reaches the Hermes agent via Socket Mode (no public URL required). The Slack bot token (xoxb-) and app-level token (xapp-) are stored in OpenShell providers and resolved by the L7 proxy at request time. Slack is supported as both a messaging channel (DMs and @-mentions) and a read-only data source via skills (slack-channel-finder, slack-channel-summarizer, cross-source-gap-analysis). Use when configuring Slack integration for the agent."
keywords: ["nemoclaw slack", "slack bot hermes agent", "slack socket mode", "slack app manifest", "slack bolt"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "slack", "socket-mode", "deployment"]
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

# Set Up Slack

This guide walks through the one-time Slack app registration that this example needs: creating the app from the bundled manifest, enabling Socket Mode, installing it to your workspace, and capturing the two tokens. Once you have them, you populate `.env` and run `bash scripts/bring-up.sh` from the example root — see the [example README](../README.md) for the full bring-up flow.

The agent uses Slack via **Socket Mode** — there's no public URL or webhook to expose. The Slack Bolt SDK inside the sandbox opens an outbound WebSocket to Slack and receives events on it. The credential proxy resolves `SLACK_BOT_TOKEN` (the `xoxb-` token) and `SLACK_APP_TOKEN` (the `xapp-` token) at runtime; neither is baked into the image.

## Prerequisites

- A Slack workspace where you have permission to create apps. (For most workspaces this means workspace-admin or App Manager rights; check your workspace settings if you're unsure.)
- A dedicated user account in that workspace (yours is fine for personal use). Its **member ID** can become `SLACK_ALLOWED_IDS` if you want to restrict access; leave the variable empty to let anyone in the workspace message the bot.

## Create the Slack App from the Bundled Manifest

The manifest at [slack_app_manifest.json](slack_app_manifest.json) pre-configures the bot user, OAuth scopes, event subscriptions, and a slash command. You only need to customize three identifiers before pasting it into Slack.

### Edit the placeholder values

Open [slack_app_manifest.json](slack_app_manifest.json) in a text editor and replace these three placeholders with your own identifier (the slash command must be lowercase and hyphen-separated):

| Field | Placeholder | Example replacement |
|-------|-------------|---------------------|
| `display_information.name` | `MyUser NemoClaw` | `Alice NemoClaw` |
| `features.bot_user.display_name` | `MyUser NemoClaw` | `Alice NemoClaw` |
| `features.slash_commands[].command` | `/myuser-nemoclaw` | `/alice-nemoclaw` |

Note your slash command — that's what users will type in Slack.

The bot's `@`-handle in Slack is derived from `bot_user.display_name` (e.g. `Alice NemoClaw` → `@alice_nemoclaw`). Note your handle — other docs (like the [Collective Wisdom demo](collective-wisdom.md)) reference it as `@<your-bot>` and expect you to substitute your actual value.

### Register the app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**.
2. Choose **From an app manifest**.
3. Select your workspace, then click **Next**.
4. Paste your edited manifest JSON and click **Next**.
5. Review the requested permissions and click **Create**.

The manifest configures:

- **Socket Mode** — no public URL required.
- **Bot events**: `message.im`, `message.channels`, `message.mpim`, `app_mention`.
- **OAuth scopes** (bot): `im:history`, `im:read`, `im:write`, `app_mentions:read`, `channels:history`, `channels:read`, `chat:write`, `commands`, `reactions:write`, `users:read`, `mpim:history`, `mpim:read`, `im:write.topic`.
- **Slash command** — your custom `/<name>-nemoclaw`.

## Enable Socket Mode and Capture `SLACK_APP_TOKEN`

1. In your new app's settings, click **Socket Mode** in the left sidebar.
2. Toggle **Enable Socket Mode** on.
3. When prompted, name the app-level token (for example `nemoclaw-socket`) and click **Generate**.
4. Copy the token. It starts with `xapp-`.

Save it for the `.env` step below — this is `SLACK_APP_TOKEN`.

> If Slack behaves oddly on this step (toggle won't persist, generate prompt doesn't appear), toggle Socket Mode off and back on once.

## Install to Your Workspace and Capture `SLACK_BOT_TOKEN`

1. In the left sidebar, click **OAuth & Permissions**.
2. Click **Install to Workspace** and authorize.
3. Copy the **Bot User OAuth Token** at the top of the page. It starts with `xoxb-`.

Save it — this is `SLACK_BOT_TOKEN`.

## (Optional) Find Your Slack User ID for `SLACK_ALLOWED_IDS`

`SLACK_ALLOWED_IDS` is an optional allowlist. **Leaving it empty lets anyone in the workspace DM or @-mention the bot** — fine for personal workspaces and small trusted teams. Set it when you need to restrict access to specific users.

1. In the Slack desktop or web client, click your name or avatar.
2. Click **Profile**.
3. Click the **⋮** (more) menu, then **Copy member ID**.
4. The ID looks like `U0887Q5UVV4`.

To allow multiple users, comma-separate their IDs in `.env` (for example `U0887Q5UVV4,U1XYZABC123`).

## Populate `.env`

Open `.env` at the example root and uncomment / set the three Slack values:

```bash
SLACK_BOT_TOKEN=xoxb-<your bot token from OAuth & Permissions>
SLACK_APP_TOKEN=xapp-<your app-level token from Socket Mode>
# Optional — leave empty to allow anyone in the workspace
SLACK_ALLOWED_IDS=U0887Q5UVV4
```

Leaving `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` unset disables Slack entirely — the example runs Outlook-only. If you set the tokens, both `<sandbox>-slack-bridge` and `<sandbox>-slack-app` providers are upserted by [scripts/02-providers.sh](../scripts/02-providers.sh).

## Run `bring-up.sh`

From the example root:

```console
$ bash scripts/bring-up.sh
```

The script (auto-sources `.env` if needed) does the following for Slack:

- Creates OpenShell providers `<sandbox>-slack-bridge` (`SLACK_BOT_TOKEN`) and `<sandbox>-slack-app` (`SLACK_APP_TOKEN`).
- Bakes `slack` into the sandbox image's channel list (`NEMOCLAW_MESSAGING_CHANNELS_B64`) alongside `outlook`.
- Bakes `SLACK_ALLOWED_IDS` into the image's per-channel allowlist (`NEMOCLAW_MESSAGING_ALLOWED_IDS_B64`).
- Builds the sandbox image and launches it; the Hermes Slack channel opens its Socket Mode WebSocket on startup.

If you change Slack credentials after a sandbox already exists, run `bash scripts/tear-down.sh && bash scripts/bring-up.sh` so the providers and image are rebuilt with the new values.

## Confirm Delivery

After the sandbox is running, send a direct message to your bot in Slack from your allowlisted account. It should respond within a few seconds.

To inspect Hermes activity inside the sandbox:

```console
$ openshell sandbox connect hermes-direct
# Inside the sandbox:
$ tail -f /sandbox/.hermes/logs/hermes.log
```

If the bot does not respond, verify that:

- `openshell provider list` shows both `<sandbox>-slack-bridge` and `<sandbox>-slack-app`.
- If `SLACK_ALLOWED_IDS` is set, your Slack member ID matches one of its entries exactly (Slack IDs are case-sensitive and start with `U`). If it's empty, this check doesn't apply — anyone in the workspace can message the bot.
- The bot user is installed in your workspace (re-check **OAuth & Permissions** in your app's settings).
- Socket Mode is still enabled (re-check **Socket Mode** in your app's settings).

## Rotating Tokens

To rotate either token:

1. Generate a new one in the Slack app settings (Socket Mode → regenerate, or OAuth & Permissions → reinstall).
2. Update the matching value in `.env`.
3. Run `bash scripts/tear-down.sh && bash scripts/bring-up.sh` to refresh the OpenShell provider and rebuild the sandbox image.

The old token continues to work until the new one is fully deployed, so there's no downtime if you do this in order.
