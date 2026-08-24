<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Build Remote Agent remote operator

For an operator who runs a NemoClaw/OpenClaw agent inside OpenShell, this
recipe adds a remote-operator skill and a GET-only host Bot API policy, then
runs host-side `gbr-agent` so a paired phone can inject into the NemoClaw TTY.

The sandboxed agent can ping the host Bot API. It cannot inject keystrokes. It
cannot reach the vendor relay. Inject is host-keyboard authority on the host
and on the paired **remote-control client**.

Build Remote Agent is an independent product by Linespotting AB. It is not
affiliated with NVIDIA, xAI, or SpaceX. Catalog placement is for discovery
only.

## Screenshot

This is a command-line recipe. The block below is terminal-result evidence
captured on a Windows amd64 contributor host on 2026-08-24. Mailbox ids and
keys are omitted. The NemoClaw sandbox attach was not live-run on this host;
that path is `scripts/onboard.sh`.

```text
Get-FileHash -Algorithm SHA256 gbr-agent-windows-amd64.exe
SHA256  40355b2be6cd68f3be68f2a06dfd30307ec1a60f16f87f1d6174012b35aa4a49  OK

.\gbr-agent-windows-amd64.exe version
gbr-agent v0.6.0 commit=903806c date=2026-08-21T15:57:30Z windows/amd64

GET http://127.0.0.1:8788/health
{"ok":true,"version":"v0.6.0","health":{"quality":"ok","relay_quality":"ok"}}

GET http://127.0.0.1:8788/v1/sessions
session_id=windows-terminal-bd010e  title=gbr-pair-verify-tty

POST http://127.0.0.1:8788/v1/inject
{"ok":true,"session_id":"windows-terminal-bd010e","local":true}

GET https://gbr-relay.ekobrott.workers.dev/v1/bot
{"ok":true,"service":"gbr-relay-bot","version":"0.6.0"}

GET https://gbr-relay.ekobrott.workers.dev/v1/mb/gbr-example/poll
HTTP 401
```

The checksum line confirms the pinned GitHub Release asset. Health and
`relay_quality` confirm the running v0.6.0 agent reached the vendor relay.
Sessions and inject confirm TTY discovery and host-keyboard inject. Relay
discovery does not require a key; poll without a key returned 401.

## At A Glance

