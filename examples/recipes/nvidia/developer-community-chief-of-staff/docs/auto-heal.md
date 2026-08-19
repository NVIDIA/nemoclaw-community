---
title:
  page: "Optional Hermes Auto-Heal"
  nav: "Auto-Heal"
description:
  main: "Install optional user-level systemd monitoring for the developer-community-chief-of-staff Hermes sandbox after a successful first bring-up."
  agent: "Explains first-time installation, manual health checks, repair, logs, and removal for the optional host-side Hermes auto-heal services."
keywords: ["nemoclaw auto-heal", "hermes watchdog", "slack response monitor", "host tls proxy"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "slack", "outlook", "systemd"]
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

# Optional Hermes Auto-Heal

This is an opt-in reliability add-on for a running Hermes sandbox. It is not a
replacement for the normal first-time setup. Finish the README's OpenShell,
`.env`, and `bash scripts/bring-up.sh` steps first, including the one-time
Outlook device login when Outlook is enabled. The first image build can take
several minutes.

The add-on installs only **user-level** systemd units. It never copies API
keys into unit files and it does not need a root-owned service. On a headless
host, enable linger once so your user services continue after logout:

```console
$ sudo loginctl enable-linger "$USER"
```

## First-time installation

From the example directory, run the read-only preflight first:

```console
$ bash scripts/autoheal/install.sh --check
```

It checks the user systemd manager, Docker, OpenShell, Python, `.env`, a Ready
sandbox, and the Hermes gateway. Fix any failed check, then install:

```console
$ bash scripts/autoheal/install.sh
$ bash scripts/autoheal/sanity-check.sh
```

The installer enables a host gateway forward, a watchdog timer, and a Slack
response-monitor timer. It also enables a TLS proxy service when you configured
one.

## Upgrade from the previous example path

Earlier versions installed units from
`examples/personal-community-sentiment-triage`. Those units contain an absolute
path. Restore the ignored `.env` file at the new path before you continue. Do
not add that file to Git. Then run the installer from
`examples/recipes/nvidia/developer-community-chief-of-staff`:

```console
$ bash scripts/autoheal/install.sh
$ bash scripts/autoheal/sanity-check.sh
```

The installer detects the previous path. It replaces the runtime configuration
and unit files, then restarts only the auto-heal services and timers that this
example owns.

## Optional Inference Hub proxy

Use this only when the sandbox endpoint is routed through the host proxy:

```bash
NEMOCLAW_ENDPOINT_URL=http://host.openshell.internal:18080/v1
NEMOCLAW_HOST_TLS_PROXY_UPSTREAM=https://inference-api.nvidia.com
NEMOCLAW_HOST_TLS_PROXY_PORT=18080
```

`NEMOCLAW_HOST_TLS_PROXY_UPSTREAM` is intentionally explicit. It is the HTTPS
origin that the host proxy reaches; the sandbox-facing endpoint stays the
`host.openshell.internal` URL. The installer refuses to manage this proxy when
the sandbox endpoint uses port `18080` but the upstream is missing.

## What runs

| Unit | Purpose |
|---|---|
| `nemoclaw-hermes-proxy.service` | Keeps the optional host TLS inference proxy running. |
| `nemoclaw-hermes-gateway-forward.service` | Keeps `127.0.0.1:8642` forwarded to the sandbox Hermes gateway. |
| `nemoclaw-hermes-runtime.service` | Launches recovered Hermes through OpenShell after watchdog recovery. |
| `nemoclaw-hermes-watchdog.timer` | Runs health checks every minute and performs bounded recovery. |
| `nemoclaw-slack-response-monitor.timer` | Detects unanswered allowed-user Slack DMs and recent transport errors every minute. |

Recovery first restarts the affected host service or Hermes gateway. The
watchdog confirms a gateway outage with three fixed probes, two seconds apart,
before it restarts anything. It selects exactly one Docker container by the
OpenShell managed-by and sandbox-name labels, stops the local recovery launcher,
and terminates only the known Hermes runtime processes in that exact container.
It does **not** restart the OpenShell container: current OpenShell sandboxes use
a time-limited bootstrap token that may be expired when a watchdog runs, so a
raw Docker restart can leave an older sandbox stuck in `Provisioning`. The
watchdog instead verifies that the existing OpenShell supervisor still accepts
a non-root `sandbox` exec, then starts the recovered Hermes entrypoint through
`nemoclaw-hermes-runtime.service`, whose launch command is `openshell sandbox
exec`. OpenShell reapplies the persisted sandbox, proxy, CA, and provider
environment to that exec session. This preserves the sandbox writable layer and
keeps the recovered workload inside OpenShell's process and network policy
boundaries. Credentials are never added to recovery command arguments.
The runtime unit is a disabled recovery launcher, not the health authority.
The watchdog verifies a new gateway process ID and process start time, the
non-root workload identity, gateway health, and the exact Slack policy after
every launch.

The watchdog does not hot-apply changes from the host `.env` file. After changing
Outlook routing or Slack authorization values, use the documented
`tear-down.sh` and `bring-up.sh` flow to recreate the sandbox with those values.
Tear-down stops the local recovery launcher before it deletes the sandbox.

Before the non-root relaunch, the watchdog repairs files left by older root-run
recovery attempts. The repair is limited to Hermes writable state and known
runtime files. It does not follow symbolic links or modify immutable
`/sandbox/.hermes` configuration.

The watchdog rebuilds the sandbox only after a live Slack Socket Mode or
Microsoft Graph probe confirms that sandbox egress is failing. Locks and
cooldowns prevent repeated rebuilds.

## Manual operation

```console
$ bash scripts/autoheal/sanity-check.sh
$ bash scripts/autoheal/sanity-check.sh --repair
$ systemctl --user status nemoclaw-hermes-gateway-forward.service
$ systemctl --user status nemoclaw-hermes-runtime.service
$ systemctl --user list-timers 'nemoclaw-*'
$ journalctl --user -u nemoclaw-hermes-watchdog.service -n 80 --no-pager
$ journalctl --user -u nemoclaw-slack-response-monitor.service -n 80 --no-pager
```

`sanity-check.sh` only reports health by default. `--repair` runs the watchdog
after reporting failures. It does not print credentials.

To stop and remove the optional add-on without touching the sandbox, providers,
or host data services:

```console
$ bash scripts/autoheal/uninstall.sh
```

## Troubleshooting

- **`install.sh --check` says the user manager is unavailable:** reconnect to
  the host after enabling linger, or export `XDG_RUNTIME_DIR=/run/user/$(id -u)`
  in the current shell.
- **The proxy service is absent:** configure
  `NEMOCLAW_HOST_TLS_PROXY_UPSTREAM` only when you intentionally use the host
  proxy, then rerun the installer.
- **A Slack message still receives no reply:** run the sanity check, then share
  the non-secret watchdog and response-monitor log lines with the operator.
- **Outlook Graph remains unavailable after recovery:** confirm normal Outlook
  delegate access and provider setup using the README; auto-heal cannot repair
  an expired sign-in or missing mailbox permissions.
