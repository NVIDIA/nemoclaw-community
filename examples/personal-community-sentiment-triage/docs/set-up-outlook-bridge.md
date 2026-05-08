---
title:
  page: "Set Up Outlook with NemoClaw and Hermes"
  nav: "Set Up Outlook"
description:
  main: "Connect Microsoft Outlook to your sandboxed Hermes agent using a delegated OAuth2 token manager and credential sidecar that injects live Microsoft Graph API tokens without baking credentials into the Docker image."
  agent: "Explains how Outlook email reaches the sandboxed Hermes agent via a Python sidecar bridge (outlook-bridge.py) that polls the Microsoft Graph API, relays message bodies to the Hermes HTTP API, and sends replies. The credential sidecar (ms_graph_sidecar.py) injects delegated OAuth tokens obtained from the MS Graph token manager running on the host. Use when setting up Outlook email integration, scheduled email jobs, or any Microsoft Graph-based messaging workflow."
keywords: ["nemoclaw outlook", "outlook bridge hermes agent", "microsoft graph delegated auth", "msal token manager", "email agent nemoclaw"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "outlook", "microsoft-graph", "deployment", "nemoclaw", "delegated-auth", "msal"]
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

# Set Up Outlook

This guide walks through the one-time host setup that this example needs: registering an Azure application, running the MS Graph token manager, and obtaining a session UUID. Once those are done, you populate `.env` and run `bash scripts/bring-up.sh` from the example root — see the [example README](../README.md) for the full bring-up flow.

## How the agent account works

The agent account is a dedicated Entra mailbox that you treat like a chatbot endpoint reachable over email. You don't sign in to it day to day — it exists so the agent has its own inbox to receive requests on and its own outbox to reply from.

Interaction loop:

1. From your own mailbox, send an email to the agent account. Use the body to describe a task, ask a question, or paste content for the agent to act on.
2. The bridge picks the message up, passes the sender, subject, and body to the agent as a single prompt, and the agent processes the request. Up to 5 emails are handled concurrently; additional messages queue.
3. The agent replies in-thread to your original message via Microsoft Graph's reply API, so the response lands in your inbox as a `Re: <your subject>` reply. End-to-end latency is typically around 30 seconds.

The agent reads from and sends from this mailbox using **delegated** Microsoft Graph permissions — it acts as the agent account itself, not as an application with tenant-wide access. That's the security boundary: the agent can only access mailboxes it has been signed in to. The mechanics (token manager, credential sidecar, session UUID) are explained in the sections below.

The agent account address is what you'll set as `OUTLOOK_TARGET_MAILBOX`. A second, separate variable — `OUTLOOK_REPLY_TO` — points at *your own* mailbox and is used only by the `outlook-email-search` skill so the agent can read your mail on your behalf when researching. Both are summarized in the variable list further down.

The Outlook channel uses delegated OAuth2 authentication via the **MS Graph token manager**.
The token manager runs on the host machine and holds live MSAL sessions.
A credential sidecar (`ms_graph_sidecar.py`) runs inside the sandbox and injects a live delegated token whenever a bridge or skill sends `Authorization: Bearer MS_GRAPH_TOKEN_PLACEHOLDER_OUTLOOK` to `MS_GRAPH_SIDECAR_URL`.

Two mailboxes are involved:

- **`OUTLOOK_TARGET_MAILBOX`** — the agent's dedicated Entra account (for example `agt-you@nvidia.com`).
  The bridge polls this inbox for task requests and sends replies from it.
  This is also the account that signs in to the token manager.
- **`OUTLOOK_REPLY_TO`** — your personal mailbox (for example `you@nvidia.com`).
  Search skills use this address to read your mail via delegated `Mail.ReadWrite.Shared` access.

No credentials appear in the Docker image or environment files.
The session UUID (`OUTLOOK_SESSION_UUID`) is stored in an OpenShell provider and resolved by the L7 proxy at request time before reaching the token manager.

## Prerequisites

- A host that can run Docker and the OpenShell CLI (the same machine that will run `bash scripts/bring-up.sh`).
- An Azure Active Directory tenant with permission to register an application.
- An admin who can grant delegated Graph API permissions (or you have that permission yourself).
- A dedicated Entra account for the agent (for example `agt-you@nvidia.com`) — this becomes `OUTLOOK_TARGET_MAILBOX`.

