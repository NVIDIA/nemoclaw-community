---
title:
  page: "Set Up Outlook with NemoClaw and Hermes"
  nav: "Set Up Outlook"
description:
  main: "Connect Microsoft Outlook to your sandboxed Hermes agent using OpenShell provider v2 gateway-managed OAuth refresh-token rotation."
  agent: "Explains how Outlook email reaches the sandboxed Hermes agent: outlook-bridge.py polls Microsoft Graph using `Authorization: Bearer openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN`, which the OpenShell L7 proxy substitutes with a live access token. The token is minted by the OpenShell gateway from a stored OAuth refresh token (registered once via `openshell provider refresh configure`). Use when setting up Outlook email integration or any Microsoft Graph-based messaging workflow."
keywords: ["nemoclaw outlook", "outlook bridge hermes agent", "microsoft graph delegated auth", "openshell provider v2", "oauth2 refresh token"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "outlook", "microsoft-graph", "deployment", "nemoclaw", "provider-v2"]
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

# Set Up Outlook

One-time host setup: register an Azure application, ensure provider v2 is enabled on the OpenShell gateway, populate `.env`, then run `bash scripts/bring-up.sh` from the example root. The first bring-up runs an interactive Microsoft device-code login and registers the refresh token with the gateway. See the [example README](../README.md) for the full bring-up flow.

## How the agent account works

The agent account is a dedicated Entra mailbox that you treat like a chatbot endpoint reachable over email. You don't sign in to it day to day — it exists so the agent has its own inbox to receive requests on and its own outbox to reply from.

1. From your own mailbox, send an email to the agent account.
2. The bridge picks the message up, passes the sender, subject, and body to the agent as a single prompt. Up to 5 emails handle concurrently.
3. The agent replies in-thread via Microsoft Graph's reply API. End-to-end latency is typically ~30 seconds.

The agent uses **delegated** Microsoft Graph permissions — it acts as the agent account itself, not as an application with tenant-wide access. The gateway holds the refresh token; the sandbox sees only the OpenShell placeholder `openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN`, which the L7 proxy substitutes at egress.

`OUTLOOK_TARGET_MAILBOX` is the agent account address; `OUTLOOK_REPLY_TO` is your own mailbox (used by `outlook-email-search` so the agent can read your mail when researching). Both are documented in [`.env.example`](../.env.example).

## Prerequisites

- An Entra (Azure AD) tenant where you can register an application.
- A dedicated mailbox for the agent (e.g. `agt-you@yourcompany.com`).
- OpenShell ≥ `v0.0.50` with `providers_v2_enabled = true` at gateway scope:

```console
$ openshell settings set --global --key providers_v2_enabled --value true --yes
```

## 1. Register the Entra application

In the Entra portal, create a new application registration:

