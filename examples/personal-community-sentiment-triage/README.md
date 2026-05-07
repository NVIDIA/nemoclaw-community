# personal-community-sentiment-triage: Hermes + Outlook

A personal Hermes agent that surfaces what the developer community is working
on, struggling with, asking about, and flagging as gaps — and compares it
against what internal developer/product teams are prioritizing, so resources
can be aligned against actual community demand. The agent draws on signal
from GitHub issues, NVIDIA forums, and Slack channels; you interact with it
via Outlook email (the primary channel), optionally over Slack.

## Intended user journey

The bring-up has two distinct halves: a host-side bootstrap (Docker services that hold
state across sandbox lifecycles) and an agent-side bring-up (the OpenShell sandbox
itself). The session UUID for Outlook gets produced *between* them, so the order matters.

### Phase 1 — Install prerequisites

```console
$ git clone <this-repo> && cd examples/personal-community-sentiment-triage/
$ curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash   # installs NemoClaw + OpenShell
```

You also need a running Docker daemon. If you haven't already, register an Azure
application and a dedicated agent mailbox per [docs/set-up-outlook-bridge.md](docs/set-up-outlook-bridge.md)
— that's a one-time setup that produces your `OUTLOOK_CLIENT_ID` and `OUTLOOK_TENANT_ID`.

### Phase 2 — Pre-populate `.env` with what you know upfront

```console
$ cp .env.example .env
```

Now edit `.env` and fill in everything you already have:

- `COMPATIBLE_API_KEY` — your inference key
- `OUTLOOK_TENANT_ID`, `OUTLOOK_CLIENT_ID` — from your Azure app registration
- `OUTLOOK_TARGET_MAILBOX`, `OUTLOOK_REPLY_TO` — the agent's mailbox and your personal mailbox
- (optional) `TOKEN_CACHE_SALT` — set to a unique random string for any deployment that
  holds real Entra sessions; leave commented for local experimentation
- (optional) `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`, `GITHUB_TOKEN`, `PHOENIX_COLLECTOR_ENDPOINT`

Leave **`OUTLOOK_SESSION_UUID` blank for now** — Phase 4 produces it.

### Phase 3 — Start host services

```console
$ bash scripts/00-host-services.sh
```

Brings up the long-lived Docker stack from [extras/docker-compose.yml](extras/docker-compose.yml):
phoenix (telemetry), MS Graph token manager (Outlook OAuth broker on port 8765), postgres
(ETL backing store), and the github-etl / forums-etl workers. Postgrest is **deferred**
until the openshell network exists — Phase 6 brings it up.

These services are designed to outlive the sandbox: a `bash scripts/tear-down.sh` followed
by another `bash scripts/bring-up.sh` does **not** require re-running this phase. Only run
it again on a fresh checkout, after `STOP_HOST_SERVICES=1 bash scripts/tear-down.sh`, or
in Phase 6 to attach postgrest.

### Phase 4 — Obtain the Outlook session UUID

The token manager (now running from Phase 3) holds delegated MSAL sessions and issues
short-lived tokens to the credential sidecar inside the sandbox. To create a session,
authenticate as the **agent account** (`OUTLOOK_TARGET_MAILBOX`):

```console
$ eval "$(bash extras/ms-graph-token-manager/scripts/authenticate.sh \
    --client-id "$OUTLOOK_CLIENT_ID" \
    --tenant-id "$OUTLOOK_TENANT_ID" \
    --login-hint "$OUTLOOK_TARGET_MAILBOX" \
    --flow browser)"
$ echo "$SESSION_ID"   # the UUID to paste into .env
```

The script prints `SESSION_ID=<uuid>` on stdout (everything else is on stderr); `eval`
turns that into a shell variable named `SESSION_ID`. On a headless host, swap `--flow
browser` for `--flow device`. See [docs/set-up-outlook-bridge.md](docs/set-up-outlook-bridge.md)
for what each flag does and how to renew an expired session.

Open `.env` and set `OUTLOOK_SESSION_UUID=<the-value-of-$SESSION_ID>`.

### Phase 5 — Bring up the agent

```console
$ bash scripts/bring-up.sh
```

The script auto-sources `.env`, then runs `01-gateway.sh` → `02-providers.sh` →
`03-sandbox.sh` (start the OpenShell gateway, upsert provider credentials, build and
launch the sandbox). When `PHOENIX_COLLECTOR_ENDPOINT` is set, this is where the
NeMo-Flow base variant gets selected and the endpoint baked into the image so
OpenInference traces flow from Hermes into Phoenix at `http://localhost:6006`.

### Phase 6 — Activate postgrest (only if you use the source-etl-query skill)

```console
$ bash scripts/00-host-services.sh
```

