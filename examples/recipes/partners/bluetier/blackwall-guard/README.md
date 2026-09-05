<!--
SPDX-FileCopyrightText: Copyright (c) 2026 BlueTier Operations LLC
SPDX-License-Identifier: Apache-2.0
-->

# Blackwall Preflight Guardrail

| Catalog field | Value |
| --- | --- |
| Description | Screens every OpenClaw tool call through an external Blackwall pre-action risk forecast, GO, CAUTION, or STOP, as defense-in-depth, with proxy-injected credentials and metadata-only forecasts by default. |
| Industry | ✨ Other |
| Requirements | Node.js · Docker + OpenShell · Blackwall API key, free tier available · in-sandbox hook, not an independent enforcement boundary |
| NemoClaw | N/A |
| Harness | OpenClaw Unpinned |
| OpenShell | Unpinned |
| Contributor | BlueTier Operations |

A community integration that adds a **pre-action risk gate** to an OpenClaw agent
running under NemoClaw. It hooks `before_tool_call` and runs a risk forecast
**before any tool executes** — so a sandboxed agent is checked at the moment of
action, not after the damage is done.

This is defense-in-depth: it catches dangerous actions a compromised, mistaken, or
prompt-injected agent might attempt — destructive shell commands, irreversible
writes, data exfiltration, fund movement — independent of the model's own judgment.

## Enforcement architecture: defense-in-depth, not an independent boundary

Be precise about what this plugin is. The `before_tool_call` hook runs **inside
the agent sandbox**, in the same process space the agent controls — so a
sufficiently capable compromised agent could in principle disable or bypass it.
It is **defense-in-depth**: an additional check that raises the cost of a bad
action, layered *under* the boundaries that the agent cannot touch — the
OpenShell network policy (which caps where the sandbox can reach regardless of
what the agent runs) and the provider credential injection (which keeps the API
key out of the sandbox entirely, so even a fully compromised agent cannot steal
it or forge authenticated forecasts).

An **independent** enforcement boundary for tool calls belongs outside the
sandbox — OpenShell's Supervisor middleware is the natural home, since it
observes tool traffic from a position the agent cannot modify. Supervisor is
currently a research-preview integration that standard NemoClaw onboarding does
not configure, so this example does not wire it; moving the forecast call into
Supervisor (with the in-sandbox hook retained as the low-latency first layer)
is the intended evolution, in coordination with the OpenShell maintainers.
Until then, treat this integration as hardening, not as the boundary itself.

