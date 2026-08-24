<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Build Remote Agent pairing

For an operator who already runs NemoClaw or OpenShell on a host, this recipe
pairs a phone running Build Remote Agent to host-side `gbr-agent` so the phone
can spectate that desktop agent session.

Build Remote Agent is an independent product by Linespotting AB. It is not
affiliated with NVIDIA, xAI, or SpaceX. Catalog placement is for discovery
only.

## Screenshot

This is a host command-line recipe. The block below is representative
terminal-result evidence after `gbr-agent` **v0.6.0** is installed from
https://grokbuildremote.com/ and `gbr-agent run` is listening on host
loopback. This repository change did not live-verify a NemoClaw sandbox.

```text
$ gbr-agent version
gbr-agent v0.6.0

$ curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8788/health
200
```

The version line confirms the pinned host agent. HTTP `200` on
`http://127.0.0.1:8788/health` confirms the host Bot API is listening on
loopback. The phone pair UI is not shown here.

## At A Glance

| Question | Answer |
| --- | --- |
| Category | Community Recipe |
| Contributor or provenance | Linespotting AB |
| Use this when | You already run NemoClaw or OpenShell on a host and want a phone spectator for that host's agent session. |
| You will get | A phone paired with host-side `gbr-agent` that can spectate the desktop session through loopback `127.0.0.1:8788` or optional host-side `gbr-mcp`. |
| Runs on | The same macOS, Windows, or Linux host that already runs NemoClaw or OpenShell. The phone runs Build Remote Agent. |
| Requires | A working NemoClaw or OpenShell host session; Build Remote Agent on the phone; MIT-licensed `gbr-agent` **v0.6.0** installed from https://grokbuildremote.com/. This recipe does not create a sandbox. |
| Verified on | Not yet verified. |
| Evidence level | local/static |
| Support and maturity | Best-effort community support. See the repository [support policy](../../../../SUPPORT.md). |
| External access, data, and actions | Host `gbr-agent pair` and `gbr-agent run` use the product's published pair flow and host loopback Bot API. This recipe does not copy `gbr-agent` into the OpenShell sandbox and does not add sandbox egress. Do not commit pairing secrets. No repository-documented usage cost. |
| Start here | [Start Here](#start-here) |
| Confirm success | [Verification](#verification) |

## Start Here

Install the MIT-licensed host agent **v0.6.0** from
https://grokbuildremote.com/ (the site's current install default). Confirm
that published pin before you run the site's OS-specific installer. Do not
pipe an unpinned live installer.

Run every command below on the **host**, not inside
`openshell sandbox exec`. Do not copy `gbr-agent` into the sandbox image.

1. Confirm the pinned host agent:

   ```bash
   gbr-agent version
   ```

   The output must include `v0.6.0` or newer.

2. Pair the phone with the existing product command. Use both the browser QR
   and the printed 8-character code. Do not add another pair protocol.

   ```bash
   gbr-agent pair
   ```

3. On the phone, open Build Remote Agent and choose **Scan QR from computer**,
   or type the 8-character code.

4. Leave the host agent running:

   ```bash
   gbr-agent run
   ```

5. Attach only host loopback or host-side `gbr-mcp`. After `gbr-agent run`:

   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8788/health
   ```

   Optional: run host-side `gbr-mcp` as documented on
   https://grokbuildremote.com/. Do not install `gbr-mcp` inside the OpenShell
   sandbox.

Keep Build Remote Agent on the host by default. The sandbox does not need
`gbr-agent`. Do not add sandbox egress to `127.0.0.1:8788` unless an existing
OpenShell policy already allows that host loopback path.

The phone is a spectator with veto. It is not the orchestrator. This recipe
does not replace NemoClaw, OpenClaw, or Hermes device or chat pairing.

## Verification

**Evidence level:** local/static

This contribution did not live-verify a NemoClaw sandbox. The commands below
are the documented host checks.

On the host, after [Start Here](#start-here):

```bash
gbr-agent version
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8788/health
```

Confirm `gbr-agent` is not present inside the sandbox image or
`openshell sandbox exec`. After a live pair, the phone shows the paired host
session.

**Expected result:**

```text
gbr-agent v0.6.0
200
```

**This verifies:** The host agent pin and loopback Bot API listener, when those
commands are run on a host that already has `gbr-agent` v0.6.0 and
`gbr-agent run` active.

**This does not verify:** A live NemoClaw or OpenShell sandbox, phone QR or
8-character pairing, `gbr-mcp`, sandbox policy, or any inject or veto path.

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
  NemoClaw, OpenShell, or the phone pair UI.
- The host agent is an independent MIT-licensed tool. NVIDIA does not maintain
  it.
- Default attach is host loopback `127.0.0.1:8788`. Optional `gbr-mcp` is
  host-side only.
- This recipe does not vendor `gbr-agent` or `gbr-mcp` and does not change
  sandbox policy.