Re-running this script after the sandbox is up brings postgrest into the now-existing
`openshell-cluster-*` network so the agent can query the ETL data via REST. Skip this
phase if you don't need the cross-source ETL skills — the agent works without it.

## What this example owns

- **Owns** (in this directory): `agents/hermes/` (the full Hermes asset tree, staged
  here for convenience), `policy.yaml` (sandbox network/filesystem policy — replaces
  the inherited `agents/hermes/policy-additions.yaml`), `extras/`, `.env`, and `scripts/`:
  - `00-host-services.sh` — host-side bootstrap (Phase 3, also re-run in Phase 6 for postgrest). Independent of the sandbox lifecycle.
  - `01-gateway.sh` / `02-providers.sh` / `03-sandbox.sh` — phase scripts called by the bring-up orchestrator.
  - `bring-up.sh` — orchestrator for 01 → 02 → 03; does **not** invoke `00-host-services.sh` (host services are long-lived).
  - `tear-down.sh` — removes the sandbox and per-sandbox providers; preserves host services unless `STOP_HOST_SERVICES=1`.
  - `snapshot.sh` / `restore.sh` — explicit Hermes state preservation across tear-down/bring-up cycles.
- **Generates and discards**: a sed-patched `.Dockerfile.staged` at the example dir
  root. OpenShell does the actual build; we patch ARG defaults beforehand because
  `openshell sandbox create` doesn't expose `--build-arg`.

The example's Dockerfile drops the upstream `COPY nemoclaw-blueprint/` step —
nothing in the Hermes runtime reads `/sandbox/.nemoclaw/blueprints/`, so this
example is **fully self-contained** and never needs a NemoClaw checkout.

When `PHOENIX_COLLECTOR_ENDPOINT` is set, `bring-up.sh` flips
`ARG ENABLE_NEMO_FLOW=1` in the staged Dockerfile, which triggers an in-image
`pip install` of the `nemo-flow` version pinned by `NEMO_FLOW_VERSION` in
[agents/hermes/Dockerfile](agents/hermes/Dockerfile) (from PyPI) plus a
re-install of Hermes with the vendored NeMo-Flow integration patch applied.
No Rust toolchain, no separate base image, no `third_party/nemo-flow` submodule.

## Prerequisites

- Docker daemon running.
- `openshell` CLI on PATH (installed transitively by the NemoClaw installer).
- MS Graph token manager running on the host at port `8765`. `bring-up.sh` auto-resolves
  the host address (Docker bridge gateway on Linux, e.g. `172.17.0.1`; `host.docker.internal`
  fallback on macOS) — set `TOKEN_MANAGER_HOST` to override.
- `.env` populated with the credentials below.

## Providers created (mirrors what `nemoclaw onboard` produces)

| Provider name | `--type` | Credential env var | Required? |
|---|---|---|---|
| `compatible-endpoint` | `openai` | `COMPATIBLE_API_KEY` (or `OPENAI_API_KEY`) — passed to OpenShell as `OPENAI_API_KEY`. URL: `NEMOCLAW_ENDPOINT_URL` (or `OPENAI_BASE_URL`) → `OPENAI_BASE_URL` config. | Required for inference. If omitted, the agent has no LLM. |
| `<sandbox>-outlook` | `generic` | `OUTLOOK_CLIENT_ID`, `OUTLOOK_TENANT_ID`, `OUTLOOK_SESSION_UUID` | Required (this example is Outlook-focused) |
| `<sandbox>-slack-bridge` | `generic` | `SLACK_BOT_TOKEN` | Optional |
| `<sandbox>-slack-app` | `generic` | `SLACK_APP_TOKEN` | Optional |
| `<sandbox>-github` | `github` | `GITHUB_TOKEN` (or `GH_TOKEN`) | Optional |

The `compatible-endpoint` provider is **not** prefixed with the sandbox name — it's a
shared inference provider and is consumed via `openshell inference set --provider
compatible-endpoint --model <NEMOCLAW_MODEL>` rather than `--provider` on sandbox create.

## Configuration knobs (all env vars)

