<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Shrike Security — Agent Action Governance

Govern what an OpenClaw agent is allowed to **do**. This recipe installs a
Shrike PreToolUse hook into a NemoClaw/OpenShell sandbox so every matched tool
call is evaluated by Shrike's enforce plane before it runs, and denied when the
verdict is `block` or `require_approval`.

OpenShell contains *where* an agent can act (network, filesystem, syscalls).
Shrike governs *what* a specific action is — a benign shell command is allowed;
a destructive command, a SQL injection, an injected instruction, or a secret
exfiltration attempt is denied — with the decision made server-side against
organizational policy and returned as `allow` / `warn` / `require_approval` /
`block`. The two compose: the sandbox is the cage, Shrike is the judgment.

## Intended users and support boundary

For operators running OpenClaw agents inside NemoClaw who want an action-level
policy decision on tool calls without building approval logic into each agent.

**Support boundary.** This is a community-maintained recipe contributed by
Shrike Security, Inc. It is provided as-is under Apache-2.0. Product/API
questions: <https://shrikesecurity.com>. Recipe issues: open a GitHub issue on
this repository identifying the example. It is not covered by an NVIDIA support
agreement.

## Data-sharing boundary (read before enabling)

When the hook evaluates an action, the **action content** — the shell command,
SQL text, file-write body, web-search target, or message content of the matched
tool call — is transmitted over TLS to `api.shrikesecurity.com` for evaluation.
A decision and a short reason are returned; no other sandbox data is sent. If no
Shrike credential is configured, the hook cannot obtain a verdict and (by
default) denies the action fail-closed — nothing is transmitted without a key.
Retention, GDPR/CCPA, and data-deletion posture: <https://shrikesecurity.com/privacy>.

Do not enable this recipe on a workload whose tool-call content must never leave
the sandbox.

## Provenance

Contributed by **Shrike Security, Inc.** Attribution is preserved in the SPDX
headers of every file. Shrike Security authored the hook, policy, and lifecycle
scripts; the recipe targets the public NemoClaw/OpenShell CLIs.

## Prerequisites and supported environments

- NemoClaw installed with a working OpenShell gateway (`nemoclaw`, `openshell`
  on `PATH`). Install: `curl -fsSL https://www.nvidia.com/nemoclaw.sh | NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash`
- An inference provider (NVIDIA-hosted `build` endpoints, or any OpenAI-compatible endpoint).
- A Shrike API key (free tier available): <https://shrikesecurity.com/signup>
- `bash`, `node`, and `curl` available in the sandbox (present in the OpenClaw runtime).
- Verified on macOS (arm64) and Linux hosts with a CPU-only OpenShell gateway.

## Architecture and major components

```
OpenClaw agent  --(tool call)-->  PreToolUse hook  --(action content)-->  Shrike enforce
     |                                   |                                      |
     |                                   |  allow/warn -> allow                 |  server-side
     |  <---------- decision ------------+  block/require_approval -> deny       |  9-layer policy
```

- `hooks/shrike-preaction-hook.mjs` — classifies the action (sql / command /
  file_write / web_search / general), calls the enforce plane, maps the verdict
  to an OpenClaw permission decision. Fail-closed by default.
- `providers/shrike.yaml` — OpenShell v2 provider profile: declares the
  `SHRIKE_API_KEY` bearer credential and scopes egress to
  `api.shrikesecurity.com` with `enforcement: enforce`. Imported at onboard time.
- `agents.yaml` — keeps the full toolset; governance is at the hook, not by
  removing tools.
- `scripts/` — `onboard.sh`, `install.sh`, `verify.sh`, `status.sh`, `teardown.sh`.

## Credential and secret handling

`onboard.sh` imports the v2 provider profile (`providers/shrike.yaml`) and
creates a provider instance with `openshell provider create`, supplying
`SHRIKE_API_KEY` to the **gateway** once through a clean sub-environment. The
sandboxed agent and hook reference only the placeholder
`openshell:resolve:env:SHRIKE_API_KEY`; the OpenShell L7 proxy substitutes the
real value on egress to `api.shrikesecurity.com`. The raw key is never written
into the sandbox environment, filesystem, or agent context. `.env` holds the key
on the host only (for the one `provider create` call) and is git-ignored.

## Setup and configuration

```bash
cp .env.example .env      # set SHRIKE_API_KEY + your inference provider vars
bash scripts/onboard.sh   # import provider profile + create provider (key held gateway-side) + onboard sandbox
bash scripts/install.sh   # install the PreToolUse hook into the sandbox
```

Overridable knobs (in `.env`): `NEMOCLAW_SANDBOX_NAME`, `SHRIKE_PROFILE_ID`,
`SHRIKE_PROVIDER_NAME`, `SHRIKE_FAIL_MODE` (`closed` default = deny on enforce
error; `open` = allow).

## Sandbox, network, and policy permissions

The provider profile (`providers/shrike.yaml`) scopes egress to
`api.shrikesecurity.com:443` with `enforcement: enforce` and permits `curl` +
`node` for the hook. The Shrike enforce API itself accepts only the
`/agent/api/scan/enforce[/specialized]`, `/agent/api/session/status`, and
`/health` paths. No other network destination is reachable from the sandbox.

## Startup behavior

Governance is active as soon as `install.sh` registers the PreToolUse hook —
there is no long-running service to start. Every matched tool call is evaluated
inline before it executes.

## Verification steps and expected results

```bash
bash scripts/verify.sh
```

Drives the installed hook with representative payloads and asserts:

| Action | Expected |
| --- | --- |
| Benign shell command (`ls -la`) | **allow** |
| Destructive command (`rm -rf /`) | **deny** |
| SQL injection (`... OR 1=1; DROP TABLE`) | **deny** |
| Prompt injection (ignore-instructions + exfil) | **deny** |
| Secret exfiltration (key in URL) | **deny** |

`scripts/verify.sh` exits `0` only when every case matches. A full transcript of
a real run is in [docs/verify-functionality.md](docs/verify-functionality.md).
Inspect wiring any time with `bash scripts/status.sh`.

## Teardown and cleanup

```bash
bash scripts/teardown.sh              # remove hook + Shrike provider/profile + sandbox
KEEP_SANDBOX=1 bash scripts/teardown.sh   # only un-wire Shrike; keep the sandbox
```

Teardown-safe: leaves no service or credential active.

## Known limitations

- The hook governs **matched tool calls**; content the agent never routes
  through a tool is out of scope (that is OpenShell's containment layer's job).
- Enforce adds a network round-trip per governed action (typically well under a
  second warm). `SHRIKE_FAIL_MODE=open` trades containment for availability if
  the enforce plane is unreachable.
- Action classification is heuristic by tool/field shape; unusual tool schemas
  fall back to the general enforce path.

## Third-party dependencies and license obligations

No new third-party libraries are added by this recipe. It uses the NemoClaw and
OpenShell CLIs, `node`, and `curl`, all already present in the runtime. The
recipe is licensed under Apache-2.0. The Shrike service it calls is operated by
Shrike Security, Inc. under its own terms (<https://shrikesecurity.com>).
