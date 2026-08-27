![NVIDIA](assets/nvidia_header.png)

# Developer Community Chief of Staff: Hermes + Outlook

A personal Hermes agent that surfaces what the developer community is working
on, struggling with, asking about, and flagging as gaps — and compares it
against what internal developer/product teams are prioritizing, so resources
can be aligned against actual community demand. The agent draws on signal
from live GitHub repository state, mirrored GitHub discussions, NVIDIA forums,
and Slack channels. An optional, search-only Tavily integration adds current
public-web discovery. You interact with the agent through Outlook email and/or
Slack.
Outlook is the recommended primary channel, but either is enough on its own —
at least one of the two must be configured.

For first-time setup, use the
[guided configuration and preflight](docs/guided-setup.md). The commands ask
only for credentials required by the selected messaging profile, preserve
unselected existing `.env` content, redact credentials, and detect missing
prerequisites before bring-up.

## Deployment model

This is a personal agent designed to run on a **managed image/VM provisioned by
enterprise IT** (e.g. Ubuntu) — one you authenticate into, that ships sanctioned
pre-installed software and can reach only specific resources. The agent rides that
infrastructure with *delegated* access: its credentials live in OpenShell providers
(GitHub, GitLab, Slack, Microsoft Graph), and it acts on your behalf within them.

Protection is layered. The managed image provides **coarse** protections (authenticated
access, a restricted set of reachable resources, host hardening). OpenShell adds
**workload-specific** protections on top: per-sandbox L7 egress allowlists, credential
placeholder substitution (real secrets never enter the sandbox), binary allowlists, and
Landlock/seccomp.

Concretely, the OpenShell gateway runs on that host under its **Docker compute driver**:
each sandbox is a host-networked container, and the agent reaches the example's host-side
services (the PostgREST forum bridge, ATIF export relay) through
`host.openshell.internal`. Under this driver the container is a thin, host-networked
execution layer — the meaningful workload boundary is OpenShell's policy/proxy/credential
and Landlock/seccomp enforcement, not the container itself. This is a single-host model,
not a Kubernetes/cluster deployment.

## Architecture

The Hermes sandbox operates with a deliberately narrow egress policy. It connects
live to Slack and Outlook for interactions and research. It also has
authenticated, read-only GitHub REST access to an exact repository allowlist
(`GITHUB_READONLY_REPOS`). The GitHub access token is attached through an
OpenShell provider placeholder so GitHub rate limits are practical, while
`policy.yaml` still limits the sandbox to repository-scoped `GET` requests.
Optional GitLab access uses the same credential-isolation pattern and supports
multiple explicitly allowlisted projects. GitHub discussions,
historical mirror data, and NVIDIA forum data come from host-side ETL
containers that scrape on a schedule, write results into Postgres, and expose
that mirror through a read-only PostgREST HTTP bridge.
When `TAVILY_API_KEY` is configured, Hermes can also search the public web
through `POST https://api.tavily.com/search`. OpenShell keeps the raw API key
outside the sandbox and permits only that host, route, method, and the pinned
Hermes Python runtime. The disabled configuration attaches neither the Tavily
provider nor its network policy.

