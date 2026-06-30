<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Troubleshooting And Recovery

Start with the automated status and verification commands:

```bash
./scripts/demo.sh status
./scripts/demo.sh verify
```

## Service Map

| Port    | Owner                            | Expected health check                     |
| ------- | -------------------------------- | ----------------------------------------- |
| `8642`  | OpenShell host forward to Hermes | `curl -fsS http://127.0.0.1:8642/health`  |
| `18080` | Financial UI server              | `curl -fsS http://127.0.0.1:18080/health` |
| `6006`  | Phoenix                          | `curl -fsS http://127.0.0.1:6006/`        |

The browser talks only to `18080`. A `Failed to fetch` browser error usually
means the UI process or its Brev port forward is missing, not that Hermes died.

## Normal Recovery

After a reboot or stopped process:

```bash
cd examples/financial-analyst-hermes
./scripts/demo.sh start
./scripts/demo.sh verify
```

If the UI alone failed:

```bash
tail -n 100 .runtime/ui.log
./scripts/demo.sh start
```

If Hermes is unavailable:

```bash
nemohermes financial-analyst status
nemohermes financial-analyst logs --follow
openshell sandbox list
```

Use a clean sandbox recreation only after saving relevant work:

```bash
nemohermes financial-analyst destroy --yes
./scripts/demo.sh install
./scripts/demo.sh start
./scripts/demo.sh verify
```

## Why Earlier Setup Failed

The prior implementation accumulated several independent failure modes:

1. The root `.env` was sourced wholesale. Old OpenShell gateway variables and
   unrelated messaging credentials changed onboarding behavior. The new script
   parses only named model settings and launches onboarding through `env -i`.
2. A model key was exported under an alias that NemoClaw resume did not read.
   The script now maps the selected key to the exact provider variable.
3. Relay observability was implemented as a custom Hermes plugin, shell-hook
   forwarder, and finalizer. Hermes `0.17.0` already includes those hooks. The
   demo now uses the bundled native plugin directly.
4. Docker `ENV` alone did not reach the Hermes gateway because OpenShell's
   privilege boundary resets the process environment. The strict NemoClaw
   patch passes the Relay config to both gateway launch paths explicitly.
5. Multiple start/recovery scripts disagreed about ports and process ownership.
   `scripts/demo.sh` is now the only core lifecycle entry point.
6. The UI could point directly at an arbitrary model endpoint. That bypassed
   Hermes and exposed browser/CORS failures. The server now always proxies the
   local Hermes forward and injects its token server-side.
7. Fresh Brev hosts may have neither Node nor a Playwright browser. The script
   installs a checksum-pinned user-local Node runtime and pinned Chromium before
   running the browser gate.

## Validate Hermes And Native Relay

```bash
nemohermes financial-analyst exec -- \
  /opt/hermes/.venv/bin/python -c \
  'import nemo_relay; import plugins.observability.nemo_relay; print("ok")'

nemohermes financial-analyst exec -- \
  grep -n observability/nemo_relay /sandbox/.hermes/config.yaml
```

After a verified question:

```bash
curl -fsS http://127.0.0.1:18080/api/phoenix/recent | python3 -m json.tool
```

A healthy tool-using turn has `llm` and `tool` spans with the same `trace_id`
and a non-empty `parent_id`. Hermes keeps the session root open until session
finalization; child LLM/tool spans appear immediately.

## ATIF Downstream Is Not Enabled

The released dependency set cannot export finalized ATIF trajectories to S3 or
S3-compatible endpoints. Hermes `0.17.0` locks NeMo Relay `0.3`, which predates
object storage. Relay `0.4` contains the implementation in source but its
published Python wheel was built without that native feature. Configuring
`[[components.config.atif.storage]]` fails with
`ATIF storage support is not enabled in this build`.

This does not affect live OpenInference traces in Phoenix. Do not add a custom
source-built wheel to this demo; move to a stable Relay release with the
object-store feature when one is published, then add a separate end-to-end
storage test before claiming downstream delivery.

## Common Errors

### `Request failed: Failed to fetch`

```bash
./scripts/demo.sh status
tail -n 100 .runtime/ui.log
curl -fsS http://127.0.0.1:18080/health
```

On Brev, also restart the laptop-side `18080:18080` port forward.

### Hermes returns `404`

Confirm the exact endpoint and model in `.env`, then recreate inference routing:

```bash
nemohermes financial-analyst destroy --yes
./scripts/demo.sh up
```

The script never sources `.env`; changing unrelated values cannot alter the
gateway selection.

### Phoenix is healthy but empty

```bash
nemohermes financial-analyst policy-add \
  --from-file presets/financial-phoenix-relay.yaml --yes
./scripts/demo.sh verify
```

Also confirm Phoenix is listening on the Brev host before the request. The
sandbox exports to `host.openshell.internal:6006` through an explicit policy.

### The strict patch rejects a newer NemoClaw layout

This is intentional. Do not silently patch an unknown Dockerfile or startup
script. Update `NEMOCLAW_REF`, review the new Hermes blueprint, update the
patcher's exact integration points, and extend `test_patch_nemoclaw.py` first.

### Outlook login reports `AADSTS53003`

Authentication succeeded but Microsoft Entra Conditional Access rejected the
application, location, or device. The demo cannot bypass tenant policy. See
[Outlook](outlook.md) for the required administrator path.
