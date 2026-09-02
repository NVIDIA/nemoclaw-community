<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Shrike Security Action Governance

| Catalog field | Value |
| --- | --- |
| Description | Adds defense-in-depth action governance through an in-sandbox hook that checks each OpenClaw tool call against server-side Shrike policy and blocks prohibited or approval-required calls. |
| Industry | ✨ Other |
| Requirements | NemoClaw/OpenShell · Node.js + npm · inference provider · Shrike API key · in-sandbox defense-in-depth only |
| NemoClaw | >=v0.0.76 |
| Harness | OpenClaw Unpinned |
| OpenShell | Unpinned |
| Contributor | Shrike Security, Inc. |

Govern what an OpenClaw agent is allowed to **do**. This recipe installs a
Shrike **`before_tool_call` plugin** into a NemoClaw/OpenShell sandbox so every
tool call is evaluated by Shrike's enforce plane before it runs, and blocked
when the verdict is `block` or `require_approval`.

OpenShell contains *where* an agent can act (network, filesystem, syscalls).
Shrike governs *what* a specific action is — a benign shell command is allowed;
a destructive command, a SQL injection, an injected instruction, or a secret
exfiltration attempt is blocked — with the decision made server-side against
organizational policy and returned as `allow` / `warn` / `require_approval` /
`block`. The two compose: the sandbox is the cage, Shrike is the judgment.

This is **in-sandbox defense-in-depth**, not an independent security boundary.
The plugin runs inside the sandbox alongside the agent; a fully compromised
sandbox could tamper with it. The independent controls remain the OpenShell
egress policy + credential provider (`providers/shrike.yaml`), which hold even
if the in-sandbox plugin is subverted.