- **Supported account types**: single-tenant (or whatever your org policy mandates).
- **Redirect URIs**: leave empty — device-code flow doesn't need one.
- **Authentication → Allow public client flows**: **Yes** (required for device code).
- **API permissions → Microsoft Graph → Delegated permissions**: add at minimum
  - `Mail.Read`
  - `Mail.Send`
  - `Mail.ReadWrite.Shared` (only if you want the agent to read another user's mailbox via delegate access)
  - `offline_access` (required to receive a refresh token)
- **Grant admin consent** for the tenant.

Note the **Application (client) ID** → `OUTLOOK_CLIENT_ID` and the **Directory (tenant) ID** → `OUTLOOK_TENANT_ID`.

## 2. Populate `.env`

```dotenv
OUTLOOK_TENANT_ID=<directory-tenant-id>
OUTLOOK_CLIENT_ID=<application-client-id>
OUTLOOK_TARGET_MAILBOX=agt-you@yourcompany.com
OUTLOOK_REPLY_TO=you@yourcompany.com
# OUTLOOK_ALLOWED_SENDERS=you@yourcompany.com,trusted-colleague@partner.com  # optional
```

## 3. Run the first bring-up

```console
$ bash scripts/bring-up.sh
```

When `02-providers.sh` reaches the Outlook block, it invokes [`scripts/login-ms-graph.py`](../scripts/login-ms-graph.py), which prints:

```
Microsoft Graph device login
To sign in, use a web browser to open the page https://microsoft.com/devicelogin
and enter the code ABCD1234 to authenticate.
```

Open that URL in a browser, sign in **as the agent account** (`OUTLOOK_TARGET_MAILBOX`), and enter the code. The script captures the refresh token and registers it with the gateway via `openshell provider refresh configure`. The token is cached at `.bootstrap/cache/ms-graph-token.json` (mode 0600; ignored by `.gitignore`) so subsequent bring-ups reuse it. Set `OUTLOOK_LOGIN_CACHE=0` to skip the on-disk cache entirely — see the security note below.

After this, the gateway auto-rotates the access token in the background. The sandbox bridge and skills call `https://graph.microsoft.com` directly with the placeholder header; the L7 proxy substitutes a live token on egress.

## 4. Verify

```console
$ openshell provider refresh status hermes-direct-outlook --credential-key MS_GRAPH_ACCESS_TOKEN
$ openshell sandbox exec --name hermes-direct -- \
    curl -sS -H "Authorization: Bearer openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN" \
      'https://graph.microsoft.com/v1.0/me' | head -c 300
```

The `/me` call should return the agent account's profile JSON.

## Renewing an expired refresh token

Microsoft caps unattended refresh-token lifetime around 90 days; the gateway rotates the refresh token transparently before then. If it does expire or gets revoked, re-authenticate by forcing a fresh device-code login:

```console
$ OUTLOOK_LOGIN_CACHE=2 bash scripts/bring-up.sh
```

This ignores the cached token at `.bootstrap/cache/ms-graph-token.json`, prompts you to re-authenticate, re-configures the provider's refresh material, and overwrites the cache with the fresh token.

## Security note: where the refresh token lives

After the device-code login succeeds, the refresh token lives in two places:

1. **Inside OpenShell's gateway credential store** — encrypted at rest, registered via `provider refresh configure --secret-material-key refresh_token`. This is the *authoritative* copy; OpenShell mints access tokens from it transparently.
2. **`examples/personal-community-sentiment-triage/.bootstrap/cache/ms-graph-token.json` in the repo working tree** — plaintext, mode 0600, used only to skip device-code re-auth on subsequent `bash scripts/bring-up.sh` runs. The repo `.gitignore` excludes `.bootstrap/` so `git add -A` won't sweep it in; if you'd rather not have any on-disk cache at all, set `OUTLOOK_LOGIN_CACHE=0`. Lose this file and you'll just do one device-code login; nothing else changes.

If you'd prefer the refresh token never touch disk on your machine — shared workstation, demo environment, security-sensitive context — set `OUTLOOK_LOGIN_CACHE=0` in your `.env`. Bring-up will run device-code login on every invocation and write nothing locally. The gateway-side encrypted copy still gets refreshed each time, so the sandbox itself is unaffected.

Microsoft's refresh tokens expire after roughly 90 days of inactivity; the gateway rotates the token transparently before then. If it does lapse, force a fresh device-code login with `OUTLOOK_LOGIN_CACHE=2 bash scripts/bring-up.sh`.

## Shared / delegate mailbox access

The `outlook-email-search` skill reads from `OUTLOOK_REPLY_TO` (your personal mailbox), not the agent's own inbox. For this to work over Graph, you must grant the agent account **delegate access** to your mailbox — in Outlook desktop: **File → Account Settings → Delegate Access**, or send a folder-share invitation that the agent account accepts. Without delegate access, Graph returns `HTTP 403: Cannot find row based on condition.` when the skill queries `/users/$OUTLOOK_REPLY_TO/`.

## Troubleshooting

- **`provider refresh rotate` fails with `invalid_grant`** — the refresh token expired or was revoked. Re-run `OUTLOOK_LOGIN_CACHE=2 bash scripts/bring-up.sh`. (Usually the freshness check catches this on the next bring-up automatically.)
- **Bridge logs `HTTP 401`** — the access token isn't being substituted. Confirm `providers_v2_enabled` is set, the `hermes-direct-outlook` provider exists (`openshell provider get hermes-direct-outlook`), and the sandbox was created **after** the provider (provider attachments are evaluated at sandbox create time).
- **Bridge logs `HTTP 403: Cannot find row based on condition`** — missing delegate access for `OUTLOOK_REPLY_TO`. See the section above.
- **Device-code prompt never appears** — `scripts/02-providers.sh` short-circuited because the cache file at `.bootstrap/cache/ms-graph-token.json` exists and is fresh. Force a re-prompt with `OUTLOOK_LOGIN_CACHE=2` (rewrites the cache) or `OUTLOOK_LOGIN_CACHE=0` (skip the cache for this run).
