---
title:
  page: "Guided Configuration and Preflight"
  nav: "Guided Setup"
description:
  main: "Create a minimal Slack, Outlook, or combined configuration and run redacted prerequisite checks before starting services or a sandbox."
  agent: "Explains the developer-community-chief-of-staff recipe's guided configure.py and read-only preflight.py commands, including safe .env preservation, non-interactive inputs, local and external check boundaries, redaction, and next actions. Use when setting up or diagnosing this recipe before bring-up."
keywords: ["nemoclaw guided setup", "nemoclaw preflight", "hermes configuration", "openshell prerequisites"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "slack", "outlook", "setup", "preflight"]
content:
  type: how_to
  difficulty: beginner
  audience: ["developer", "engineer"]
status: published
---

<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

![NVIDIA](../assets/nvidia_header.png)

# Guided Configuration and Preflight

Use the guided configurator to create a minimal `.env`. Then use the preflight
to find configuration and host problems before `bring-up.sh` starts services,
creates providers, or builds a sandbox.

The configurator does not register external applications or grant access. Set
up the required Slack app or Microsoft Entra application before you enter its
values. You also need an inference API key with access to the selected model.

## Run Guided Configuration

From the recipe root, run:

```console
$ python3 scripts/configure.py
```

Select one messaging profile:

| Profile | Required inputs |
| --- | --- |
| `slack` | Inference API key, Slack bot access token, Slack app-level token |
| `outlook` | Inference API key, tenant ID, client ID, agent mailbox, reply-to mailbox |
| `both` | All Slack and Outlook inputs above |

The command proposes these non-secret defaults:

| Setting | Default |
| --- | --- |
| Sandbox name | `hermes-direct` |
| OpenShell gateway | `openshell` |
| Gateway endpoint | `https://127.0.0.1:17670` for `openshell`; `http://127.0.0.1:17670` for `snap-docker` |
| Inference model | `nvidia/nemotron-3-super-120b-a12b` |

Credential prompts do not echo their values. The final summary confirms that
the required credentials are configured without printing them.

### Existing `.env` behavior

If `.env` exists, the configurator preserves every comment, unknown setting,
and unselected value. Press Enter at a prompt to keep the current value. Enter
a new value to change that key.

The command fails instead of guessing when the file contains duplicate
assignments, invalid shell quoting, command lines, or unsupported shell
operators and expansions. It writes a successful result atomically and sets its
permissions to owner read/write (`0600`).

Use `--replace` only when you intend to discard unselected values and create a
minimal file:

```console
$ python3 scripts/configure.py --profile slack --replace
```

`.env.example` remains the complete reference for advanced settings. Manual
copy-and-edit setup remains supported.

## Run Non-Interactive Configuration

Non-interactive mode is deterministic and does not accept credential values as
command arguments. Supply required values through the process environment or
an existing `.env` and select the profile:

```console
$ python3 scripts/configure.py --non-interactive --profile slack
```

For a new Slack configuration, the environment must contain:

- `COMPATIBLE_API_KEY` or `OPENAI_API_KEY`
- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`

For Outlook, it must contain the inference key and all four values:

- `OUTLOOK_TENANT_ID`
- `OUTLOOK_CLIENT_ID`
- `OUTLOOK_TARGET_MAILBOX`
- `OUTLOOK_REPLY_TO`

Use all Slack and Outlook values for `--profile both`. Existing file values
take precedence so automation cannot overwrite a configured credential merely
because the parent process contains a different value. Use `--replace` with a
controlled environment when replacement is intentional.

These optional command arguments contain only non-secret values:

```console
$ python3 scripts/configure.py --non-interactive --profile slack \
    --sandbox-name hermes-direct \
    --gateway openshell \
    --gateway-endpoint https://127.0.0.1:17670 \
    --model nvidia/nemotron-3-super-120b-a12b
```

## Run Local Preflight

Run the default preflight before bring-up:

```console
$ python3 scripts/preflight.py
```

This mode does not contact configured external services. It performs these
read-only checks:

- Parses `.env` without executing it and checks owner-only permissions.
- Checks Slack, Outlook, inference, GitHub, optional Tavily web search, and
  other optional-component values.
- Checks Python, Git, Docker, Docker Compose, OpenShell, curl, and OpenSSL.
- Checks the Docker daemon, configured gateway reachability and registration,
  and the gateway-scoped provider-v2 setting.
- Checks the local ports used by Phoenix, OpenTelemetry, the source API,
  PostgreSQL, and enabled optional services.
- Reports enabled and skipped integrations and the exact next command.

An occupied recipe port is a warning because an existing deployment can own
it. Confirm that the listener belongs to this recipe before bring-up.

The preflight does not install software, modify gateway settings, select or
register a gateway, create providers, start services, or create a sandbox.

## Run Optional External Checks

After local checks pass, explicitly allow bounded service checks:

```console
$ python3 scripts/preflight.py --external
```

External mode reuses the checks that `02-providers.sh` uses:

- When inference validation is enabled, `inference_preflight.py` sends one
  bounded structured-tool request to the configured inference endpoint.
- When `TAVILY_API_KEY` is configured, `tavily_search_preflight.py` sends one
  search request with one result requested. It reports only success, a failure
  category, or an HTTP status; it does not print the API key or response body.
- When Slack is enabled, `slack_socket_preflight.py` calls Slack
  `apps.connections.open` to validate the app-level token and
  `connections:write` scope. Slack returns a temporary Socket Mode URL; the
  preflight does not print it or open the WebSocket.
- Outlook device-code sign-in remains an explicit bring-up step and is reported
  as skipped.

Neither mode creates a service, provider, or sandbox. External mode does
contact the selected services, so run it only when you have authorization and
valid credentials.

## Use Redacted JSON in Automation

Use `--json` for machine-readable output:

```console
$ python3 scripts/preflight.py --json
```

The JSON includes resolved non-secret defaults, check scope, status, detail,
remediation, and `next_command`. Credential values are omitted and are also
removed from captured error details.

Exit codes are:

| Code | Meaning |
| --- | --- |
| `0` | No check failed. Warnings and explicit skips can remain. |
| `1` | One or more configuration or prerequisite checks failed. |
| `2` | The command arguments or `.env` syntax are invalid. |

Follow the printed `next_command`. After `--external` completes without a
failure, the next command is:

```console
$ bash scripts/bring-up.sh
```