```mermaid
flowchart LR

    nvidia["Internal\nLLM Inference Provider"]
    entra["Internal\nMS Entra ID"]
    slack["Internal\nSlack workspace"]
    outlook["Internal\ngraph.microsoft.com\nmailbox"]
    gitlab["Private\nGitLab REST API"]
    github["External\nGitHub API"]
    tavily["External\nTavily Search API"]
    forums["External\nNVIDIA Forums\n(nemoclaw tag)"]
    s3["Internal\nAWS S3 (prod)\nATIF trace storage"]

    subgraph host["Host Machine/Virtual Machine"]
        direction TB

        subgraph supervisor["OpenShell Sandbox Supervisor"]
            direction TB

            l7["OpenShell L7 Proxy\n10.200.0.1:3128"]
            privacyRouter["OpenShell Privacy Router\n(CONNECT proxy)"]

            subgraph sandbox["OpenShell Sandbox"]
                direction LR

                agent["Hermes Agent\n+ Slack messaging channel"]
                relayRuntime["native NeMo Relay\n(in-process Hermes plugin)"]
                outlookBridge["outlook-bridge\nMS Graph poller"]
                atifBridge["atif-bridge\n127.0.0.1:18444\nHTTP→HTTPS shim"]
                traceDisk[("/tmp/atif/\n(local or recovery)")]

                subgraph sourceSkills["Source Skills"]
                    direction LR
                    s1["source-etl-query"]
                    s2["gitlab-readonly-live"]
                    s4["cross-source-gap-analysis"]
                end

                subgraph slackSkills["Slack Skills"]
                    direction LR
                    k1["slack-channel-finder"]
                    k2["slack-channel-summarizer"]
                end

                subgraph outlookSkills["Outlook Skills"]
                    direction LR
                    o1["outlook-email-search"]
                end

                subgraph webSkills["Optional Public Web Skill"]
                    direction LR
                    w1["public-web-search"]
                end

                outlookBridge <-->|"HTTP POST\ndeliver · reply"| agent
                agent -->|"tool call\nskill dispatch"| sourceSkills
                agent -->|"tool call\nskill dispatch"| slackSkills
                agent -->|"tool call\nskill dispatch"| outlookSkills
                agent -->|"tool call\nskill dispatch"| webSkills
                agent -->|"in-process\nscope events"| relayRuntime
                relayRuntime -.->|"file write\nlocal or recovery"| traceDisk
                relayRuntime -->|"HTTP POST /atif\ncompleted trajectory"| atifBridge
                relayRuntime -->|"OTLP HTTP POST\ntelemetry traces"| l7
                atifBridge -->|"HTTPS POST /atif\nbearer placeholder"| l7
                outlookBridge -->|"HTTPS GET/POST\nmail poll · reply"| l7
                agent <-->|"WSS socket-mode\nmessaging channel"| l7
                agent -->|"HTTPS POST\nLLM request"| privacyRouter
                sourceSkills -->|"HTTP GET\nsource queries"| l7
                slackSkills -->|"HTTPS POST\nSlack API"| l7
                outlookSkills -->|"HTTPS GET\nGraph API"| l7
                webSkills -->|"HTTPS POST /search\nAPI key placeholder"| l7
            end
        end

        gateway["OpenShell Gateway\n127.0.0.1:17670\nprovider store ·\nrefresh-token rotation"]
        atifRelay["atif-export-relay\n:18443\nbearer auth · re-signs"]
        phoenix["Phoenix\n:6006"]
        postgrest["PostgREST\n:3100"]
        postgres[("PostgreSQL\nsource mirror")]
        etls["Source ETLs\nGitHub + Forums\nhourly deltas"]
        minio["MinIO (dev)\n:9000"]

        l7 -->|"OTLP HTTP POST\ntrace ingest"| phoenix
        l7 -->|"HTTP GET\nREST queries"| postgrest
        l7 -->|"HTTPS POST /atif\nBearer substituted"| atifRelay
        postgrest -->|"SQL\ndata queries"| postgres
        etls -->|"SQL INSERT\nhourly deltas"| postgres
        gateway <-->|"gRPC stream\ncredential refresh"| l7
        atifRelay -.->|"boto3 PutObject"| minio
    end

    privacyRouter -->|"HTTPS POST\nLLM inference"| nvidia
    l7 <-->|"WSS / HTTPS POST\nSlack messaging"| slack
    l7 -->|"HTTPS GET/POST\nGraph API"| outlook
    l7 -->|"HTTPS GET\nGitHub REST"| github
    l7 -->|"HTTPS GET\nproject-scoped GitLab REST"| gitlab
    l7 -->|"HTTPS POST /search\nAPI key substituted"| tavily
    atifRelay -->|"boto3 PutObject"| s3
    gateway <-->|"HTTPS POST\ntoken rotation"| entra
    etls -->|"HTTPS GET\nscheduled scrape"| github
    etls -->|"HTTPS GET\nscheduled scrape"| forums

    style host       fill:#f7f6ef,stroke:#8a8068,stroke-width:2px
    style supervisor fill:#e7f0ff,stroke:#2b5fab,stroke-width:3px
    style sandbox    fill:#d8e8ff,stroke:#2b5fab,stroke-width:1px,stroke-dasharray:5 3

    style sourceSkills  fill:#f0f4ff,stroke:#7090cc,stroke-width:1px
    style slackSkills   fill:#f0f4ff,stroke:#7090cc,stroke-width:1px
    style outlookSkills fill:#f0f4ff,stroke:#7090cc,stroke-width:1px
    style webSkills     fill:#f0f4ff,stroke:#7090cc,stroke-width:1px

    style agent         fill:#dbeafe,stroke:#3b82f6,stroke-width:1.5px
    style relayRuntime  fill:#fef9e7,stroke:#f39c12,stroke-width:2px
    style atifBridge    fill:#fef0e7,stroke:#e67e22,stroke-width:2px
    style atifRelay     fill:#fef0e7,stroke:#e67e22,stroke-width:2px
    style outlookBridge fill:#fef0e7,stroke:#e67e22,stroke-width:2px
    style traceDisk     fill:#fef9e7,stroke:#f39c12,stroke-width:1px

    style l7            fill:#fce5cd,stroke:#e69138,stroke-width:2px
    style privacyRouter fill:#e7eef0,stroke:#5d6d75,stroke-width:2px
    style gateway       fill:#e7eef0,stroke:#5d6d75,stroke-width:2px

    style s3    fill:#eef7e9,stroke:#6aa84f,stroke-width:2px
    style minio fill:#eef7e9,stroke:#6aa84f,stroke-width:1px,stroke-dasharray:4 2

    classDef internal fill:#eef7e9,stroke:#6aa84f,stroke-width:2px
    classDef external fill:#fce5cd,stroke:#e69138,stroke-width:2px
    class nvidia,slack,outlook,gitlab,entra,s3 internal
    class github,forums,tavily external
```

**Key invariants:**

- The agent has authenticated read-only `api.github.com` access for an exact repository allowlist. The raw GitHub access token stays in an OpenShell provider; the sandbox sees only a placeholder, and policy still blocks writes, non-API GitHub hosts, `git`, and `gh`.
- The agent can have authenticated read-only access to multiple explicitly configured GitLab projects. Policy permits only selected project-data routes and blocks writes plus sensitive endpoints such as CI/CD variables, hooks, tokens, runners, and members.
- Public web search is disabled by default. When configured, the raw Tavily API
  key stays in an OpenShell provider and the sandbox can call only
  `POST api.tavily.com/search` from Hermes's pinned Python runtime. Page
  extraction, direct URL fetching, browser automation, and other internet
  egress remain blocked.
- GitHub discussions, historical mirror data, and NVIDIA forum data come from the Postgres mirror.
- Slack and Outlook are live connections from the sandbox; the agent can read and write both in real time.
- Compatible-endpoint inference egress is required for the agent's LLM calls — it's not a research/data-ingestion path.
- The ETL containers are non-agentic — fixed scraper logic on an hourly interval, no LLM involvement.
- The PostgREST bridge exposes a read-only HTTP API on host port `3100`, and the sandbox reaches it through `host.openshell.internal` without any live forum egress.
- Hermes runs NeMo Relay in process through its native plugin integration, with no separate Relay installation or process.

## Agent skills

Skills are loaded on demand by the agent when relevant to a task. They live in [agents/hermes/skills/](agents/hermes/skills/).
0.0.
| Skill | Purpose |
|-------|---------|
| `github-readonly-live` | Query the configured live GitHub repo via authenticated, policy-scoped REST `GET` requests. |
| `gitlab-readonly-live` | Query one of the explicitly allowed GitLab projects via authenticated, project-scoped REST `GET` requests. |
| `source-etl-query` | Query the host-side PostgREST bridge for mirrored GitHub discussions, historical mirror data, and NVIDIA forum data. |
| `slack-channel-finder` | Discover Slack channels by topic, team, or domain and infer what each channel is for. |
| `slack-channel-summarizer` | Resolve Slack channels by name or ID and read message history via the Slack Web API. |
| `outlook-email-search` | Search the Outlook mailbox via Microsoft Graph to find and read emails relevant to a question. |
| `cross-source-gap-analysis` | Synthesize findings across Slack, GitHub, and NVIDIA forum sources to identify gaps, alignment issues, and follow-ups. |
| `nemoclaw-autoheal` | Guide users through sandbox health checks and optional host-side auto-heal setup. |
| `nemoclaw-nvteam` | Route work through eight evidence-bounded role lenses added locally by this Community recipe. |
| `public-web-search` | Search current public information through the optional, policy-scoped Tavily `web_search` path and cite returned URLs. |