Background and design walkthrough: [Securing NemoClaw Agents with Shrike](https://shrikesecurity.com/blog/securing-nemoclaw-agents).

## Intended users and support boundary

For operators running OpenClaw agents inside NemoClaw who want an action-level
policy decision on tool calls without building approval logic into each agent.

**Support boundary.** This is a community-maintained recipe contributed by
Shrike Security, Inc. It is provided as-is under Apache-2.0. Product/API
questions: <https://shrikesecurity.com>. Recipe issues: open a GitHub issue on
this repository identifying the example. It is not covered by an NVIDIA support
agreement.

## Data-sharing boundary (read before enabling)

When the plugin evaluates an action, the **action content** — the shell command,
SQL text, file-write body, web-search target, or message content of the tool
call — is transmitted over TLS to `api.shrikesecurity.com` for evaluation. A
decision and a short reason are returned; no other sandbox data is sent. If no
Shrike credential is configured, the plugin cannot obtain a verdict and (by
default) blocks the action fail-closed — nothing is transmitted without a key.
Retention, GDPR/CCPA, and data-deletion posture: <https://shrikesecurity.com/privacy>.

Do not enable this recipe on a workload whose tool-call content must never leave
the sandbox.

## Provenance

Contributed by **Shrike Security, Inc.** Attribution is preserved in the SPDX
headers of every file. Shrike Security authored the plugin, policy, and
lifecycle scripts; the recipe targets the public NemoClaw/OpenShell CLIs.

## Prerequisites and supported environments

- NemoClaw installed with a working OpenShell gateway (`nemoclaw`, `openshell`
  on `PATH`). Install: `curl -fsSL https://www.nvidia.com/nemoclaw.sh | NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash`
- An inference provider (NVIDIA-hosted `build` endpoints, or any OpenAI-compatible endpoint).
- A Shrike API key (free tier available): <https://shrikesecurity.com/signup>
- On the host: `node` + `npm` (to build the plugin) and `curl`.
- Verified on macOS (arm64) and Linux hosts with a CPU-only OpenShell gateway,
  NemoClaw v0.0.103 / OpenShell 0.0.85 / OpenClaw 2026.7.1.

## Architecture and major components

```
OpenClaw agent  --(tool call)-->  before_tool_call plugin  --(action content)-->  Shrike enforce
     |                                     |                                            |
     |                                     |  allow/warn -> allow                       |  server-side
     |  <----------- decision -------------+  block/require_approval -> block            |  9-layer policy
```

- `plugin/` — the OpenClaw `before_tool_call` plugin (TypeScript → `dist/`). It
  classifies each action (sql / command / file_write / web_search / general),
  calls the enforce plane, and maps the verdict to an OpenClaw decision
  (`allow`/`warn` → allow; `block`/`require_approval` → block). Fail-closed by
  default. This is the supported OpenClaw interception path — the same contract
  NemoClaw's own secret-scanner uses — not a Claude-style PreToolUse hook.
- `providers/shrike.yaml` — OpenShell v2 provider profile: declares the
  `SHRIKE_API_KEY` bearer credential and scopes egress to the two enforce POST
  paths on `api.shrikesecurity.com` with `enforcement: enforce`.
- `agents.yaml` — keeps the full toolset; governance is at the plugin, not by
  removing tools.
- `scripts/` — `onboard.sh`, `install.sh`, `build-image.sh`, `verify.sh`,
  `status.sh`, `teardown.sh`.

## Two install paths

The plugin can be delivered two ways. **Image is the supported, reliable path;
runtime is a best-effort local convenience.**

| | **`image` (recommended)** | **`runtime` (dev quick-try)** |
| --- | --- | --- |
| How | Baked into a version-matched custom sandbox image at onboard time (`nemoclaw onboard --from`) | Installed into the live sandbox (`openclaw plugins install`) |
| Durable across `rebuild` | Yes | No |
| Touches the managed config guard | No — config is sealed correctly at build time | Yes — see below |
| Provenance / trusted-source check | Yes — NemoClaw records + re-validates plugin provenance on every rebuild (v0.0.76+) | No — see below |
| Prerequisite | A matched NemoClaw source checkout (or GitHub access to clone the release tag) | None |

### Why image is the reliable path (the config-integrity shield)

The managed runtime protects `openclaw.json` with an integrity shield
(`.config-hash`). Enabling a plugin **at runtime** rewrites `openclaw.json`
out-of-band, and a background normalizer keeps rewriting it, so the gateway
refuses to restart (`GATEWAY_UNSAFE_CONFIG_PATH`) until the change is re-blessed
— and re-blessing races the normalizer nondeterministically. There is no
supported runtime plugin-install into a managed sandbox yet (tracked upstream in
[NemoClaw #5998](https://github.com/NVIDIA/NemoClaw/issues/5998)).

The **image path avoids this entirely**: the plugin is installed and the config
is sealed *at trusted build time*, before the shield locks it, under NemoClaw's
provenance guard. That guard is the real "this change is authentic" check — a
property the runtime path cannot provide (a runtime re-bless proves *intent*,
not *authenticity*: `.config-hash` is a sha256, carrying no signature). As a
security recipe, this example uses NemoClaw's supported path and does **not**
silently circumvent the integrity shield.

## Setup and configuration

```bash
cp .env.example .env      # set SHRIKE_API_KEY + your inference provider vars
```

### Recommended — image install (durable, provenance-guarded)

```bash
# Point at a NemoClaw source checkout matching your installed CLI (or let
# build-image.sh clone the matching release tag from GitHub).
export INSTALL_MODE=image
export NEMOCLAW_SOURCE_DIR=/path/to/NemoClaw   # matched to `nemoclaw --version`

bash scripts/onboard.sh    # import provider + create provider + BAKE plugin image + attach provider
bash scripts/install.sh    # verifies the baked plugin loaded (no-op install)
bash scripts/verify.sh     # allowed/denied live validation
```

### Dev quick-try — runtime install (not durable; best-effort)

```bash
bash scripts/onboard.sh                          # import + create provider + onboard + attach provider
SHRIKE_RUNTIME_REBLESS=1 bash scripts/install.sh # install plugin into the live sandbox
bash scripts/verify.sh
```

`install.sh` will not silently touch the managed config guard: without
`SHRIKE_RUNTIME_REBLESS=1` it fails loud and points you here. With the opt-in it
re-blesses the integrity hash (unsigned, operator-asserted) and retries; because
that races the managed normalizer it may not settle — if it doesn't, use the
image path.

Overridable knobs (in `.env`): `INSTALL_MODE`, `NEMOCLAW_SANDBOX_NAME`,
`SHRIKE_PROFILE_ID`, `SHRIKE_PROVIDER_NAME`, `SHRIKE_FAIL_MODE` (`closed`
default = block on enforce error; `open` = allow), `SHRIKE_VERIFY_TOOL`,
`NEMOCLAW_SOURCE_DIR`.

## Credential and secret handling

`onboard.sh` imports the v2 provider profile (`providers/shrike.yaml`) and
creates a provider with `openshell provider create`, supplying `SHRIKE_API_KEY`
to the **gateway** once through a clean sub-environment, then **attaches** that
provider to the sandbox. The plugin references only the placeholder
`openshell:resolve:env:SHRIKE_API_KEY`; the OpenShell L7 proxy substitutes the
real value on egress to `api.shrikesecurity.com`. The raw key is never written
into the sandbox environment, filesystem, or agent context. `.env` holds the key
on the host only (for the one `provider create` call) and is git-ignored.

## Sandbox, network, and policy permissions

`providers/shrike.yaml` scopes egress to `api.shrikesecurity.com:443` with
`enforcement: enforce`, and restricts it to exactly two POST paths
(`/agent/api/scan/enforce` and `/agent/api/scan/enforce/specialized`) — no other
method or path on the host is reachable — and permits only `curl` for the egress
call. No other network destination is reachable from the sandbox.

## Startup behavior

Governance is active once the plugin is loaded (after the image onboard, or
after a successful runtime install + gateway restart). There is no long-running
service to start; every tool call is evaluated inline before it executes.

## Verification steps and expected results

```bash
bash scripts/verify.sh
```

`verify.sh` drives **real tool calls through the sandbox gateway**
(`/tools/invoke`); the `before_tool_call` plugin fires on each before the tool
runs. A benign call must pass the plugin (not blocked); a malicious call must be
blocked (`tool_call_blocked`).

| Tool call (`SHRIKE_VERIFY_TOOL`, default `web_search`) | Expected |
| --- | --- |
| Benign technical query | **allowed** (passes the plugin) |
| Prompt injection (ignore-instructions + exfil) | **blocked** |

`scripts/verify.sh` exits `0` only when every case matches. A full transcript of
a real run is in [docs/verify-functionality.md](docs/verify-functionality.md).
Inspect wiring any time with `bash scripts/status.sh`.

## Teardown and cleanup

```bash
bash scripts/teardown.sh                  # disable/uninstall plugin + detach + remove provider/profile + sandbox
KEEP_SANDBOX=1 bash scripts/teardown.sh   # only un-wire Shrike; keep the sandbox
```

Teardown-safe: leaves no service or credential active. For an `image` install
the plugin is baked into the image, so removing the sandbox (the default) is the
clean teardown.

## Known limitations

- **In-sandbox defense-in-depth, not an independent boundary** — a fully
  compromised sandbox could tamper with the plugin; the OpenShell egress policy
  + credential provider are the controls that hold regardless.
- **Runtime install is best-effort** — it races the managed config-integrity
  shield and is not durable across `rebuild`; use `image` for anything real.
- Enforce adds a network round-trip per governed action (typically well under a
  second warm). `SHRIKE_FAIL_MODE=open` trades containment for availability if
  the enforce plane is unreachable.
- Action classification is heuristic by tool/field shape; unusual tool schemas
  fall back to the general enforce path.
- `verify.sh` drives one tool (`SHRIKE_VERIFY_TOOL`, default `web_search`); set
  it to a tool your agent exposes.

## Third-party dependencies and license obligations

The plugin builds with TypeScript (dev-only) and imports nothing from the
`openclaw` runtime (structural types), so it ships no runtime third-party
libraries. It uses the NemoClaw and OpenShell CLIs and `curl`, already present
in the runtime. The recipe is licensed under Apache-2.0. The Shrike service it
calls is operated by Shrike Security, Inc. under its own terms
(<https://shrikesecurity.com>).