| Var | Default | What it does |
|---|---|---|
| `SANDBOX_NAME` | `hermes-direct` | OpenShell sandbox name. Default avoids clobbering `nemoclaw-hermes`. |
| `OPENSHELL_GATEWAY` | `examples-gateway` | Gateway name. The script auto-starts a gateway with this name if none is active. |
| `OPENSHELL_GATEWAY_PORT` | `8090` | Host port for the auto-started gateway. Different from NemoClaw's default 8080 so the example gateway and `nemoclaw onboard` can coexist. |
| `NEMOCLAW_MODEL` | `nvidia/nemotron-3-super-120b-a12b` | Inference model passed to `openshell inference set`. |
| `NEMOCLAW_ENDPOINT_URL` | `https://integrate.api.nvidia.com/v1` | Upstream base URL for the `compatible-endpoint` provider. (`OPENAI_BASE_URL` is also accepted as a fallback.) |
| `COMPATIBLE_API_KEY` | (none) | Inference API key. Mirrors NemoClaw's `REMOTE_PROVIDER_CONFIG.custom`. (`OPENAI_API_KEY` is also accepted.) |
| `TOKEN_MANAGER_HOST` | (auto-detected: Docker bridge gateway IP, e.g. `172.17.0.1`) | Host where the MS Graph token manager is reachable from inside the sandbox. Auto-resolved via `docker network inspect bridge` to mirror NemoClaw onboard. |
| `PHOENIX_COLLECTOR_ENDPOINT` | (none) | Set to e.g. `http://172.17.0.1:6006/v1/traces` to enable OpenInference telemetry. When set, bring-up flips `ENABLE_NEMO_FLOW=1` so the Dockerfile installs the `nemo-flow` version pinned by `NEMO_FLOW_VERSION` in the Dockerfile from PyPI and applies the Hermes integration patch (~1-2 min on first build, cached on rebuild). |
| `DELETE_INFERENCE_PROVIDER` | `0` | If set to `1` during `tear-down.sh`, also removes the shared `compatible-endpoint` provider. |

## Verification (what success looks like)

```console
$ openshell sandbox list                      # hermes-direct should be ready
$ openshell sandbox exec hermes-direct \
    curl -sf http://localhost:8642/health     # {"status":"ok",...}
$ openshell sandbox exec hermes-direct \
    ls -l /usr/local/bin/ms-graph-sidecar     # binary present
$ openshell sandbox exec hermes-direct \
    ls /usr/local/lib/nemoclaw-bridges/outlook/  # bridge present
$ openshell sandbox exec hermes-direct python3 \
    /sandbox/.hermes-data/skills/outlook-email-search/scripts/search_emails.py \
    --query "nemoclaw" --since 7d              # {"ok": true, "count": N, ...}
```

## Tear-down

```console
$ bash scripts/tear-down.sh
```

Removes the sandbox, the Outlook/GitHub/Slack providers, and any leftover
`.Dockerfile.staged`. **Does not** destroy the gateway or stop host services
(phoenix, token manager, postgres, ETLs, postgrest) by default — those are
typically long-lived. Opt-in flags:

- `STOP_HOST_SERVICES=1` — also `docker compose down` the [extras/](extras/) stack
- `DELETE_INFERENCE_PROVIDER=1` — also remove the shared `compatible-endpoint` provider
- `openshell gateway destroy --name examples-gateway` — manual gateway cleanup

## Persistence: collective wisdom across restarts

What survives a `tear-down.sh && bring-up.sh` cycle by default:

- **Postgres ETL data** — backed by the named Docker volume `source-etls-postgres-data` in [extras/docker-compose.yml](extras/docker-compose.yml). Survives unless you opt in to `STOP_HOST_SERVICES=1`.
- **Host services state** (phoenix's traces, token-manager's MSAL cache) — also volume-backed.

What does **not** survive by default:

- **Hermes's accumulated state** under `/sandbox/.hermes-data/` (memories, sessions, learned skills, scheduled cron, conversation history). The sandbox container is destroyed on tear-down; the writable layer goes with it.

This example ships [scripts/snapshot.sh](scripts/snapshot.sh) and [scripts/restore.sh](scripts/restore.sh) for explicit state preservation. OpenShell's CLI does not expose a `sandbox stop`/`start` pair (the lifecycle is `create` / `delete`), so snapshot-as-tarball is the durable path.

```console
# 1. Capture state from a running sandbox.
$ bash scripts/snapshot.sh
$ ls .snapshots/                              # tarball + manifest.json

# 2. Tear down completely.
$ bash scripts/tear-down.sh

# 3. Bring up a fresh sandbox.
$ bash scripts/bring-up.sh

# 4. Re-hydrate. Defaults to the most recent snapshot in .snapshots/.
$ bash scripts/restore.sh

# 5. Reconnect — Hermes recalls what it learned in step 1.
$ openshell sandbox connect hermes-direct
```

To pin a specific snapshot instead of the latest, pass the path:
`bash scripts/restore.sh .snapshots/2026-05-07T19-03-22Z.tar.gz`.

[scripts/snapshot.sh](scripts/snapshot.sh) excludes obvious credential-bearing files (`.env`, `*secret*`, `*token*`, `auth-profiles*`, etc.) so the tarballs are safe to share — same spirit as NemoClaw's upstream `createSnapshotBundle()` redaction, with file-level exclusion in place of content-aware redaction.

The `.snapshots/` directory is `.gitignore`'d.
