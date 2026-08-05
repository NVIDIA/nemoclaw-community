---
name: nemoclaw-autoheal
description: Guide users through Hermes availability checks and the optional host-side auto-heal setup without crossing the sandbox-to-host boundary.
---

<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# nemoclaw-autoheal

Use this skill when a user says the Slack bot is not responding, asks whether
Hermes is healthy, reports inference `503`/`504` failures, asks about Outlook
connectivity, or wants to install the optional auto-heal services.

## Boundary

You run inside the OpenShell sandbox. Do not run `systemctl`, recreate the
sandbox, inspect credentials, or try to install host services. Those actions
belong to the host operator. You may call `nemoclaw_status` to inspect the
local Hermes gateway, then give the operator the exact commands below.

## Diagnose

1. Call `nemoclaw_status` first. If the gateway is stopped, say that the
   sandbox gateway is unhealthy.
2. For an inference error, explain that `503`, `504`, or a timeout can be an
   upstream service or host-proxy failure.
3. For a Slack failure, distinguish an unavailable gateway from an allowlist,
   Socket Mode, or Slack API issue. Do not claim the bot received a message
   unless the user supplied evidence.
4. For Outlook, explain that a Graph connection closure may be sandbox egress
   or a temporary proxy failure; it is not proof that the mailbox settings are
   wrong.

## Tell the host operator

Run these commands from the cloned example directory, not inside the sandbox:

```bash
bash scripts/autoheal/sanity-check.sh
bash scripts/autoheal/sanity-check.sh --repair
```

If auto-heal is not installed yet, first run:

```bash
bash scripts/autoheal/install.sh --check
bash scripts/autoheal/install.sh
```

For status and logs:

```bash
systemctl --user status nemoclaw-hermes-gateway-forward.service
systemctl --user list-timers 'nemoclaw-*'
journalctl --user -u nemoclaw-hermes-watchdog.service -n 80 --no-pager
```

If the user runs an inference endpoint through
`http://host.openshell.internal:18080`, remind them to set
`NEMOCLAW_HOST_TLS_PROXY_UPSTREAM` in the host `.env` before installing the
auto-heal services. The value is the HTTPS origin, for example
`https://inference-api.nvidia.com`.

## Response style

Start with the current status or likely failure class, then give only the next
one or two host commands. Do not print or request Slack, Outlook, GitHub, or
inference credentials.