The original contribution reported source revision
`b87038405fd7d9646dba57c367f54d86ca4d933d`. This repository adapts and hardens
that package for the public recipe; it does not claim byte-for-byte identity
with the reported source. The repository commit that contains this example is
the auditable version.

Named-person authority weighting is disabled by default. This public recipe
does not provision a private registry or a secure registry-installation
workflow. It includes only the schema, synthetic example, and validator for a
trusted runtime that supplies the registry read-only outside agent-writable
state.

The eight role lenses are Product Manager (River), Technical Program Manager
(Quinn), Backend and Systems Engineer (Akira), Data and ML Engineer (Jordan),
Quality Engineer (Robin), Platform and SRE (Alex), Security Engineer (Morgan),
and Technical Marketing Engineer (Parker). The chief of staff introduces this
team once at the start of the first NVTeam-routed response and shows the active
name and role on each routed response. NVTeam is added by this Community recipe;
it is not a built-in capability of the core NemoClaw product. These labels
describe task-scoped lenses, not real people, separate agents, models,
configurations, decision owners, or evidence about core-product behavior.

Substantive NVTeam work applies Mission is the Boss, Speed of Light (SOL),
Listen, Understand, Answer (LUA), and “As much as needed, as little as
possible” as practical decision tools. The personas apply these principles
silently by default and name one only when it clarifies a material choice.
Akira, Jordan, Robin, Alex, Morgan, and Parker share one technical-writing
reference instead of duplicating the same rules across their cards.

In Slack, every persona uses semantic Markdown shaped for its domain. Hermes
renders the Markdown as native Rich Blocks and retains a complete text
fallback. When two to four choices materially block progress, the normal
Hermes clarification tool appears as one-tap Slack buttons. A click returns
user input to the normal turn; it does not approve or perform a side effect.

## Intended user journey

The bring-up has two distinct halves: a host-side bootstrap (Docker services that hold
state across sandbox lifecycles) and an agent-side bring-up (the OpenShell sandbox
itself). The session UUID for Outlook gets produced *between* them, so the order matters.

### Phase 1 — Install prerequisites

```console
$ git clone https://github.com/NVIDIA/nemoclaw-community.git && cd examples/recipes/nvidia/developer-community-chief-of-staff/
$ curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | OPENSHELL_VERSION=v0.0.85 sh
```

OpenShell `v0.0.85` matches the supported version in the NemoClaw `v0.0.105`
release that publishes this example's pinned Hermes sandbox base image.

The package-managed installer starts a local gateway service for you. This
example assumes that default path and targets the `openshell` gateway at
`https://127.0.0.1:17670`. If you're following OpenShell's snap instructions
instead, set `OPENSHELL_GATEWAY=snap-docker` and
`OPENSHELL_GATEWAY_ENDPOINT=http://127.0.0.1:17670` in `.env`.

