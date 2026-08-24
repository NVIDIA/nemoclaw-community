<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Build Remote Agent pairing

For an operator who already has NemoClaw or OpenShell open as a **host
terminal window**, this recipe installs host-side `gbr-agent` so a phone can
see that TTY the same way it sees any other host terminal.

`gbr-agent` is a **host tool**. It discovers terminal windows on the host. It
does not enter the OpenShell sandbox. There is no NemoClaw-specific adapter,
no in-sandbox `gbr-agent`, and no fourth pair protocol. If NemoClaw or
OpenShell is not a TTY on that host, the phone does not see it.

Build Remote Agent is an independent product by Linespotting AB. It is not
affiliated with NVIDIA, xAI, or SpaceX. Catalog placement is for discovery
only.

## Screenshot

This is a host command-line recipe. The block below is terminal-result
evidence captured on this contributor host after downloading GitHub Release
**v0.6.0** `gbr-agent-darwin-arm64` and checking the hard-coded digest. This
change did **not** live-run NemoClaw or OpenShell.

```text
$ printf '%s  %s\n' '7baa1a8e214cd71b60e3f2b5063713e00ff740939749c3cab3d702784a1432f8' 'gbr-agent-darwin-arm64' | shasum -a 256 -c -
gbr-agent-darwin-arm64: OK

$ ./gbr-agent-darwin-arm64 version
gbr-agent v0.6.0 commit=903806c date=2026-08-21T15:57:34Z darwin/arm64
```

The checksum line confirms the pinned GitHub Release asset. The version line
confirms that binary. The phone pair UI is not shown. A NemoClaw or OpenShell
session is not shown.

## At A Glance