| Question | Answer |
| --- | --- |
| Category | Partner Recipe |
| Contributor or provenance | Linespotting AB |
| Use this when | You want a NemoClaw/OpenClaw sandbox to ping a host operator, and a phone to inject into the NemoClaw TTY, without giving the sandbox a route to the vendor relay. |
| You will get | An OpenClaw skill, an additive OpenShell policy, and host-side `gbr-agent` **v0.6.0**. |
| Runs on | Host `gbr-agent`: macOS, Windows, or Linux. NemoClaw/OpenShell sandbox attach: macOS, Linux, or Windows Subsystem for Linux (WSL). The optional phone app runs on iOS or Android. |
| Requires | GitHub Release **v0.6.0** `gbr-agent` with the hard-coded digest below. NemoClaw and OpenShell on `PATH` for sandbox attach. The paid phone app is optional for host-only Bot API use. |
| Verified on | Windows amd64 host path: GitHub Release v0.6.0 checksum (`commit=903806c`), live Bot API, TTY discover, inject, and relay discovery/401. NemoClaw/OpenShell sandbox attach not live-run (`nemoclaw` and `openshell` were not on `PATH`). |
| Evidence level | integration |
| Support and maturity | Best-effort community support. See the repository [support policy](../../../../../SUPPORT.md). |
| External access, data, and actions | Host `gbr-agent` sends `gbr/1` envelopes to `https://gbr-relay.ekobrott.workers.dev` (session titles and agent output for the paired mailbox). The paired remote-control client can inject text into discovered host TTYs. Loopback `127.0.0.1:8788` is unauthenticated by default. macOS Accessibility is required for TTY inject. The OpenShell policy allows GET to `host.openshell.internal:8788` only. Do not commit mailbox keys. Host `gbr-agent` is MIT. The mobile Build Remote Agent app is a paid closed-source remote-control client and is not required for host-only Bot API use. |
| Start here | [Start Here](#start-here) |
| Confirm success | [Verification](#verification) |

## Security and external services

Read this section before you run any command below.

- **Outbound HTTPS relay (host only).** `gbr-agent pair` and `gbr-agent run`
  send `gbr/1` envelopes to `https://gbr-relay.ekobrott.workers.dev`. Those
  envelopes can include session titles and agent output for the paired
  mailbox. Auth is not uniform:
  - `POST /v1/mb/:id/pair` is unauthenticated and throttled (12/hour/mailbox)
    because it issues the mailbox key.
  - Post-pair `push`, `poll`, and `ack` require `X-GBR-Key`.
  - Vendor reference:
    <https://github.com/LinespottingOrg/GrokBuildRemote-Agents/blob/v0.6.0/relay/README.md>
  Do not commit mailbox keys, `X-GBR-Key`, or `device.json`.
- **Remote inject is host-keyboard authority.** A paired phone is a
  **remote-control client**. It can inject text into discovered host terminal
  windows through `POST /v1/inject`. That is not read-only. Treat a paired
  device as equivalent to sitting at the host keyboard.
- **Loopback Bot API.** `http://127.0.0.1:8788` is **unauthenticated by
  default**. Keep that default when the OpenShell skill must GET the Bot API;
  the sandbox has no mailbox key. Set the environment variable
  `GBR_BOT_REQUIRE_KEY=1` only for host-only Bot API use with no sandbox
  attach.
- **OpenShell boundary.** `policy.yaml` allows GET to
  `host.openshell.internal:8788` (`/health`, `/v1/sessions`, `/v1/status`).
  It does not allow POST `/v1/inject`. It does not allow
  `gbr-relay.ekobrott.workers.dev`. Do not copy `gbr-agent` into the sandbox
  image.
- **macOS Accessibility.** TTY inject on macOS needs Accessibility permission
  for `gbr-agent`. Grant it only if you want inject. Capture of terminal
  titles can still work without it.
- **License boundary.** Desktop `gbr-agent` is MIT. The mobile **Build Remote
  Agent** app is a paid closed-source remote-control client. It is not
  required for host-only Bot API use.

## Architecture

```text
phone (optional paid Build Remote Agent app)
  remote-control client — host-keyboard inject
        |
        |  HTTPS gbr/1
        |  POST /v1/mb/:id/pair     no key (issues the key; throttled)
        |  push / poll / ack        X-GBR-Key required
        v
https://gbr-relay.ekobrott.workers.dev
        ^
        |  host only — no sandbox route
host
  gbr-agent  -- discover / inject -->  host TTY
       |                               (NemoClaw CLI / OpenShell gateway TTY)
       v
  127.0.0.1:8788 Bot API               (unauthenticated by default)

OpenShell sandbox                      (policy-enforced)
  OpenClaw / Hermes agent
    skill gbr-remote-operator
      GET host.openshell.internal:8788/health
      GET host.openshell.internal:8788/v1/sessions
      no POST /v1/inject
      no vendor relay
```

NemoClaw keeps the sandbox. `gbr-agent` stays on the host. The skill is the
harness integration. The policy is the OpenShell boundary.

## Start Here

Do not `curl` a website `install.sh`. Install the GitHub Release **v0.6.0**
binary and check the **hard-coded** digest. Do not trust a `SHA256SUMS` file
downloaded from the same release as the only check.

Run host commands on the **host**, not inside `openshell sandbox exec`.

### 1. Install host `gbr-agent` v0.6.0

**PowerShell (Windows):**

```powershell
cd examples/recipes/partners/linespotting/gbr-pair
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-gbr-agent.ps1
```

**bash (macOS / Linux / WSL):**

```bash
cd examples/recipes/partners/linespotting/gbr-pair
bash scripts/install-gbr-agent.sh
```

GitHub Release v0.6.0 SHA-256 (hard-coded; Windows amd64 re-checked on
2026-08-24; other hashes from the same release assets):

| Asset | SHA-256 |
| --- | --- |
| `gbr-agent-darwin-amd64` | `62673a6856342a87d4a2a659bc1de92200aa19a5b60d88d252254940820f0b7f` |
| `gbr-agent-darwin-arm64` | `7baa1a8e214cd71b60e3f2b5063713e00ff740939749c3cab3d702784a1432f8` |
| `gbr-agent-linux-amd64` | `fb54724367882497f2e8e05e40ecdeb4be29e008e6c865fc5c426cf464e6ad6e` |
| `gbr-agent-linux-arm64` | `9e9d7ca45bb0c4ded9d04226136013e9b64ae30f16bcf03069d35e9c38171cb9` |
| `gbr-agent-windows-amd64.exe` | `40355b2be6cd68f3be68f2a06dfd30307ec1a60f16f87f1d6174012b35aa4a49` |
| `gbr-agent-windows-arm64.exe` | `8fb9efcbc7e2ac91c11964944bf0f45e31bb23f4356d9dcb4b305d7cb9b0fe8c` |

Abort if the digest does not match. Do not continue on a failed check.

### 2. Pair the remote-control client

This step talks to the vendor relay. `POST /v1/mb/:id/pair` is unauthenticated
and throttled because it issues the mailbox key. After that, push, poll, and
ack require `X-GBR-Key`.

```bash
gbr-agent pair
```

On the phone, open Build Remote Agent and choose **Scan QR from computer**,
or type the 8-character code. Skip this step for host-only Bot API use.

### 3. Leave the host agent running

```bash
gbr-agent run
```

### 4. Confirm the host Bot API

```bash
curl -sS http://127.0.0.1:8788/health
curl -sS http://127.0.0.1:8788/v1/sessions
```

On Windows PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/health
Invoke-RestMethod http://127.0.0.1:8788/v1/sessions
```

### 5. Attach the NemoClaw / OpenShell sandbox

Requires `nemoclaw` and `openshell` on `PATH` (macOS, Linux, or WSL). Native
Windows OpenShell is not the documented path.

```bash
export SANDBOX_NAME=gbr-pair
# Create the sandbox first if it does not exist, then:
bash scripts/onboard.sh
openshell sandbox exec --name gbr-pair -- /sandbox/bin/gbr-operator-ping
```

`onboard.sh` adds `policy.yaml` with `nemoclaw <sandbox> policy-add --from-file`
and copies the skill. The sandbox GET-only route is
`host.openshell.internal:8788`. Do not add sandbox egress to the vendor relay.

### 6. Inject from the remote-control client

On the phone, select the NemoClaw TTY and type. That is host-keyboard
authority. The sandboxed agent does not inject.

## Verification

**Evidence level:** integration

The full transcript is in
[docs/verify-functionality.md](docs/verify-functionality.md).

On Windows:

```powershell
cd examples/recipes/partners/linespotting/gbr-pair
.\scripts\verify.ps1
```

On macOS, Linux, or WSL:

```bash
cd examples/recipes/partners/linespotting/gbr-pair
bash scripts/verify.sh
```

**Expected result:**

```text
PASS: gbr-pair verification
```

Static checks must pass. Host Bot API and relay checks pass when `gbr-agent`
is running. Sandbox attach is SKIP when `nemoclaw` and `openshell` are not on
`PATH`.

**This verifies:** The recipe files (policy, skill, agents manifest, scripts)
are present and GET-only against the host Bot API. On the captured Windows
host: the v0.6.0 GitHub Release checksum, a live Bot API, TTY discovery,
inject `ok: true` into `gbr-pair-verify-tty`, relay discovery without a key,
and poll without a key returning 401.

**This does not verify:** A live `nemoclaw onboard` / `openshell sandbox exec`
on this contributor host, a GPU box, macOS Accessibility, or
`GBR_BOT_REQUIRE_KEY=1`. Layer C remains scripted in `scripts/onboard.sh`.

## Credentials And Secret Handling

Do not put mailbox keys, `X-GBR-Key`, `device.json`, or other pairing secrets
in this recipe, in sandbox environment variables, or in git.

Pairing material stays on the phone and the host. Copy `.env.example` to
`.env` for `SANDBOX_NAME` only. `.env` is gitignored.

## Teardown And Cleanup

```bash
bash scripts/teardown.sh
```

Then:

1. Unpair in the phone app Settings. Force-close is not enough before you
   change hosts.
2. Stop `gbr-agent run` on the host.
3. `teardown.sh` removes the in-sandbox skill. It does not stop `gbr-agent`
   unless `GBR_TEARDOWN_STOP_AGENT=1`.

## Known Limitations

- Evidence level is `integration`. Host Bot API, TTY discover, inject, and
  relay were captured on Windows amd64. NemoClaw/OpenShell sandbox attach was
  not live-run on this host.
- Native Windows is documented for host `gbr-agent` only. Sandbox attach uses
  WSL, macOS, or Linux.
- Windows Terminal inject can return `ok: true` while console capture reports
  `The handle is invalid`.
- The host agent is an independent MIT-licensed tool. NVIDIA does not maintain
  it.
- This recipe does not vendor `gbr-agent` and does not replace NemoClaw,
  OpenClaw, or Hermes device pairing.
