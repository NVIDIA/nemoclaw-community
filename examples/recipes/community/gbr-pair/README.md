<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Build Remote Agent pairing (host tool)

Pair a phone running **Build Remote Agent** to the **host** that runs NemoClaw /
OpenShell. The phone spectates (and can inject into) a desktop agent session
through free MIT `gbr-agent`. Protocol `gbr/1`.

This is an independent community recipe, not a supported NemoClaw product
surface. Catalog placement is for discovery only.

Independent product by Linespotting AB. Not affiliated with NVIDIA, xAI, or SpaceX.

Website: https://grokbuildremote.com/
Agent: https://github.com/LinespottingOrg/GrokBuildRemote-Agents (MIT)

## Scope

- Install and run `gbr-agent` **on the host** (Mac/PC), not inside the OpenShell sandbox.
- Pair the phone with `gbr-agent pair` (browser QR **and** printed 8-char code).
- Attach only `http://127.0.0.1:8788` (after `gbr-agent run`) or stdio `gbr-mcp`.
- Phone is spectator + veto, not orchestrator.

It does not:

- copy `gbr-agent` into the sandbox image
- invent a second pair protocol
- replace NemoClaw / OpenClaw / Hermes device or chat pairing
- require mailbox keys, `X-GBR-Key`, or `~/.gbr/` in this repository

## Provenance And Intended Users

- Provenance: independent community contribution
- Intended users: operators who already run NemoClaw or OpenShell on a host and want a phone spectator on that host's agent session
- Support boundary: operators remain responsible for installing `gbr-agent`, keeping it on loopback, and not committing relay keys

## Requirements

- Host with NemoClaw / OpenShell already working (this recipe does not create a sandbox)
- `gbr-agent` **v0.6.0+** on the same host
- Optional: Node.js, to run stdio `gbr-mcp`

## Credentials And Secret Handling

Do not put mailbox keys, `X-GBR-Key`, or `device.json` in this recipe, in sandbox env, or in git.

If a remote bot must use the relay, copy the key on the phone under **Settings → Bot API** and keep it on the operator machine only.

## Startup

On the **host** (not in `openshell sandbox exec`):

```bash
# macOS / Linux
curl -fsSL https://grokbuildremote.com/install.sh | bash
gbr-agent version          # must print v0.6.0 or newer
gbr-agent pair             # QR in browser + printed 8-char code
gbr-agent run              # leave running
```

```powershell
# Windows
irm https://grokbuildremote.com/install.ps1 | iex
gbr-agent version
gbr-agent pair
gbr-agent run
```

Phone: Build Remote Agent → **Scan QR from computer** (or type the 8-char code).
Unpair in Settings before changing PCs. Force-close is not enough.

## Attach

After `gbr-agent run` on the host:

```bash
curl -sS http://127.0.0.1:8788/health
curl -sS http://127.0.0.1:8788/v1/sessions
```

Optional MCP stdio (host-side, never a sandbox binary):

```bash
git clone https://github.com/LinespottingOrg/GrokBuildRemote-Agents.git
cd GrokBuildRemote-Agents/mcp/gbr-mcp && npm install
node bin/gbr-mcp.js --diagnose
```

Point the sandboxed agent at **host** loopback only if your OpenShell policy already allows it. Default: keep GBR entirely on the host; the sandbox does not need `gbr-agent`.

## Verification

1. `gbr-agent version` prints v0.6.0 or newer.
2. `curl -sS http://127.0.0.1:8788/health` succeeds on the host.
3. Phone shows the paired session after scan/code.
4. Confirm `gbr-agent` is **not** present inside the sandbox image / `openshell sandbox exec`.

## Teardown

1. Unpair in the phone app Settings.
2. Stop `gbr-agent run` on the host (Ctrl-C, or stop the LaunchAgent/service).
3. No sandbox files to remove; this recipe does not install in-sandbox skills.

## Loop

diagnose → open/attach → lock → inject → wait idle → harvest excerpt → iterate or close

Docs: https://github.com/LinespottingOrg/GrokBuildRemote-Agents/blob/main/docs/BOT-API.md
