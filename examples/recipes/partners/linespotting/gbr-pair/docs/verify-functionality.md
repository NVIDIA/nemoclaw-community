<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Captured verification — gbr-pair

Sanitized transcript from the contributor host on 2026-08-24. Mailbox ids,
keys, and private paths are omitted.

## Layer A — pinned binary

PowerShell, GitHub Release **v0.6.0** `gbr-agent-windows-amd64.exe`:

```text
SHA256  40355b2be6cd68f3be68f2a06dfd30307ec1a60f16f87f1d6174012b35aa4a49  OK

.\gbr-agent-windows-amd64.exe version
gbr-agent v0.6.0 commit=903806c date=2026-08-21T15:57:30Z windows/amd64
```

## Layer B — host Bot API, TTY discover, inject, relay

A running `gbr-agent` **v0.6.0** on Windows amd64:

```text
GET http://127.0.0.1:8788/health
{"ok":true,"version":"v0.6.0","health":{"quality":"ok","relay_quality":"ok"}}
paired phone / tablet app  online=true

GET http://127.0.0.1:8788/v1/sessions
session_id=windows-terminal-bd010e  title=gbr-pair-verify-tty

POST http://127.0.0.1:8788/v1/inject
{"ok":true,"session_id":"windows-terminal-bd010e","local":true,"queued":false}

GET https://gbr-relay.ekobrott.workers.dev/v1/bot
{"ok":true,"service":"gbr-relay-bot","version":"0.6.0"}

GET https://gbr-relay.ekobrott.workers.dev/v1/mb/gbr-example/poll
HTTP 401
```

`GET /v1/bot` is discovery and does not require a key. `GET .../poll` without
`X-GBR-Key` returned 401. `POST /v1/mb/:id/pair` is not called here; the
vendor relay README documents that pair is unauthenticated and throttled
because it issues the key.

Inject typed into a discovered host TTY titled `gbr-pair-verify-tty`. Console
capture after inject returned `The handle is invalid` on Windows Terminal
(`method=attachconsole`). The inject call itself returned `ok: true`.

## Layer C — NemoClaw / OpenShell sandbox

Not captured live. This host has neither `nemoclaw` nor `openshell` on `PATH`.
WSL Ubuntu is present but has no NemoClaw, OpenShell, or Docker install.

The independently deployable path is:

```bash
export SANDBOX_NAME=gbr-pair
bash scripts/onboard.sh
openshell sandbox exec --name gbr-pair -- /sandbox/bin/gbr-operator-ping
bash scripts/verify.sh
```

`onboard.sh` adds `policy.yaml` with `nemoclaw <sandbox> policy-add --from-file`
and copies `skills/gbr-remote-operator/` into the sandbox. The policy allows
GET to `host.openshell.internal:8788` only. It does not allow POST `/v1/inject`
and does not allow `gbr-relay.ekobrott.workers.dev`.
