<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Connecting a mailbox

Fifteen minutes, most of it waiting for a sign-in page. On the supported path,
what you end up with is a credential the sandbox never holds and a collector
that reads your inbox and writes nothing back to it.

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

## Request delegated permissions

An application permission instead of a delegated one. `Mail.Read` exists in
both flavours, and the application flavour reads every mailbox in the tenant.
The collector refuses it — a token whose `/me` has no address is not a
delegated token — but it is worth not requesting in the first place.

## Provider provenance is an operator check in this version

The provider profile in this checkout describes the intended boundary; it is
not proof of which provider is active on a particular sandbox. The current
collector reads `MS_GRAPH_ACCESS_TOKEN` from its environment and cannot identify
the attached provider that supplied it.

Before running setup or intake, list the sandbox's attached providers on the
host and inspect each one:

```bash
openshell sandbox provider list <sandbox>
openshell provider get <provider-name>
```

If an unrelated provider exposes `MS_GRAPH_ACCESS_TOKEN`, stop. Do not run the
collector, even if that provider happens to hold a valid Outlook token. Use a
dedicated sandbox or detach the conflicting provider first.

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

- **Delegated** `Mail.Read`, `User.Read`, and `offline_access`. Delegated, not
  application.
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

If setup reports that another attached provider exposes
`MS_GRAPH_ACCESS_TOKEN`, treat the refusal as a hard stop. Detach the conflicting
provider or use a dedicated sandbox before rerunning setup.

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

## 5. Verify the effective provider, then the collector

On the host, confirm that the attached Graph provider has type
`memory-driven-cos-graph-user`, then export that profile and verify its Graph
endpoint declares `access: read-only` and `enforcement: enforce`:

```bash
openshell sandbox provider list <sandbox>
openshell provider get <provider-name>
openshell provider profile export memory-driven-cos-graph-user
```

Do not infer those properties from `providers/graph-user.yaml`; the exported
gateway profile is the effective policy. Do not proceed if a different provider
also exposes `MS_GRAPH_ACCESS_TOKEN`.

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
| `0` | Collected or unconfigured; unconfigured is not a fault |
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

## Optional Sent Items collection

Inbox remains enabled with the existing setup. Sent Items is disabled by
default. To enable it for a manual run inside the selected profile:

```bash
INTAKE_GRAPH_SENT_ITEMS=1 python3 profile/scripts/ingest_graph.py
```

For scheduled intake, edit the environment file reported by
`hermes -p <profile> config env-path` and set exactly one entry:

```dotenv
INTAKE_GRAPH_SENT_ITEMS=1
```

Set it to `0`, or remove it, to stop Sent Items collection. Only `0` and `1`
are accepted; other values stop the collector before requests. The Slack
self-authored setting is independent. Exporting a value in an interactive
shell does not configure future scheduled runs.

The existing delegated `Mail.Read`, `User.Read`, and `offline_access` scopes
are sufficient; this feature adds no permissions. Each run checks the mailbox
identity. Only Sent Items whose From address matches the returned mail address
or user principal name qualify as outbound. Unrecognized aliases and copied
messages from other authors are omitted and counted as `unverified_authorship`.
User-authored copies in Inbox are omitted in both modes, avoiding duplicate
outbound evidence from Inbox and Sent Items.

Inbox and Sent Items keep separate delta/resume cursors in
`workspace/graph_state.json`. An older flat state file migrates its cursor to
Inbox. Each folder gets its own page budget; the rate-limit wait budget is
shared. A folder's committed progress is saved atomically before proceeding to
the next folder. Failed cursor publication is reported, while already-stored
rows remain idempotent on retry. Malformed state is reported before collection.

The initial backfill defaults to seven days (`GRAPH_BACKFILL_DAYS` changes it).
Graph delta permits a `receivedDateTime` filter, not a `sentDateTime` filter;
that is the initial API boundary. Outbound evidence uses `sentDateTime`, falling
back to received time when the source omits it. Subsequent delta queries may
report older changes. See the [Graph delta contract](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0)
and [message fields](https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0).

Disabling preserves the Sent Items cursor and stored content. Re-enabling
resumes that cursor, including changes during the disabled interval. An expired
cursor restarts that folder's bounded backfill. `--recheck` or a changed mailbox
starts fresh folder rounds. Source-deletion monitoring for Sent Items pauses
while disabled; retention still runs over its stored bodies.

Recipient metadata includes distinct non-self To/Cc/Bcc addresses. Exclusions
check recipients before storage, and sender fields continue to identify the
author. Ambiguous group messages are kept unassigned until a qualifying reply;
see the [direction contract](phase-c1-direction.md). Resolved outbound text can
inform relationship memory, but cannot create inbound obligations or act as an
explicit user priority correction.

Retention clears bodies, not metadata or derived pages. Reset removes the
ledger and collection state, but not independent exports/backups. Portable
exports include recipient metadata and cursor state; they omit the profile
`.env`, so restoring into a new profile does not opt it into collection.
Set the environment entry to `0` as part of reset if future collection must
remain off. [Data lifecycle](data-lifecycle.md) describes the remaining controls.
Schema rollback requires a consistent pre-upgrade profile backup and matching
distribution, with writers stopped; toggling this setting does not downgrade
schema v6.