| Question | Answer |
| --- | --- |
| Category | Partner Recipe |
| Contributor or provenance | Linespotting AB |
| Use this when | You want a phone or the host Bot API to see **host terminal windows**, including a NemoClaw or OpenShell TTY if one is already open on that host. |
| You will get | Host-side `gbr-agent` **v0.6.0** that discovers host TTYs. This is a host TTY spectator next to NemoClaw, not a NemoClaw integration. |
| Runs on | macOS, Windows, or Linux host. The optional phone app runs on iOS or Android. |
| Requires | GitHub Release **v0.6.0** `gbr-agent` with the hard-coded digest below. NemoClaw or OpenShell is optional: if present, it is only another host TTY. The paid phone app is optional for host-only Bot API use. |
| Verified on | Not yet verified on NemoClaw or OpenShell. Checksum and version captured on macOS darwin/arm64 from GitHub Release v0.6.0 (`commit=903806c`). |
| Evidence level | local/static |
| Support and maturity | Best-effort community support. See the repository [support policy](../../../../../SUPPORT.md). |
| External access, data, and actions | Outbound HTTPS to `https://gbr-relay.ekobrott.workers.dev` (session titles and agent output for the paired mailbox). Phone can inject text into discovered host TTYs (`POST /v1/inject`). Loopback `127.0.0.1:8788` is unauthenticated by default. macOS Accessibility is required for TTY inject. Do not commit mailbox keys. Host `gbr-agent` is MIT. The mobile Build Remote Agent app is a paid closed-source spectator and is not required for host-only Bot API use. |
| Start here | [Start Here](#start-here) |
| Confirm success | [Verification](#verification) |

## Security and external services

Read this section before you run any command below.

- **Outbound HTTPS relay.** `gbr-agent pair` and `gbr-agent run` send `gbr/1`
  envelopes to `https://gbr-relay.ekobrott.workers.dev`. Those envelopes can
  include session titles and agent output for the paired mailbox. The relay
  always requires the `X-GBR-Key` request header. Do not commit mailbox keys,
  `X-GBR-Key`, or `device.json`.
- **Remote inject.** A paired phone can inject text into discovered host
  terminal windows through `POST /v1/inject`. Treat that as host keyboard
  authority, not a read-only spectator.
- **Loopback Bot API.** `http://127.0.0.1:8788` is **unauthenticated by
  default**. Set the environment variable `GBR_BOT_REQUIRE_KEY=1` if loopback
  callers must present the mailbox key. The relay path still requires
  `X-GBR-Key` even when loopback does not.
- **macOS Accessibility.** TTY inject on macOS needs Accessibility permission
  for `gbr-agent`. Grant it only if you want inject. Capture of terminal
  titles can still work without it.
- **License boundary.** Desktop `gbr-agent` is MIT. The mobile **Build Remote
  Agent** app is a paid closed-source spectator. It is not required for
  host-only Bot API use.
- **No in-sandbox agent.** Do not copy `gbr-agent` into the OpenShell sandbox
  image. Do not add a NemoClaw-specific pair protocol. Pairing is only
  `gbr-agent pair` (browser QR and printed 8-character code) and
  `gbr-agent run`.

## Architecture

```text
phone (optional paid Build Remote Agent app)
        |
        |  HTTPS gbr/1 envelopes (titles, agent output)
        v
https://gbr-relay.ekobrott.workers.dev     (always X-GBR-Key)
        ^
        |
host
  gbr-agent  -- discover / inject -->  host TTY windows
       |                               (Terminal, iTerm, Windows Terminal, ...)
       |                               If NemoClaw or OpenShell is one of
       |                               those TTYs, it is visible like any
       |                               other TTY. There is no adapter.
       v
  127.0.0.1:8788 Bot API               (unauthenticated by default)
  optional host-side gbr-mcp

OpenShell sandbox                      (unchanged; no gbr-agent inside)
  NemoClaw / OpenClaw / Hermes
```

NemoClaw keeps its own sandbox. `gbr-agent` stays on the host and talks to
host TTYs.

## Start Here

Do not `curl` a website `install.sh`. Install the GitHub Release **v0.6.0**
binary and check the **hard-coded** digest. Do not trust a `SHA256SUMS` file
downloaded from the same release as the only check.

Run every command on the **host**, not inside `openshell sandbox exec`.

1. Install `gbr-agent` v0.6.0 (darwin-arm64 shown). Swap the asset name and
   digest for your platform from the table below.

   ```bash
   VER=v0.6.0
   BASE=https://github.com/LinespottingOrg/GrokBuildRemote-Agents/releases/download/$VER
   SHA=7baa1a8e214cd71b60e3f2b5063713e00ff740939749c3cab3d702784a1432f8
   curl -fsSL -o gbr-agent-darwin-arm64 "$BASE/gbr-agent-darwin-arm64"
   printf '%s  %s\n' "$SHA" 'gbr-agent-darwin-arm64' | shasum -a 256 -c -
   mkdir -p ~/.local/bin
   install -m 0755 gbr-agent-darwin-arm64 ~/.local/bin/gbr-agent
   export PATH="$HOME/.local/bin:$PATH"
   gbr-agent version   # v0.6.0
   ```

   GitHub Release v0.6.0 SHA-256 (hard-coded; verified by downloading each
   asset on 2026-08-24):

   | Asset | SHA-256 |
   | --- | --- |
   | `gbr-agent-darwin-amd64` | `62673a6856342a87d4a2a659bc1de92200aa19a5b60d88d252254940820f0b7f` |
   | `gbr-agent-darwin-arm64` | `7baa1a8e214cd71b60e3f2b5063713e00ff740939749c3cab3d702784a1432f8` |
   | `gbr-agent-linux-amd64` | `fb54724367882497f2e8e05e40ecdeb4be29e008e6c865fc5c426cf464e6ad6e` |
   | `gbr-agent-linux-arm64` | `9e9d7ca45bb0c4ded9d04226136013e9b64ae30f16bcf03069d35e9c38171cb9` |
   | `gbr-agent-windows-amd64.exe` | `40355b2be6cd68f3be68f2a06dfd30307ec1a60f16f87f1d6174012b35aa4a49` |
   | `gbr-agent-windows-arm64.exe` | `8fb9efcbc7e2ac91c11964944bf0f45e31bb23f4356d9dcb4b305d7cb9b0fe8c` |

   On Linux, `sha256sum -c` is an equivalent check. Abort if the digest does
   not match. Do not continue on a failed check.

2. Pair the phone with the existing product command. Use both the browser QR
   and the printed 8-character code. Do not add another pair protocol.

   ```bash
   gbr-agent pair
   ```

3. On the phone, open Build Remote Agent and choose **Scan QR from computer**,
   or type the 8-character code. Skip this step for host-only Bot API use.

4. Leave the host agent running. Set `GBR_BOT_REQUIRE_KEY=1` if loopback
   callers must present the mailbox key.

   ```bash
   gbr-agent run
   ```

5. Confirm the host Bot API listener:

   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8788/health
   ```

   Optional: run host-side `gbr-mcp` from the same v0.6.0 source tag. Do not
   install `gbr-mcp` inside the OpenShell sandbox.

Keep `gbr-agent` on the host. The sandbox does not need it. Do not add
sandbox egress to `127.0.0.1:8788` unless an existing OpenShell policy already
allows that host loopback path.

The phone is not the NemoClaw orchestrator. This recipe does not replace
NemoClaw, OpenClaw, or Hermes device or chat pairing.

## Verification

**Evidence level:** local/static

This contribution did not live-verify NemoClaw or OpenShell. This host has
neither `nemoclaw` nor `openshell` on `PATH`. The commands below are the
documented host checks for the pinned binary.

On the host, after step 1 of [Start Here](#start-here):

```bash
printf '%s  %s\n' '7baa1a8e214cd71b60e3f2b5063713e00ff740939749c3cab3d702784a1432f8' 'gbr-agent-darwin-arm64' | shasum -a 256 -c -
gbr-agent version
```

**Expected result:**

```text
gbr-agent-darwin-arm64: OK
gbr-agent v0.6.0 commit=903806c date=2026-08-21T15:57:34Z darwin/arm64
```

(The date and commit fields can vary by platform. The version must be
`v0.6.0`, not "v0.6.0 or newer".)

After `gbr-agent run`, `curl` to `http://127.0.0.1:8788/health` can return
`200`. This contribution did not capture that result from the pinned v0.6.0
binary.

**This verifies:** The GitHub Release v0.6.0 darwin-arm64 asset matches the
hard-coded digest, and that binary reports `v0.6.0`.

**This does not verify:** A live NemoClaw or OpenShell sandbox, a GPU box, a
phone QR or 8-character pair, TTY inject, the relay path, `gbr-mcp`, sandbox
policy, loopback authentication, or any claim that the phone spectates a
NemoClaw session as a product surface. If a maintainer requires live
end-to-end NemoClaw evidence, this recipe cannot supply it from this host.

## Credentials And Secret Handling

Do not put mailbox keys, `X-GBR-Key`, `device.json`, or other pairing secrets
in this recipe, in sandbox environment variables, or in git.

Pairing material stays on the phone and the host. This recipe does not require
those files in the repository.

## Teardown And Cleanup

1. Unpair in the phone app Settings. Force-close is not enough before you
   change hosts.
2. Stop `gbr-agent run` on the host.
3. No in-sandbox skill files to remove. This recipe does not install any.

## Known Limitations

- Evidence level is `local/static`. This contribution did not live-verify
  NemoClaw, OpenShell, phone pairing, inject, or the relay.
- This is a host TTY spectator next to NemoClaw, not a NemoClaw integration.
- The host agent is an independent MIT-licensed tool. NVIDIA does not maintain
  it.
- Default attach is host loopback `127.0.0.1:8788`. Optional `gbr-mcp` is
  host-side only.
- This recipe does not vendor `gbr-agent` or `gbr-mcp` and does not change
  sandbox policy.
