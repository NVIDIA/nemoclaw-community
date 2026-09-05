---
title:
  page: "Set Up Slack with Hermes"
  nav: "Set Up Slack"
description:
  main: "Register a Slack app from the bundled manifest, enable Socket Mode, install to your workspace, and capture the bot/app tokens used by the developer-community-chief-of-staff example."
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
3. When prompted, name the app-level token (for example `nemoclaw-socket`).
4. Add the app-level scope
   **[`connections:write`](https://docs.slack.dev/reference/scopes/connections.write/)**.
   Slack requires this scope for
   [`apps.connections.open`](https://api.slack.com/methods/apps.connections.open)
   to generate the Socket Mode WebSocket URL.
5. Click **Generate**, then copy the token. It starts with `xapp-`.

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
# Optional — set false for text-only output
NEMOCLAW_SLACK_RICH_BLOCKS=true
```

Leaving `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` unset disables Slack entirely — the example runs Outlook-only. If you set the tokens, a single `<sandbox>-slack` provider is upserted by [scripts/02-providers.sh](../scripts/02-providers.sh) with both credentials attached.

Hermes renders supported semantic Markdown with Slack Block Kit by default,
including native table blocks. Set `NEMOCLAW_SLACK_RICH_BLOCKS=false` for
text-only output. The setting accepts only `true` or `false`. Every message
keeps a text fallback for notifications, accessibility, old clients, and
renderer failure.

Hermes also renders two to four clarification choices as one-tap buttons plus
an `Other` option through its native Slack adapter. Rich Blocks and buttons use
the existing Slack credentials and require no additional OAuth scopes or app
reinstall. Rebuild the sandbox after changing the Rich Blocks setting.

## Run `bring-up.sh`

From the example root:

```console
$ bash scripts/bring-up.sh
```

The script (auto-sources `.env` if needed) does the following for Slack:

- Calls `apps.connections.open` with a bounded request to verify that the app
  token is valid, has `connections:write`, and can create a Socket Mode URL.
  Setup stops before provider and sandbox creation when this check fails.
- Creates an OpenShell provider `<sandbox>-slack` with both `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` credentials (one v2 provider, two credentials).
- Bakes `slack` into the sandbox image's channel list (`NEMOCLAW_MESSAGING_CHANNELS_B64`) alongside `outlook`.
- Injects `SLACK_ALLOWED_IDS` as the gateway's `SLACK_ALLOWED_USERS` at sandbox-create time (runtime `-- env`, not baked into the image). An empty allowlist sets `SLACK_ALLOW_ALL_USERS=true` so any workspace user can DM the bot.
- Builds the sandbox image and launches it; the Hermes Slack channel opens its Socket Mode WebSocket on startup.

If you change Slack credentials after a sandbox already exists, run `bash scripts/tear-down.sh && bash scripts/bring-up.sh` so the providers and image are rebuilt with the new values.

## Verify End-to-End Delivery

The setup preflight calls `apps.connections.open`. That check proves that the
app-level token can reach Slack and create a Socket Mode URL. It does not prove
that Slack can deliver an event to the running Hermes gateway.

After the sandbox is running, start the guided direct-message diagnostic from
the example root:

```console
$ python3 scripts/slack_delivery_diagnostic.py --mode dm
```

The command prints a unique test value and asks you to send one direct message
to the bot. It does not send a message as you. The delivery wait is 90 seconds
by default, and the command reports the last confirmed stage:

| Stage | What it confirms |
| --- | --- |
| Slack API access | The bot access token can call `auth.test`. |
| Socket Mode connection | The running Hermes process completed a Socket Mode connection. |
| Inbound event receipt | The adapter received the test event from Slack. |
| Hermes dispatch | The event passed adapter filtering and entered the Hermes message path. |
| Inference | The Hermes message handler completed without an exception. |
| Outbound response | The Slack adapter confirmed a send. |

When `SLACK_ALLOWED_IDS` contains members, send the direct message from an
allowlisted member. When the value is empty, the documented allow-all mode is
supported. The command reports the authorization mode and member count, but it
does not print member IDs.

To verify the custom slash command from your app manifest, run a separate test.
Replace the command name with the value that you configured:

```console
$ python3 scripts/slack_delivery_diagnostic.py \
    --mode slash --slash-command /alice-nemoclaw
```

Then run the printed slash command in Slack. The recipe's custom-command hook
forwards only a message that contains the generated diagnostic value through
the normal Hermes inference path. Other unknown slash commands keep their
existing help response.

The sandbox records only the diagnostic value, stage, status, timestamp,
process ID, and exception class in a mode-0600 bounded log. It does not record
the message body, Slack credentials, workspace name, or unrelated history. The
diagnostic uses the existing Slack permissions. It does not restart the gateway
or rebuild the sandbox. Use `--timeout <seconds>` to change the bounded wait.

Rebuild the sandbox before the first diagnostic after you update this recipe.
The sandbox image contains the stage instrumentation and the sandbox-side
reader.

The optional response monitor serves a different purpose. It detects some
unanswered direct messages after delivery and can request host-side recovery.
It does not prove the slash-command path or identify the last completed stage.

## Manual Inspection

You can also send a direct message to the bot from an allowlisted account. It
should respond within a few seconds.

To inspect Hermes activity inside the sandbox:

```console
$ openshell sandbox connect hermes-direct
# Inside the sandbox:
$ tail -f /sandbox/.hermes/logs/hermes.log
```

If the bot does not respond, verify that:

- `openshell provider list` shows `<sandbox>-slack` with both `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in its credential keys.
- If `SLACK_ALLOWED_IDS` is set, your Slack member ID matches one of its entries exactly (Slack IDs are case-sensitive and start with `U`). If it's empty, this check doesn't apply — anyone in the workspace can message the bot.
- The bot user is installed in your workspace (re-check **OAuth & Permissions** in your app's settings).
- Socket Mode is still enabled (re-check **Socket Mode** in your app's settings).

## Rotating Tokens

To rotate either token:

1. Generate a new one in the Slack app settings (Socket Mode → regenerate, or OAuth & Permissions → reinstall).
2. Update the matching value in `.env`.
3. Run `bash scripts/tear-down.sh && bash scripts/bring-up.sh` to refresh the OpenShell provider and rebuild the sandbox image.

The old token continues to work until the new one is fully deployed, so there's no downtime if you do this in order.
