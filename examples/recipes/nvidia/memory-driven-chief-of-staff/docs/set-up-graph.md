<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Connecting a mailbox

Fifteen minutes, most of it waiting for a sign-in page. What you end up with is
a credential the sandbox never holds and a collector that reads your inbox and
writes nothing back to it.

## What holds the credential

The OpenShell gateway does, and it renews it. The sandbox receives
`openshell:resolve:env:…` — sixty-odd bytes of placeholder — which the gateway
substitutes at the egress boundary. A collector that leaked its environment
would leak a string that is useless anywhere else.

This is the arrangement [#122](https://github.com/NVIDIA/nemoclaw-community/issues/122)
decision 1 settled on. The alternative was MSAL-managed renewal with an
encrypted token cache, which keeps a recipe self-contained at the cost of the
refresh token living inside the sandbox — where an encrypted cache is a
mitigation rather than a boundary.

## The one thing that goes wrong

An application permission instead of a delegated one. `Mail.Read` exists in
both flavours, and the application flavour reads every mailbox in the tenant.
The collector refuses it — a token whose `/me` has no address is not a
delegated token — but it is worth not requesting in the first place.

## Where each step runs

| Step | Where |
| --- | --- |
| Register the application | Your browser, at the Entra admin centre |
| `scripts/setup-graph.sh` | The **host**, where `openshell` is |
| Signing in with the device code | Any machine you trust |
| `ingest_graph.py` | The **sandbox**, where `hermes` is |

## 1. Encrypted storage

The setup script checks this before anything else, and it is the same check
the Slack connector uses. See [encrypted-storage.md](encrypted-storage.md) for
what it can and cannot verify, and why the path has to be named rather than
guessed.

## 2. Register an application

At the Microsoft Entra admin centre, register an application with:

- **Delegated** `Mail.Read` and `offline_access`. Delegated, not application.
- **Public client flows enabled** — the device-code flow needs it, and it is
  off by default.
- No redirect URI. There is no browser on the machine running the collector,
  which is why this uses device code rather than a redirect.

Take the application (client) id and the directory (tenant) id.

## 3. Run the setup

On the host:

```bash
cd <this recipe>
GRAPH_CLIENT_ID=<client id> GRAPH_TENANT_ID=<tenant id> \
    SANDBOX_STORAGE_PATH=<path> bash scripts/setup-graph.sh
```

It prints a short code and an address. Open the address anywhere you trust,
enter the code, approve. The terminal waits; nothing is stored until you
finish, and the refresh token that comes back goes to the gateway rather than
into the sandbox.

## 4. Choose how far back the first synchronisation reaches

Seven days by default. Fourteen and thirty are the other usual answers, and any
number from 1 to 3650 works:

```bash
ENV=$(hermes -p <profile> config env-path)
echo 'GRAPH_BACKFILL_DAYS=14' >> "$ENV"
```

That file is the supported path and the only one that persists: `hermes cron
create` takes no environment, so a variable exported in a shell reaches the run
in front of you and nothing scheduled.

**The window decides where the first round starts, and nothing else.** The
delta cursor it produces carries no filter, so once the baseline exists every
later change in the folder is reported — including an older message being
deleted. Choosing seven days is choosing where to begin, not choosing to be
told less afterwards.

A wider window costs a longer first synchronisation. Each tick spends a bounded
number of requests and saves its place, so a first round over thirty days
finishes across several ticks rather than in one.

## 5. Verify

Inside the sandbox:

```bash
python3 <profile home>/scripts/ingest_graph.py
```

A configured mailbox reports what it did:

```json
{"source": "email", "scope": "inbox", "added": 42, "removed": 0,
 "pages": 3, "resumed": false, "complete": true, "synchronised": true,
 "backfill_days": 7}
```

`complete: false` with `synchronised: false` means the first round is still
running and will continue on the next tick — expected on a wide window, not a
failure. `resumed: true` says this tick continued one.

### When it fails

| Exit | Means |
| --- | --- |
| `0` | Collected, or never configured. Never configured is a state, not a fault |
| `1` | Something else; the message says what |
| `2` | The credential is missing, wrong, or was refused |
| `3` | Rate limited before the work finished |
| `4` | The token works but is not a delegated mailbox token |

## What the schedule does with it

The intake job runs the collector as its pre-step, every thirty minutes. A tick
that collects nothing new emits the wake gate and costs no model call.

## Deletions

Graph reports them, so this acts on them. A message deleted in the mailbox is
tombstoned locally on the next synchronisation and its body cleared at once,
rather than ageing out on the retention pass a month later. The row itself
stays: obligations and events hang off it, and removing it would break the
record of why something was ranked or ignored.

Slack has no equivalent on the surface this recipe reads, which is why the two
connectors differ here — see [data-lifecycle.md](data-lifecycle.md).

## Revoking

Remove the application's consent in your Microsoft account, then:

```bash
openshell sandbox provider detach <sandbox> <provider>
openshell provider delete <provider>
```

That ends collection. It does not remove what was already collected: the
messages read up to that point are still in the store. `reset.py --yes` removes
them, and `export_store.py` writes out a copy first if you want one — both in
[data-lifecycle.md](data-lifecycle.md). Revoking and erasing are separate
actions, and doing one is easy to mistake for both.