On Debian/Ubuntu the installer registers `openshell-gateway` as a **systemd
user service**, which only auto-starts when your user has an active systemd
session. Headless hosts (cloud shells, SSH-only VMs, CI runners) often don't,
so the service silently never starts and the first `openshell gateway add`
call fails with `mTLS certificates for gateway 'openshell' were not found`.
The fix, per the [OpenShell install docs](https://github.com/NVIDIA/OpenShell/blob/main/docs/about/installation.mdx#linux),
is to enable linger so the user manager boots without an interactive login:

```console
$ sudo loginctl enable-linger $USER
$ export XDG_RUNTIME_DIR=/run/user/$(id -u)   # only needed in shells started before linger
$ systemctl --user start openshell-gateway    # if not already started
$ systemctl --user status openshell-gateway   # verify
```

If `systemctl --user` returns `Failed to connect to bus: No medium found`
even after `enable-linger`, it's because the current shell predates the
user manager and doesn't know where the bus is. Either export
`XDG_RUNTIME_DIR` as shown above, or log out and reconnect — `pam_systemd`
sets it automatically once linger is on.

The service's `ExecStartPre` provisions the mTLS bundle the CLI needs, so
once the unit is `active (running)`, `bring-up.sh` can register the gateway.

This example uses OpenShell provider v2 (OAuth refresh-token rotation via
`openshell provider refresh configure`). Enable it once at gateway scope:

```console
$ openshell settings set --global --key providers_v2_enabled --value true --yes
```

`scripts/02-providers.sh` verifies this is set and refuses to run otherwise.

You also need a running Docker daemon. If you haven't already, register an Azure
application and a dedicated agent mailbox per [docs/set-up-outlook-bridge.md](docs/set-up-outlook-bridge.md)
— that's a one-time setup that produces your `OUTLOOK_CLIENT_ID` and `OUTLOOK_TENANT_ID`.

This example will download and install additional third-party open source software projects. Review the license terms of these open source projects before use. The repository-level `THIRD-PARTY-NOTICES` file tracks the expected inventory.

### Phase 2 — Configure and check the recipe

```console
$ python3 scripts/configure.py
$ python3 scripts/preflight.py
```

The configurator guides you through a Slack-only, Outlook-only, or combined
profile. It hides credential input and writes `.env` with owner-only
permissions. If `.env` exists, the command changes only the selected keys and
preserves comments, advanced settings, and other values. Use `--replace` only
when you intend to replace the file with a minimal configuration.

The default preflight performs configuration and local host checks. It does
not create services, providers, or sandboxes, and it does not contact the
configured inference or Slack services. When the local checks pass, run the
optional bounded external checks:

```console
$ python3 scripts/preflight.py --external
```

The external mode reuses `inference_preflight.py` and
`slack_socket_preflight.py`. It sends the same bounded validation requests that
provider setup uses. Each preflight result prints the exact next command.

For deterministic automation, supply the required values through the process
environment or an existing `.env`, then select a profile:

```console
$ python3 scripts/configure.py --non-interactive --profile slack
```

Do not place credential values in command arguments. See
[Guided Configuration and Preflight](docs/guided-setup.md) for profile inputs,
automation, replacement behavior, JSON output, and the external-check boundary.

Advanced manual configuration remains supported:

```console
$ cp .env.example .env
```

Edit `.env` and fill in everything you need:

- `COMPATIBLE_API_KEY` — your inference key
- **At least one messaging channel** — Outlook or Slack (or both):
  - **Outlook** (recommended primary channel): set **all four** Outlook vars together, or leave the entire block empty.
    - `OUTLOOK_TENANT_ID`, `OUTLOOK_CLIENT_ID` — from your Azure app registration
    - `OUTLOOK_TARGET_MAILBOX`, `OUTLOOK_REPLY_TO` — the agent's mailbox and your personal mailbox
  - **Slack**: `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` (both required) — see [docs/set-up-slack.md](docs/set-up-slack.md). Partial Outlook configuration (some vars set, some empty) is rejected at bring-up.
- (optional) `SLACK_ALLOWED_IDS` — comma-separated Slack user IDs to restrict who can DM the agent; leave empty to allow anyone in the workspace
- (optional) `NEMOCLAW_SLACK_RICH_BLOCKS=false` — disable native Slack Rich Block rendering and use the text fallback. The default is `true`.
- (optional) `OUTLOOK_ALLOWED_SENDERS` — comma-separated allowlist of email senders the agent will respond to; leave empty to fall back to OUTLOOK_REPLY_TO
- (optional) `GITHUB_TOKEN` for authenticated sandbox read-only
  GitHub REST, `GITHUB_READONLY_REPOS`,
  `PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_PROJECT_NAME`
- (optional) `TAVILY_API_KEY` for policy-scoped public web search. See
  [Policy-Scoped Public Web Search](docs/public-web-search.md).

### Phase 3 — Host services (handled by bring-up.sh, no manual step)

[scripts/bring-up.sh](scripts/bring-up.sh) handles host services as its phase 1/4 by
invoking [scripts/00-host-services.sh](scripts/00-host-services.sh) before the
sandbox-side phases. The stack from [extras/docker-compose.yml](extras/docker-compose.yml)
— phoenix (telemetry), postgres (ETL backing store), the forum ETL, PostgREST on
host port 3100, plus the opt-in GitHub ETL and minio + atif-export-relay when
configured — is
designed to outlive the sandbox, so subsequent `tear-down.sh && bring-up.sh` cycles
re-touch only the sandbox by default (00-host-services is idempotent).

You can also manage host services independently: `bash scripts/00-host-services.sh up`
or `bash scripts/00-host-services.sh down` for direct control without touching the
sandbox.

### Phase 4 — Bring up the agent

```console
$ bash scripts/bring-up.sh
```

The script auto-sources `.env`, then runs `01-gateway.sh` → `02-providers.sh` →
`03-sandbox.sh` (select or register the local OpenShell gateway, import v2 provider
profiles, upsert providers, build and launch the sandbox).

Before the image build, provider setup sends one bounded synthetic tool request
and requires a valid structured tool call. After selecting the route, it also
confirms that OpenShell reports the requested provider and model as active. A
failure stops setup before the expensive build. Set
`NEMOCLAW_INFERENCE_PREFLIGHT=0` only as an explicit bypass for intentional
offline setup or an endpoint that cannot support verification.

On the first bring-up with Outlook configured, `02-providers.sh` runs an interactive
Microsoft device-code login (it prints a URL + code; complete it in a browser as the
`OUTLOOK_TARGET_MAILBOX` user) and caches the resulting refresh token at
`.bootstrap/cache/ms-graph-token.json` (mode 0600; ignored by `.gitignore`). Subsequent
bring-ups reuse the cached refresh token (auto-refreshing on staleness ~90 days). Force
a fresh login with `OUTLOOK_LOGIN_CACHE=2 bash scripts/bring-up.sh`. Set
`OUTLOOK_LOGIN_CACHE=0` to skip the cache entirely and do device-code on every
bring-up — see [docs/set-up-outlook-bridge.md](docs/set-up-outlook-bridge.md#security-note-where-the-refresh-token-lives).

To use Hermes interactively after bring-up, connect to the sandbox and start a
new TUI session:

```console
$ openshell sandbox connect hermes-direct
$ hermes chat --tui
```

Use `hermes chat --tui --continue` only after a TUI session exists. The image
contains the TUI bundle and does not need an `npm install` at runtime.

Hermes includes NeMo Relay as a normal runtime dependency. In the default local
export mode, a finalized session is written to `/tmp/atif/`. If
`PHOENIX_COLLECTOR_ENDPOINT` is set, `03-sandbox.sh` additionally bakes the
endpoint into the image so OpenInference traces stream into Phoenix at
`http://localhost:6006`.

### Optional Phase 5 — Install auto-heal after first bring-up

After the sandbox is Ready and the normal verification passes, you can opt in
to user-level monitoring that keeps the host proxy, Hermes gateway forward, and
Slack response path healthy. It is deliberately separate from `bring-up.sh` so
first-time setup stays predictable and operators retain control over systemd.

```console
$ bash scripts/autoheal/install.sh --check
$ bash scripts/autoheal/install.sh
$ bash scripts/autoheal/sanity-check.sh
```

If you installed auto-heal from the previous
`examples/personal-community-sentiment-triage` path, run the last two commands
again from this directory. Restore the ignored `.env` file at this new path
first, and keep it out of Git. The installer updates its absolute paths and
restarts only the units that it owns.

For a host TLS proxy, first set the explicit upstream origin in `.env`. For
example, `NEMOCLAW_ENDPOINT_URL=http://host.openshell.internal:18080/v1` pairs
with `NEMOCLAW_HOST_TLS_PROXY_UPSTREAM=https://inference-api.nvidia.com`.
See [docs/auto-heal.md](docs/auto-heal.md) for manual checks, logs, repair, and
uninstall instructions.

## What this example owns

- **Owns** (in this directory): `agents/hermes/` (the full Hermes asset tree, staged
  here for convenience), `policy.yaml` (sandbox network/filesystem policy template), `extras/`,
  `.env`, and `scripts/`:
  - `00-host-services.sh` — host-side stack lifecycle (phoenix, postgres, ETLs, postgrest, and minio + atif-export-relay when `ATIF_EXPORT_MODE=relay`). Idempotent; safe to invoke directly for `up` or `down`.
  - `01-gateway.sh` / `02-providers.sh` / `03-sandbox.sh` — sandbox-side phase scripts called by the bring-up orchestrator.
  - `bring-up.sh` — orchestrator: invokes `00-host-services.sh up` (phase 1/4) followed by 01 → 02 → 03 (phases 2-4/4). `00-host-services.sh` is idempotent, so re-running `bring-up.sh` on an already-up host stack is a no-op for those services and only re-runs the sandbox-side phases.
  - `tear-down.sh` — removes the sandbox and per-sandbox providers; preserves host services. Add `--stop-host-services` to also stop them (volumes preserved) or `--purge-host-services` to stop and wipe named volumes.
  - `snapshot.sh` / `restore.sh` — explicit Hermes state preservation across tear-down/bring-up cycles.
  - `download-traces.sh` — pull ATIF trace records from `/tmp/atif/` inside the sandbox into a host-side tarball. See [Capturing ATIF traces](#capturing-atif-traces) for the env knobs.
  - `host-tls-proxy.py` — optional plain-HTTP forwarder for hosts where the sandbox can't validate the inference endpoint's TLS chain (corporate VPN, split-horizon DNS, mkcert). See [docs/host-tls-proxy.md](docs/host-tls-proxy.md).
  - `autoheal/` — optional user-systemd installer, watchdog, response monitor,
    sanity checker, and unit templates. See [docs/auto-heal.md](docs/auto-heal.md).
- **Generates and discards**: sed-patched `.Dockerfile.staged` and
  `.policy.staged.yaml` files at the example dir root. OpenShell does the actual
  build; we patch ARG defaults beforehand because `openshell sandbox create`
  doesn't expose `--build-arg`, and we patch the GitHub read-only repo scope
  from `.env` before applying the policy.

The example's Dockerfile drops the upstream `COPY nemoclaw-blueprint/` step —
nothing in the Hermes runtime reads `/sandbox/.nemoclaw/blueprints/`, so this
example is **fully self-contained** and never needs a NemoClaw checkout.

The Dockerfile inherits the pinned NemoClaw `v0.0.105` Hermes sandbox base, then
installs a pinned Hermes source revision
(`03fa32c92dd445eb64c7f67434dd91b32c40701d`, package `0.20.0`) with NeMo
Relay `0.7.2`. Hermes's native `observability/nemo_relay` plugin handles scopes
and export in process, so the image needs no separate Relay installation or
process.

Setting `PHOENIX_COLLECTOR_ENDPOINT` is a separate opt-in for live
OpenInference egress: when present, `03-sandbox.sh` bakes the URL into the
image so the agent streams traces to a Phoenix collector. The collector is
included in [extras/docker-compose.yml](extras/docker-compose.yml) and runs
on host port `6006`.

### Capturing ATIF traces

In local mode, NeMo Relay writes an ATIF (Agent Trajectory Format) record to
`/tmp/atif/` when Hermes finalizes a session and closes its top-level Agent
scope. Finalization happens on an explicit `/new` or `/reset`, CLI/TUI exit, or
configured gateway expiry—not after every conversational turn. That directory
is ephemeral—it lives on the sandbox's writable layer and is destroyed by
`tear-down.sh`—so capture before destroying the sandbox if you want to keep
the traces.

For production / always-on capture, set `ATIF_EXPORT_MODE=relay` (with
`ATIF_RELAY_BACKEND=minio` or `s3`) to have NeMo Relay upload completed
trajectories to S3-compatible storage via a host-side relay. The sandbox never holds real
AWS credentials; OpenShell's provider store manages a per-sandbox bearer
token instead. A successful remote POST does not also create a local file. If
all configured remote targets fail, NeMo Relay `0.7.2` writes a recovery copy
to `/tmp/atif/`. See [docs/atif-export.md](docs/atif-export.md) for setup, IAM
template, and the auth model.

```console
$ bash scripts/download-traces.sh
```

Writes `$EXAMPLE_DIR/.traces/atif-{ISO-timestamp}.tar.gz` plus a JSON
manifest sidecar. The tarball path is printed on stdout (progress goes to
stderr), so callers can capture it:

```console
$ TRACE=$(bash scripts/download-traces.sh)
```

Two env vars answer the "from where / to where" questions and can be
overridden at the call site:

| Env var | Default | What it controls |
|---|---|---|
| `SANDBOX_NAME` | `hermes-direct` | Which OpenShell sandbox to pull `/tmp/atif/` from. Shared with the rest of the example's scripts (defined in `_lib.sh`). |
| `TRACES_DIR` | `$EXAMPLE_DIR/.traces` | Host-side directory the tarball is written to. |

If `/tmp/atif/` is empty when the script runs (for example, no session has
finalized, or remote export succeeded), the script still emits a
valid empty tarball whose manifest carries an explanatory `note` — downstream
tooling never has to special-case "no file."

**Lifecycle note**: no automatic rotation — files accumulate until
sandbox teardown. For long-lived sessions, prune manually inside the
sandbox, e.g. `find /tmp/atif -type f -mtime +7 -delete`.

## Prerequisites

- Docker daemon running.
- `openshell` CLI on PATH (installed transitively by the NemoClaw installer).
- `providers_v2_enabled` set globally on the OpenShell gateway
  (`openshell settings set --global --key providers_v2_enabled --value true --yes`).
- `.env` populated with the credentials below.
- **(Optional)** If your network performs TLS interception (e.g. an
  SSL-inspecting proxy), place the inspection CA certificate(s) as `.crt`
  files in the example-root `certs/` directory before running `bring-up.sh`.
  Additional roots installed in the host's standard local CA directory are
  staged automatically. Otherwise leave the directory empty. See
  [`certs/README.md`](certs/README.md) for details.

## Providers created by `bring-up.sh`

Five of the six providers use custom v2 profiles in [providers/](providers/)
and are attached to the sandbox directly. Inference goes through OpenShell's
built-in `nvidia` v2 profile + `openshell inference set` + `inference.local`
routing for gateway-side hardening (streaming timeout, header sanitization,
model-ID enforcement, credential never enters the sandbox env). The custom
[`providers/compatible-endpoint.yaml`](providers/compatible-endpoint.yaml) is
checked in as a forward-looking placeholder for when OpenShell adds inference-
route auto-creation from `inference_capable` v2 profiles; until then it's not
imported. The agent calls each non-inference upstream directly with a placeholder
bearer header; the OpenShell L7 proxy substitutes a live token on egress.

| Provider name | `--type` | Credential env var | Required? |
|---|---|---|---|
| `compatible-endpoint` | `nvidia` (built-in v2; consumed via `openshell inference set`, not attached to the sandbox directly) | `NVIDIA_API_KEY` (populated from `OPENAI_API_KEY` / `COMPATIBLE_API_KEY` at provider-create time). URL: `NEMOCLAW_ENDPOINT_URL` → `NVIDIA_BASE_URL` provider config. Routing via `inference.local`. | Required for inference. Missing credentials stop setup before the sandbox build unless the explicit offline preflight bypass is selected. |
| `<sandbox>-outlook` | `nemoclaw-outlook-email` | `MS_GRAPH_ACCESS_TOKEN` (auto-rotated by the gateway from the registered refresh token). Refresh material: `OUTLOOK_TENANT_ID`, `OUTLOOK_CLIENT_ID`, refresh_token (cached from device-code login). | Optional. Created only when the Outlook block is fully populated; partial config is rejected. At least one of Outlook or Slack must be configured. |
| `<sandbox>-slack` | `nemoclaw-slack` | `SLACK_BOT_TOKEN` (Web API) + `SLACK_APP_TOKEN` (Socket Mode) | Optional. Before provider creation, setup verifies that the app token can call `apps.connections.open` with `connections:write`. At least one of Outlook or Slack must be configured. |
| `<sandbox>-github` | `nemoclaw-github` | `GITHUB_TOKEN` | Optional but recommended. Enables authenticated live GitHub REST reads. The sandbox receives only the OpenShell placeholder; `policy.yaml` further limits use to repository-scoped `GET` routes from approved binaries. |
| `<sandbox>-gitlab` | `nemoclaw-gitlab` | `GITLAB_TOKEN` | Optional. Enables authenticated GitLab REST reads. `policy.yaml` expands a separate GET-only path allowlist for every project in `GITLAB_READONLY_PROJECTS`; sensitive project endpoints remain blocked. |
| `<sandbox>-tavily-search` | `nemoclaw-tavily-search` | `TAVILY_API_KEY` | Optional and disabled when the key is absent. Setup validates the key before provider creation. Request-body placeholder rewriting supports Hermes's native `web_search`; provider and sandbox policies allow only `POST /search` from `/opt/hermes/.venv/bin/python`. |
| `<sandbox>-atif-export-relay` | `nemoclaw-atif-export-relay` | `ATIF_RELAY_AUTH_TOKEN` | Created and attached only when `ATIF_EXPORT_MODE=relay`. Allows the Python ATIF bridge to send `POST /atif` to the configured host relay; the provider owns the endpoint, path, binary, private-IP, and credential restrictions. |

The `compatible-endpoint` provider is **not** prefixed with the sandbox name — it's a
shared inference provider attached via `--provider compatible-endpoint` on sandbox
create, the same way every other v2 provider is attached. The agent dials the upstream
host directly; the L7 proxy substitutes the `OPENAI_API_KEY` placeholder on egress.

### How `policy.yaml` and provider profiles compose

Sandbox network policy ([`policy.yaml`](policy.yaml)) layers on top of the per-provider
endpoint scopes above. For most providers the profile is the sole source of policy;
`policy.yaml` only carries restrictions that the v2 ProviderProfile schema can't
express today — specifically per-path allow rules (used to scope the NVIDIA inference
API to specific `/v1/*` paths, GitHub reads to an exact repository allowlist,
and GitLab reads to explicitly listed projects via `GITLAB_READONLY_PROJECTS`)
and credential-less host-routed services (Phoenix collector, Source-ETL API). Surviving
`network_policies` blocks in `policy.yaml` carry **load-bearing comments** explaining
why they can't be folded into provider profiles. Fully-redundant blocks (e.g. the
former `slack` block) have been removed.

Tavily is intentionally enforced twice. Its provider profile carries the fixed
search endpoint and request-body credential rewrite. The staged sandbox policy
adds the same `POST /search` and Hermes-Python boundary only when
`TAVILY_API_KEY` exists. With no key, `web_search` is not advertised to Slack,
the policy marker is removed without replacement, and no Tavily provider is
attached.

`GITHUB_TOKEN` is attached as `<sandbox>-github` for live sandbox GitHub reads.
The sandbox sees only an OpenShell placeholder;
the raw access token is resolved by the proxy on egress. GitHub write attempts are
still blocked by the applied policy, which allows only selected `GET` paths
under `api.github.com/repos/` for the configured allowlist. If you keep the optional
host GitHub mirror enabled, it also reads `GITHUB_TOKEN` for API rate limits.

## Changing the available live GitHub repositories

The live GitHub policy is repository-scoped. To change the repositories that
the sandbox can read:

1. Set a comma-separated allowlist in `.env`, for example
   `GITHUB_READONLY_REPOS=owner/skills,owner/blueprint`. Each item must use
   `owner/repository`. Existing configurations can continue to use the single
   `GITHUB_READONLY_REPO` setting. When both are set, the plural setting takes
   precedence.
2. For practical API rate limits, set `GITHUB_TOKEN`. Each private repository
   requires the access token to have access to it. Public repositories can be
   read without an access token but use GitHub's lower unauthenticated API
   limits.
3. If you need to preserve memories, sessions, or learned skills, run
   `bash scripts/snapshot.sh` while the existing sandbox is running.
4. Recreate the sandbox so `scripts/03-sandbox.sh` can stage the Dockerfile
   environment and apply exact `GET` rules for the new allowlist:

```bash
bash scripts/tear-down.sh
bash scripts/bring-up.sh
```

5. If you made a snapshot, run `bash scripts/restore.sh` after bring-up. The
   [persistence section](#persistence-collective-wisdom-across-restarts)
   describes the snapshot contents and handling requirements.

For normal repository changes, do not edit `policy.yaml` by hand.
`03-sandbox.sh` validates the list and replaces the fail-closed marker with
exact repository paths before it applies the staged policy. After bring-up,
verify each allowed repository from the host shell:

```bash
set -a; . ./.env; set +a
openshell sandbox exec --name "${SANDBOX_NAME:-hermes-direct}" -- sh -lc \
  '/usr/bin/python3 /sandbox/.hermes-data/skills/github-readonly-live/scripts/github_readonly.py --repo owner/skills get . --fields full_name,default_branch,open_issues_count'
```

When more than one repository is allowed, `--repo owner/repository` is
required. The helper rejects an unlisted repository before it sends a request.
The policy permits only `GET`; write methods remain denied. With one allowed
repository, omitting `--repo` retains the previous helper behavior.

`GITHUB_READONLY_REPOS` and its singular fallback control only live REST reads
through `github-readonly-live`. The host-side ETL mirror is independent and
disabled by default. Set `SOURCE_ETL_GITHUB_ENABLED=1` and optionally
`SOURCE_ETL_GITHUB_REPO=owner/repo` when you want mirrored GitHub
discussions/history, then rerun
`bash scripts/00-host-services.sh`. Existing mirror database/state is preserved
unless you remove the compose volumes.

## Changing the available live GitLab projects

GitLab access is optional and supports one or more explicit project paths; it
is not limited to a single repository:

1. Create a GitLab personal access token with `read_api` scope and set
   `GITLAB_TOKEN` in `.env`.
2. Set a comma-separated allowlist, for example:

```bash
GITLAB_READONLY_PROJECTS=example-team/project-one,group/subgroup/project-two
```

3. If necessary, set `GITLAB_API_URL` to the REST v4 base for the GitLab
   deployment. The value must have the form `https://host[:port]/api/v4`.
4. Rerun `bash scripts/bring-up.sh`. Changing the allowlist requires sandbox
   recreation because the exact project paths are compiled into policy.

During sandbox creation, each configured path is resolved to its canonical
numeric project ID. The staged policy receives GET-only rules for that ID; the
sandbox itself receives only the friendly path-to-ID mapping and the OpenShell
credential placeholder. The raw token is never baked into the image.

The helper selects the project automatically when only one is configured. With
multiple projects, pass `--project group/project`. Issues, merge requests,
repository content and history, labels, milestones, and releases are readable.
The bare project-metadata response is blocked because GitLab may include
sensitive fields in it for privileged identities. Variables, hooks, tokens,
runners, members, writes, `glab`, and `git` remain blocked.

## Configuration knobs (all env vars)

| Var | Default | What it does |
|---|---|---|
| `SANDBOX_NAME` | `hermes-direct` | OpenShell sandbox name. Default avoids clobbering `nemoclaw-hermes`. |
| `OPENSHELL_GATEWAY` | `openshell` | Gateway name. The default matches the package-managed OpenShell installer. Use `snap-docker` when following the snap setup. |
| `OPENSHELL_GATEWAY_ENDPOINT` | auto (`https://127.0.0.1:17670` for `openshell`, `http://127.0.0.1:17670` for `snap-docker`) | Override the local gateway endpoint if you registered it under a different URL. |
| `NEMOCLAW_MODEL` | `nvidia/nemotron-3-super-120b-a12b` | Inference model passed to `openshell inference set`. |
| `NEMOCLAW_INFERENCE_PREFLIGHT` | `1` | Requires one bounded structured tool call before sandbox creation, then verifies that OpenShell activated the requested provider and model. Remote endpoints must use HTTPS. For `http://host.openshell.internal:<port>`, the host-side check safely uses the same listener through `127.0.0.1:<port>`. Non-empty proxy and CA environment variables are preserved; unset CA overrides remain unset so the platform trust store still works. Set to `0` only for intentional offline setup or an endpoint that cannot support verification. |
| `NEMOCLAW_INFERENCE_PREFLIGHT_TIMEOUT_SECONDS` | `10` | Maximum time allowed for the preflight request. |
| `NEMOCLAW_SLACK_RICH_BLOCKS` | `true` | Render supported semantic Markdown with Hermes's native Slack Block Kit renderer, including table blocks. Set to `false` for text-only output. Interactive clarification buttons remain available. Only `true` or `false` is accepted. Rebuild the sandbox after changing it. |
| `NEMOCLAW_ENDPOINT_URL` | `https://integrate.api.nvidia.com/v1` | Upstream base URL for the `compatible-endpoint` provider. (`OPENAI_BASE_URL` is also accepted as a fallback.) |
| `NEMOCLAW_HOST_TLS_PROXY_UPSTREAM` | (none) | Optional HTTPS origin for the host TLS proxy. Required when `NEMOCLAW_ENDPOINT_URL` uses `host.openshell.internal:18080` and auto-heal should manage that proxy. |
| `NEMOCLAW_HOST_TLS_PROXY_PORT` | `18080` | Host listener port for the optional TLS proxy. |
| `NEMOCLAW_HOST_CA_BUNDLE` | `/etc/ssl/certs/ca-certificates.crt` | Absolute path to a readable regular-file host CA bundle mounted read-only into the GitHub/forum ETLs and ATIF relay. Override when the supported Ubuntu host stores its trusted bundle elsewhere. |
| `COMPATIBLE_API_KEY` | (none) | Inference API key. Mirrors NemoClaw's `REMOTE_PROVIDER_CONFIG.custom`. (`OPENAI_API_KEY` is also accepted.) |
| `GITHUB_TOKEN` | (none) | Optional GitHub access token for authenticated live REST reads. Also feeds the optional host GitHub mirror. |
| `GITHUB_READONLY_REPOS` | `NVIDIA/OpenShell` | Comma-separated exact allowlist for the live GitHub REST policy. Each item uses `owner/repository`. Recreate the sandbox after changing it. |
| `GITHUB_READONLY_REPO` | `NVIDIA/OpenShell` | Backward-compatible single-repository setting. It is used only when `GITHUB_READONLY_REPOS` is empty or absent. |
| `GITLAB_TOKEN` | (none) | Optional GitLab PAT. Use `read_api` scope; the sandbox receives only the OpenShell credential placeholder. |
| `GITLAB_READONLY_PROJECTS` | (none) | Comma-separated GitLab project paths (`group/project` or `group/subgroup/project`). Each receives its own GET-only policy rules when the sandbox is created. |
| `GITLAB_API_URL` | `https://gitlab.example.com/api/v4` | GitLab REST v4 base, formatted as `https://host[:port]/api/v4`. Replace the example hostname for your deployment; the provider and network policy remain scoped to its exact host and port. |
| `TAVILY_API_KEY` | (none) | Enables search-only public-web discovery. The host holds the raw API key; the sandbox receives an OpenShell placeholder. Recreate the sandbox after adding, changing, or removing it. |
| `NEMOCLAW_TAVILY_PREFLIGHT_TIMEOUT_SECONDS` | `10` | Maximum time for the bounded Tavily key-validation request during provider setup. |
| `SOURCE_ETL_GITHUB_ENABLED` | `0` | Set to `1` to start the host-side GitHub mirror. A live-read `GITHUB_TOKEN` alone does not enable the ETL. |
| `SOURCE_ETL_GITHUB_REPO` | `NVIDIA/NemoClaw` | Host-side GitHub mirror repository for source-etls. This is independent of the live GitHub allowlist. |
| `OUTLOOK_LOGIN_CACHE` | `1` | Controls the Microsoft refresh-token cache at `.bootstrap/cache/ms-graph-token.json`. `1` = use the cache (auto-refresh on staleness, ~90 days). `0` = skip the cache entirely (device-code every bring-up, nothing on disk; use on shared workstations or security-sensitive contexts). `2` = force device-code login and rewrite the cache. The gateway-side encrypted credential copy is unaffected by this knob. |
| `PHOENIX_COLLECTOR_ENDPOINT` | (none) | Set to e.g. `http://host.openshell.internal:6006/v1/traces` to stream OpenInference traces to a Phoenix collector. ATIF export is independent: local mode writes completed scopes to `/tmp/atif/`; relay mode sends them remotely and uses `/tmp/atif/` only for recovery after all remote targets fail. |
| `PHOENIX_PROJECT_NAME` | `default` | Sets `openinference.project.name` on every exported span so Phoenix routes traces to a named project. Override per-build to keep multiple deployments separate in the same Phoenix instance. |

## Verification (what success looks like)

The plumbing checks below confirm that the bridge and skill scripts are wired
correctly. For an end-to-end walkthrough that exercises each skill through
Slack DM and Outlook email, see
[docs/verify-functionality.md](docs/verify-functionality.md). The optional
web-search setup, positive check, and blocked-route checks are in
[docs/public-web-search.md](docs/public-web-search.md). For a cross-channel,
multi-user example where one user teaches the agent a new skill and a different
user invokes it after a full sandbox rebuild, see
[docs/collective-wisdom.md](docs/collective-wisdom.md).

For a bounded Slack transport check that identifies the last confirmed delivery
stage, run the guided diagnostic after sandbox creation:

```console
$ python3 scripts/slack_delivery_diagnostic.py --mode dm
$ python3 scripts/slack_delivery_diagnostic.py \
    --mode slash --slash-command /alice-nemoclaw
```

The command asks the operator to send the generated test value. It does not
send a Slack message as the operator. See
[Set Up Slack — Verify End-to-End Delivery](docs/set-up-slack.md#verify-end-to-end-delivery)
for the stage definitions, privacy boundary, and failure guidance.

```console
$ set -a; . ./.env; set +a

$ openshell sandbox list                      # hermes-direct should be ready
$ openshell sandbox exec --name hermes-direct -- \
    curl -sf http://localhost:8642/health     # {"status":"ok",...}
$ openshell sandbox exec --name hermes-direct -- \
    ls /usr/local/lib/nemoclaw-bridges/outlook/  # bridge present

# Verify the v2 outlook provider's gateway-managed refresh works end-to-end.
# The L7 proxy substitutes the placeholder with a live access token on egress.
$ openshell sandbox exec --name hermes-direct -- \
    curl -sS -H "Authorization: Bearer openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN" \
      'https://graph.microsoft.com/v1.0/me' | head -c 300

$ openshell sandbox exec --name hermes-direct -- env \
    OUTLOOK_TARGET_MAILBOX="$OUTLOOK_TARGET_MAILBOX" \
    /usr/bin/python3 /sandbox/.hermes-data/skills/outlook-email-search/scripts/search_emails.py \
      --query "nemoclaw" --since 7d           # {"ok": true, "count": N, ...}
```

> **Note 1:** `openshell sandbox exec` requires `--name <SANDBOX>` and a `--` separator before the command — without them, the sandbox name is parsed as the command itself (`hermes-direct: command not found`).
>
> **Note 2:** The verification points the search at `OUTLOOK_TARGET_MAILBOX` (the bot's own mailbox) because the delegated token always has access to it. Substituting `OUTLOOK_REPLY_TO` to query your *personal* mailbox via shared-folder access requires you to have granted the bot account delegate access in Outlook (**Outlook → File → Account Settings → Delegate Access**, or send a folder-share invitation); without that, Graph returns `HTTP 403: Cannot find row based on condition.`

## Tear-down

```console
$ bash scripts/tear-down.sh
```

Removes the sandbox, the Outlook/GitHub/Slack/Tavily providers, and any leftover
staged Dockerfile/policy files. **Does not** destroy the gateway or stop host services
(phoenix, postgres, ETLs, postgrest) by default — those are
typically long-lived. Opt-in flags (mutually exclusive):

- `--stop-host-services` — also stop the [extras/](extras/) stack (volumes preserved; delegates to `00-host-services.sh down`).
- `--purge-host-services` — also stop the stack AND wipe its volumes. Forces ETL re-scrape on the next `up`. Delegates to `00-host-services.sh down --volumes`.

Manual cleanup for less-common operations:

- `openshell gateway destroy --name "${OPENSHELL_GATEWAY:-openshell}"` — destroy the gateway (substitute `snap-docker` if you registered it under that name).
- `openshell provider delete compatible-endpoint` — remove the shared inference provider.

To stop *just* the host services without removing the sandbox:

```console
$ bash scripts/00-host-services.sh down
```

Add `--volumes` (or `-v`) to also wipe the source-etls Postgres data (forces ETL re-scrape on the next `up`). Outlook re-auth is independent — re-run `bash scripts/bring-up.sh` with `OUTLOOK_LOGIN_CACHE=2`.

## Persistence: collective wisdom across restarts

What survives a `tear-down.sh && bring-up.sh` cycle by default:

- **Postgres ETL data** — backed by the named Docker volume `source-etls-postgres-data` in [extras/docker-compose.yml](extras/docker-compose.yml). Survives unless you opt in to `--purge-host-services` (or run `bash scripts/00-host-services.sh down --volumes` directly).
- **Host services state** (phoenix's traces) — also volume-backed.
- **Microsoft refresh token** (in `.bootstrap/cache/ms-graph-token.json`; ignored by `.gitignore`) — survives tear-down/bring-up cycles, auto-refreshed on staleness. Set `OUTLOOK_LOGIN_CACHE=2` to force a fresh device-code login + cache rewrite, or `OUTLOOK_LOGIN_CACHE=0` to skip the cache altogether.

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

[scripts/snapshot.sh](scripts/snapshot.sh) excludes obvious
credential-bearing filenames (`.env`, `*secret*`, `*token*`,
`auth-profiles*`, etc.), the legacy writable `nvteam/` registry location, and
recognizable copies of `persona-authorities` files. The filter is name-based,
not content-aware. A snapshot can still contain sensitive conversation,
session, memory, or learned-skill content. Treat every snapshot as sensitive;
inspect and independently sanitize it before sharing.
[scripts/restore.sh](scripts/restore.sh) also rejects an archive that contains
a recognizable private authority registry path.

The `.snapshots/` directory is `.gitignore`'d.

For a hands-on demo of this in action — including a learned skill surviving a full rebuild and being invoked by a different user from a different channel — see [docs/collective-wisdom.md](docs/collective-wisdom.md).