## Register an Azure Application

1. Open [portal.azure.com](https://portal.azure.com) and navigate to **Azure Active Directory → App registrations → New registration**.
2. Give the app a name (for example `NemoClaw Hermes`), leave the redirect URI blank for now, and click **Register**.
3. On the **Overview** page, copy:
   - **Application (client) ID** → this is `OUTLOOK_CLIENT_ID`
   - **Directory (tenant) ID** → this is `OUTLOOK_TENANT_ID`
4. Navigate to **Authentication → Add a platform → Web**, enter `http://localhost:51247` as the redirect URI, and click **Configure**.
5. Navigate to **API permissions → Add a permission → Microsoft Graph → Delegated permissions** and add:
   - `Mail.Read`
   - `Mail.Send`
   - `Mail.ReadWrite.Shared`
6. Click **Grant admin consent for \<your org\>** and confirm.
   The permissions must show a green **Granted** status before the bridge can acquire tokens.

No client secret is required — the delegated flow authenticates as the agent account, not as the application.

## Populate `.env` (initial values)

Copy `.env.example` to `.env` at the example root and fill in everything you have so far. `OUTLOOK_SESSION_UUID` is the only value you don't have yet — leave it blank; the next step produces it.

```bash
OUTLOOK_CLIENT_ID=<application-client-id>
OUTLOOK_TENANT_ID=<directory-tenant-id>
OUTLOOK_SESSION_UUID=                       # filled in after authenticate.sh
OUTLOOK_TARGET_MAILBOX=agt-you@yourdomain.com
OUTLOOK_REPLY_TO=you@yourdomain.com
```

Optional comma-separated sender allowlist (the bridge ignores email from addresses not on this list):

```bash
OUTLOOK_ALLOWED_SENDERS=alice@example.com,bob@example.com
```

Leave `OUTLOOK_ALLOWED_SENDERS` unset or blank to accept email from any sender.

Now source `.env` into your current shell so the remaining steps (`authenticate.sh`, `bring-up.sh`) can resolve `$OUTLOOK_CLIENT_ID`, `$OUTLOOK_TENANT_ID`, and `$OUTLOOK_TARGET_MAILBOX`:

```console
$ set -a; . ./.env; set +a
```

`set -a` exports every variable assigned by `. ./.env`; `set +a` turns that behavior off again. Re-run this line whenever you edit `.env` (e.g. after pasting in `OUTLOOK_SESSION_UUID` below).

## Start the MS Graph Token Manager

The token manager is an MSAL OAuth server that holds delegated sessions and issues short-lived access tokens to the credential sidecar on demand.

The recommended way to start it is via the host-services bootstrap script, which also brings up the rest of the long-lived host stack (postgres, ETLs, phoenix):

```console
$ bash scripts/00-host-services.sh
```

If you only want the token manager (e.g., you're not using the source-etl-query skill), start it directly:

```console
$ cd extras/ms-graph-token-manager
$ docker compose up -d
```

It binds two ports:

| Port | Purpose |
|------|---------|
| `8765` | Token API — used by `authenticate.sh` and the credential sidecar |
| `51247` | OAuth redirect URI — receives the browser callback after sign-in |

Tokens are persisted in a named Docker volume and survive container restarts.
Re-authentication is only needed if the Entra refresh token expires (typically 90 days in corporate tenants) or if the agent account password changes.

## Authenticate and Obtain Session UUID

Run `authenticate.sh` as the **agent account** (`OUTLOOK_TARGET_MAILBOX`) to start the delegated auth flow and obtain a session UUID. The script prints `SESSION_ID=<uuid>` to stdout (everything else goes to stderr), so `eval` is the cleanest way to capture it into a shell variable:

```console
$ eval "$(./extras/ms-graph-token-manager/scripts/authenticate.sh \
    --client-id "$OUTLOOK_CLIENT_ID" \
    --tenant-id "$OUTLOOK_TENANT_ID" \
    --login-hint "$OUTLOOK_TARGET_MAILBOX" \
    --flow browser)"
$ echo "$SESSION_ID"   # bare UUID — paste into .env as OUTLOOK_SESSION_UUID
```

On a headless host, swap `--flow browser` for `--flow device`.

The session UUID is stored in the token manager and reused across restarts — re-run the script only when the session expires or is invalidated.

To check whether an existing session is still valid:

```console
$ ./extras/ms-graph-token-manager/scripts/authenticate.sh \
    --client-id "$OUTLOOK_CLIENT_ID" \
    --tenant-id "$OUTLOOK_TENANT_ID" \
    --session-id "$OUTLOOK_SESSION_UUID"
```

## Save the Session UUID to `.env`

Paste the `SESSION_ID` value from the previous step into `.env` as `OUTLOOK_SESSION_UUID`, then re-source so subsequent commands pick it up:

```console
$ set -a; . ./.env; set +a
```

## Run `bring-up.sh`

From the example root:

```console
$ bash scripts/bring-up.sh
```

The script (auto-sources `.env` if needed) does the following:

- Creates an OpenShell provider (`<sandbox>-outlook`) and upserts `OUTLOOK_CLIENT_ID`, `OUTLOOK_TENANT_ID`, and `OUTLOOK_SESSION_UUID` onto it.
- Bakes `outlook` into the sandbox image's channel list (`NEMOCLAW_MESSAGING_CHANNELS_B64`).
- Bakes the allowed-senders list into the image as `OUTLOOK_ALLOWED_SENDERS`.
- Sets `OUTLOOK_TARGET_MAILBOX` and `OUTLOOK_REPLY_TO` in the sandbox environment.
- Builds the sandbox image and attaches it to the example gateway.

The bridge and credential sidecar start automatically once the Hermes gateway is healthy.
Logs are written to `/tmp/outlook-bridge.log` inside the sandbox.

If you change credentials after a sandbox already exists, run `bash scripts/tear-down.sh && bash scripts/bring-up.sh` so the image and provider attachments are rebuilt.

## Confirm Delivery

After the sandbox is running, send an email to `OUTLOOK_TARGET_MAILBOX` from an allowed address.
Within approximately 30 seconds a reply from the agent should arrive in your inbox.

To inspect bridge activity inside the sandbox:

```console
$ openshell term
# Inside the sandbox:
$ tail -f /tmp/outlook-bridge.log
```

If the bridge does not start, verify that:

- `openshell sandbox policy` shows `graph.microsoft.com` and `login.microsoftonline.com` as allowed.
- The Azure app has **Granted** delegated permissions (not Application).
- `openshell provider list` shows `<sandbox>-outlook` with `OUTLOOK_CLIENT_ID`, `OUTLOOK_TENANT_ID`, and `OUTLOOK_SESSION_UUID`.
- The MS Graph token manager is running on the host and reachable at `TOKEN_MANAGER_HOST:8765`.

## Renewing the Session

Entra refresh tokens typically expire after 90 days of inactivity in corporate tenants, or immediately if the agent account password changes or the app registration is modified.
When the session expires, the credential sidecar will log token fetch errors.

To renew:

1. Re-run `authenticate.sh` as the agent account — if the existing session is invalid it starts a new auth flow automatically.
2. Update `OUTLOOK_SESSION_UUID` in `.env` with the new value, then run `bash scripts/tear-down.sh && bash scripts/bring-up.sh` to refresh the OpenShell provider and rebuild the sandbox image.

## Scheduled Jobs

The bridge reads `/sandbox/.hermes-data/cron/outlook-jobs.json` at startup and schedules each entry using the `schedule` library.

### Job schema

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable label for logs |
| `time` | string | 24-hour `HH:MM` time to run daily |
| `prompt` | string | Prompt sent to the agent |
| `to` | string | Recipient email address for the result |
| `subject` | string | Email subject line |

### Example

```json
[
  {
    "name": "morning-report",
    "time": "10:00",
    "prompt": "Summarize the top AI research news from the past 24 hours.",
    "to": "team@example.com",
    "subject": "Daily AI Summary"
  }
]
```

Edit the file, then restart the bridge to pick up changes:

```console
$ openshell term
# Inside the sandbox:
$ kill $(pgrep -f outlook-bridge.py)
# The bridge does not restart automatically — restart the sandbox to reload jobs.
```

Alternatively, run `bash scripts/tear-down.sh && bash scripts/bring-up.sh` to rebuild the sandbox with a fresh job schedule.