> **Third-party integration — requirements & support.** This is an independent
> community example, **not** a supported part of NemoClaw core. It calls the external
> [BLACK_WALL](https://blackwalltier.com) service and **requires a BLACK_WALL API
> key** — sign up at [blackwalltier.com](https://blackwalltier.com) (a free tier is
> available; usage-based pricing applies above it). **Support** for this integration
> and the service is provided by BlueTier Operations, not NVIDIA — contact
> <bluetier.operations@gmail.com> or [blackwalltier.com](https://blackwalltier.com).

## What it does

- On every tool call, calls BLACK_WALL `forecast()` and receives a verdict —
  **GO**, **CAUTION**, or **STOP** — plus a risk score and named red flags.
- In **enforce** mode: **STOP** blocks the call before it runs. **CAUTION** also
  blocks by default — NemoClaw's `before_tool_call` contract has no interactive
  approval surface, so a CAUTION verdict is blocked with its red-flag detail in the
  block reason rather than prompting. Configurable via `cautionAction` (set `allow`
  to let CAUTION through).
- In **observe** mode (the default): logs the verdict but never blocks — safe to
  trial in production without changing behavior.
- Every decision returns an **Ed25519-signed receipt** that verifies **offline**
  against the published key — a tamper-evident audit trail of what the agent was
  about to do and why it was allowed or blocked.

## Files

| Path | Purpose |
|---|---|
| `index.ts` | The plugin. Registers `before_tool_call` + `after_tool_call`, calls `forecast()`/`observe()`, and returns the block decision. |
| `openclaw.plugin.json` | Plugin manifest (config schema, defaults). |
| `skills/blackwall-policy/SKILL.md` | Guidance for tuning enforce/observe and the gate policy. |
| `skills/blackwall-verify/SKILL.md` | How to independently verify a decision receipt. |
| `index.test.ts` | Vitest suite pinning the gate's decision state machine, the HTTPS-only credential guard, input minimization, fail-closed defaults, and the proxy CONNECT-header cap. Runnable in-repo: `npm install && npm test`. |
| `package.json` | Dev harness for the test suite (vitest); not needed at runtime. |
| `scripts/bring-up.sh` | Full OpenShell lifecycle: import the provider profile, create the provider with the key held gateway-side, create the sandbox with `policy.yaml` and the provider attached. |
| `scripts/tear-down.sh` | Reverse of bring-up: delete the sandbox, the per-sandbox provider, and (with `--profile`) the imported profile. |
| `scripts/install.sh` | Host-side dev loop only: copy the plugin into an OpenClaw plugin directory (`$OPENCLAW_PLUGIN_DIR` / `~/.openclaw/extensions`). In NemoClaw the plugin is baked into the sandbox image instead (see *Install & enable*). |
| `scripts/verify.sh` | Three-stage check: unit tests, egress reachability, and a live credential-injection probe that distinguishes "no key arrived" / "placeholder passed through unreplaced" / "real key injected". |
| `scripts/uninstall.sh` | Host-side dev loop only: remove the installed plugin (manifest-id guarded). |
| `providers/blackwall.yaml` | OpenShell provider profile that injects the API key at the L7 proxy on egress, so the key never enters the sandbox (see *Recommended deployment*). |
| `policy.yaml` | OpenShell sandbox network policy allowing egress only to the BLACK_WALL forecast endpoints. |

## Enable & configure

Disabled by default. Enable it for an agent and provide an API key:

| Config | Env | Meaning |
|---|---|---|
| `apiKey` | `BLACKWALL_API_KEY` | BLACK_WALL API key (get one at <https://blackwalltier.com>) |
| `baseUrl` | `BLACKWALL_BASE_URL` | API base URL (default `https://blackwalltier.com`; **must be `https://`** for any non-loopback host) |
| `mode` | `BLACKWALL_MODE` | `observe` (default) or `enforce` |
| `cautionAction` | — | what a CAUTION verdict does in enforce mode: `approve` (default) → **block** with red-flag detail / `block` → **block** / `allow` → permit |
| `failClosed` | `BLACKWALL_FAIL_CLOSED` | if the gate is unreachable, block instead of allowing an unscored action. **Default `true`** (fail closed) — set `false` to prefer availability over enforcement. |
| `inputMode` | `BLACKWALL_INPUT_MODE` | what a forecast carries about tool parameters. **Default `metadata`**: key names, value types, and byte sizes only — parameter *values* never leave the sandbox. `contents`: size-capped/truncated values, opt-in, for content-based red-flag detection. |
| `forecastTimeoutMs` | `BLACKWALL_TIMEOUT_MS` | per-call forecast timeout (ms) |

> **Sandboxed runtimes (e.g. NemoClaw):** the agent process may run with a scrubbed
> environment, so `BLACKWALL_API_KEY` can be empty even when a login shell sees it.
> The plugin also resolves the key from a file — `$BLACKWALL_API_KEY_FILE`,
> `$OPENCLAW_HOME/.openclaw/blackwall.key`, or `$HOME/.openclaw/blackwall.key` — so
> you can deliver it as a file the agent can read. That is the *simple* option; the
> *recommended* one below keeps the key out of the sandbox entirely.

## Recommended deployment (NemoClaw) — keep the key out of the sandbox

The strongest setup never places the API key inside the sandbox at all. Rather than
delivering the key to the agent (env var or file, above), inject it at the OpenShell
L7 proxy on egress. Two files here express this:

- **`providers/blackwall.yaml`** — an OpenShell provider profile with
  `auth_style: bearer`. The sandbox's `BLACKWALL_API_KEY` holds only an OpenShell
  placeholder; the L7 proxy substitutes the real value into the `Authorization`
  header as the request leaves the sandbox. A compromised or prompt-injected agent
  inside the sandbox can never read the credential.
- **`policy.yaml`** — a sandbox network policy that explicitly allows egress to
  `blackwalltier.com:443`, scoped to only the two forecast endpoints the plugin
  calls (`POST /api/v1/forecast` and `POST /api/v1/forecast/<id>/outcome`).

The plugin itself needs no change: it still sends `Authorization: Bearer
$BLACKWALL_API_KEY`, but in the sandbox that value is the placeholder, and the real
key exists only host-side. This mirrors the provider + policy pattern used by the
[Developer Community Chief of Staff](../../../nvidia/developer-community-chief-of-staff/README.md)
recipe. `scripts/bring-up.sh` performs the profile import, provider creation, and
policy application; to wire it into an existing deployment instead, merge
`policy.yaml`'s `network_policies` entry into your sandbox policy and import
`providers/blackwall.yaml` alongside your other OpenShell providers.

## What leaves the sandbox (data sharing)

Every gated tool call sends one HTTPS request to the BLACK_WALL service. What it
carries depends on `inputMode`:

- **`metadata` (the default):** the tool *name*, plus a summary of its parameters
  — key names (clipped to 64 chars, max 50 keys), each value's JSON type and byte
  size, and the total payload size. Parameter **values are never transmitted**:
  no commands, no file contents, no URLs, no tokens.
- **`contents` (opt-in):** the actual parameters, size-capped at
  `maxInputBytes` (default 8 KiB) with long strings truncated. Choose this only
  where content-based red-flag detection is worth sharing tool payloads with the
  service, and treat the cap as a size guard, not redaction.

In both modes the `after_tool_call` outcome report carries only an outcome class
and divergence severity, not tool output. Support and data-handling questions:
<bluetier.operations@gmail.com>.

## Security properties

- **No credential over plaintext.** The API key is only sent over `https://` (or an
  explicit loopback `http://` for local testing); a misconfigured `http://` base URL
  is rejected *before* any request or `Authorization` header is emitted.
- **Fail-closed by default.** In enforce mode, an unreachable gate blocks the
  action rather than letting it run unscored; opting *out* (`failClosed: false`)
  is the explicit choice. Observe mode is a trial/rollout mode and never blocks —
  it is not an enforcement boundary, and the recommended sandboxed profile is
  `mode: enforce` with the defaults left on.
- **Metadata-only forecasts by default.** See *What leaves the sandbox* above;
  sharing tool-call contents with the service is opt-in per deployment.
- **Verifiable receipts.** Each receipt is signed over canonical hashes of the
  request and response; anyone can re-hash the bodies and verify the Ed25519
  signature against the published key at `/.well-known/blackwall-signing-keys.json`
  — no trust in any server required.

## Lifecycle: bring-up, verify, tear-down

```bash
export BLACKWALL_API_KEY=bw_live_…   # host-side only; never enters the sandbox
export SANDBOX_IMAGE=<your OpenClaw-capable sandbox image with the plugin baked in>

scripts/bring-up.sh                  # profile import -> provider create (key held
                                     #   gateway-side) -> sandbox create with
                                     #   policy.yaml + provider attached
scripts/verify.sh                    # unit tests + egress + injection probe +
                                     #   interception check (see below)
scripts/tear-down.sh                 # sandbox -> provider (-> --profile) teardown
```

### Install & enable (the plugin inside the sandbox)

Current-convention recipes bake agent plugins into the sandbox image rather than
mutating a live sandbox. Add this example's plugin directory (`index.ts`,
`openclaw.plugin.json`, `skills/`) to your OpenClaw sandbox image — e.g. a
`COPY` into the agent's plugin directory in your image's Dockerfile — and enable
plugin id `nemoclaw-blackwall-guard` in the agent's config. For a host-side
development loop *outside* NemoClaw, `scripts/install.sh` still copies the
plugin into `$OPENCLAW_PLUGIN_DIR` (default `~/.openclaw/extensions/`).

### Verification

Run `verify.sh` in three places:

- **From the repo checkout** — unit tests + endpoint reachability.
- **Inside the sandbox** — stage 3 proves whether the L7 proxy really injected
  the credential at egress: HTTP 2xx means the real key was substituted; a
  `401 invalid_api_key` means the placeholder passed through unreplaced; a
  `401 missing_api_key` means no Authorization header arrived at all.
- **Host-side with `SANDBOX_NAME` set** — stage 4 proves a real OpenClaw tool
  call is intercepted, by finding the hook's deterministic gate line
  (`[blackwall] <mode> · <tool> → <verdict>`) in the sandbox logs. If none has
  appeared yet, ask the sandboxed agent to run any tool and re-check.

## Validation

`index.test.ts` is a [Vitest](https://vitest.dev) suite covering the full
`before_tool_call` decision state machine (observe/enforce × GO/CAUTION/STOP ×
caution-action × forecast-error/fail-closed), the HTTPS-only credential guard
(including loopback and bypass cases), input minimization (metadata mode never
transmits parameter values), and the proxy CONNECT-header size cap. It stubs the
OpenClaw plugin SDK, so it runs in-repo with no host runtime:

```bash
npm install && npm test    # 27 tests
```

## License

Contributed under this repository's license (Apache-2.0).
