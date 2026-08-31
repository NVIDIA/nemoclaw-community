<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Memory-Driven Chief of Staff

Turn NemoHermes into an attention bridge for inbound conversations. This recipe
builds a source-backed work wiki and surfaces the decisions, replies, and
follow-ups that require the user's attention.

## From Message Overload to the Work That Needs You

Work arrives across threads and providers. NemoHermes rebuilds the context
needed to understand what changed and where the user must step in.

With this recipe, you can ask NemoHermes questions such as:

> **What changed on this project since yesterday?**
>
> **Which conversations need a decision, response, or follow-up from me?**
>
> **What are the most important items on my todo list today?**
>
> **What should I know about this person or project, and how does it connect to
> my work?**

NemoHermes turns the same inbound stream into one continuous workflow:

```text
direct messages · group chats · channels · email
                         │
                         ▼
              living, source-backed work wiki
                │                         │
                ▼                         ▼
       “What changed?”          “Where do I need to act?”
                │                         │
                └────────────┬────────────┘
                             ▼
                ranked attention recommendations
                             ▲
                             │
              user pins · ignores · corrections
```

Answers show what changed, where the user is needed, why an item matters, and
which sources support it. A message can update the wiki without becoming a todo;
an urgent broadcast can rank below work the user has chosen.

## Memory That Tracks Work, Not Just Preferences

[Hermes built-in memory](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory.md)
stores compact preferences, environment facts, and lessons across sessions.

This recipe tracks the work around the person in evolving, linked pages for
people, projects, goals, patterns, concepts, and current attention. Its
scheduled writer currently maintains people and attention pages from message
evidence and user corrections. It also keeps the evidence behind non-obvious
claims and the user's corrections to message-derived obligations.

> **Hermes built-in memory:** “What should the agent know about me?”
>
> **This recipe's operational memory:** “What changed around my work, what is
> the evidence, and where does my attention matter now?”

General personalization stays compact. Operational memory can grow with the
work while remaining linked, source-backed, schema-checked, and repairable. The
recipe complements Hermes memory and optional external memory providers.

## Table of Contents

- [From Message Overload to the Work That Needs You](#from-message-overload-to-the-work-that-needs-you)
- [Memory That Tracks Work, Not Just Preferences](#memory-that-tracks-work-not-just-preferences)
- [How It Works](#how-it-works)
- [Quick Start](#quick-start)
- [Offline Walkthrough (No Deployment)](#offline-walkthrough-no-deployment)
- [Configuration](#configuration)
- [Connect Messaging Providers](#connect-messaging-providers)
- [Scheduled Operation](#scheduled-operation)
- [Data Lifecycle and Privacy](#data-lifecycle-and-privacy)
- [Troubleshooting and FAQ](#troubleshooting-and-faq)
- [Limitations and Support](#limitations-and-support)
- [For Contributors](#for-contributors)

## How It Works

Hermes built-in memory remains available for general identity, preferences,
and learned facts. The recipe adds a workflow around three connected layers:

1. **Inbound signals** bring new information from configured messaging
   providers into a source-neutral format.
2. **The work wiki** organizes durable context about people, projects, goals,
   patterns, concepts, and current attention, with provenance and maintenance
   rules. Its scheduled writer currently maintains people and attention pages,
   and user-confirmed identity links connect the same person across providers.
3. **The attention layer** uses that context to identify work that requires the
   user's response, decision, or follow-up; recommend priorities; and preserve
   the user's corrections over time.

```text
configured IM providers ──► normalized inbound signals
                                      │
                   ┌──────────────────┴─────────────────┐
                   ▼                                    ▼
        self-maintaining work wiki             attention recommendations
 people · projects · goals · patterns        ranked obligations · todos
                   │                                    ▲
                   └──► sourced retrieval               │
                                                        │
                    user corrections ──► learned preferences

Hermes built-in memory ──► general profile and cross-session context
```

The model does not write SQL. It returns a versioned JSON envelope;
`apply_decisions.py` validates that envelope and applies it transactionally.
The offline walkthrough substitutes recorded envelopes only at the two points
where inference would otherwise be required. Everything downstream is the same
code used by scheduled runs.

### Core concepts

<!-- markdownlint-disable MD013 -->
| Term | Meaning |
| --- | --- |
| Profile home | One Hermes profile directory, named by `HERMES_HOME` |
| Hermes built-in memory | Bounded `USER.md` and `MEMORY.md` notes for general personalization and learned facts |
| Work wiki | Schema-checked pages for people, projects, goals, patterns, concepts, and attention |
| Provenance | Source, evidence date, and trust attached to non-obvious wiki claims |
| Attention layer | Ranked recommendations for inbound work that may require the user's response, decision, or follow-up |
| Obligation ledger | Message judgments, corrections, and audit history at `$HERMES_HOME/workspace/ledger/state.db` |
| Obligation | A source message that still needs a response or action |
| Intent gate | Proof in memory that the user chose the work; required for `high` |
| Wake gate | The last non-empty selector line that tells Hermes not to call the model |
| Envelope | Versioned JSON containing model decisions for the transactional writer |
<!-- markdownlint-enable MD013 -->

## Quick Start

This is the path that ends with a running, scheduled assistant. It assumes an
existing NemoClaw-managed Hermes sandbox; it does not cover NemoClaw
onboarding itself.

The scheduled jobs run inside a Linux NemoHermes sandbox. Your own computer is
outside that sandbox and can use any platform supported by NemoHermes.

This guide uses two command locations:

<!-- markdownlint-disable MD013 -->
| Location | What it means | CLI available there |
| --- | --- | --- |
| Your machine, outside the sandbox | The terminal with the repository checkout that you use to manage NemoHermes | `nemohermes`, `openshell` |
| NemoHermes sandbox | The isolated Linux environment where Hermes and the scheduled jobs run | `hermes` |
<!-- markdownlint-enable MD013 -->

The sandbox satisfies the recipe's Linux runtime requirement. The current
provider setup helpers still require Linux or WSL on your machine; this is a
helper-script limitation, not a recipe runtime requirement.

`scripts/install.sh` always runs inside the sandbox. Your machine is not
expected to have `hermes` on `PATH`.

### 1. Confirm and inspect a Hermes sandbox from your machine

If NemoClaw is not installed, follow the upstream
[NemoClaw setup guide](https://github.com/NVIDIA/NemoClaw) and select Hermes,
an inference provider, and a model during onboarding.

```bash
nemohermes my-hermes status
openshell sandbox provider list my-hermes
```

Replace `my-hermes` in this section with your registered sandbox name.

Before starting scheduled intake, inspect every provider already attached to
the sandbox:

```bash
openshell provider get "<provider-name>"
```

Do not continue if an unrelated provider exposes `MS_GRAPH_ACCESS_TOKEN`.
The current Graph collector can see the injected environment value but cannot
identify which attached provider supplied it. Use a dedicated sandbox or
detach the conflicting provider before installing or starting the scheduled
runtime.

### 2. Upload the recipe from your machine

Run this from the cloned `nemoclaw-community` repository root.

```bash
nemohermes sandbox upload my-hermes \
  examples/recipes/nvidia/memory-driven-chief-of-staff \
  /sandbox
nemohermes my-hermes connect
```

The upload is required: the sandbox cannot see the checkout on your machine.
After `connect` opens a shell, the remaining commands in this subsection run
**inside the sandbox**.

### 3. Install the profile and jobs inside the sandbox

```bash
cd /sandbox/memory-driven-chief-of-staff
export PROFILE_NAME="memory-driven-chief-of-staff"
bash scripts/install.sh
```

The installer creates the target profile and copies only `model.default`,
`model.provider`, and `model.base_url`. It never copies a credential. On a first
run without a target-profile credential, it
stops before registering jobs.

In a NemoClaw-managed sandbox, set the non-secret OpenShell rewrite sentinel,
then rerun the installer:

```bash
hermes -p "$PROFILE_NAME" config set model.api_key \
  "sk-OPENSHELL-PROXY-REWRITE"
bash scripts/install.sh
```

The sentinel is not an upstream API key. Hermes requires an `sk-`-prefixed
value before it sends a request, and OpenShell removes this marker and
injects the managed inference credential at the egress boundary. Use the
exact sentinel above rather than another placeholder — do not copy a real
inference key into the recipe profile on the supported NemoClaw path.

> **Not on NemoClaw, and your endpoint genuinely needs no key?** This opt-out
> is not a substitute for the rewrite sentinel above — use it only for a
> genuinely keyless, non-NemoClaw endpoint.
>
> ```bash
> ALLOW_NO_API_KEY=1 bash scripts/install.sh
> ```

### 4. Start and verify the scheduled runtime inside the sandbox

NemoClaw's own supervisor launches and continuously respawns `hermes gateway
run` for the sandbox's default profile automatically. This recipe installs
as a separate, named profile (`memory-driven-chief-of-staff`), which that
supervision does not cover — there is no NemoClaw-managed lifecycle for a
second named-profile gateway today, so this step starts and tracks it by
hand. Check first whether it is already running, to avoid starting a second,
orphaned instance:

```bash
hermes -p "$PROFILE_NAME" cron status
```

If it reports the gateway is not running, start it in the background and
record its PID. Unlike NemoClaw's own gateway, nothing restarts this one
automatically — if it dies (crash, OOM, sandbox restart), cron stops firing
until you notice and rerun this:

```bash
nohup hermes -p "$PROFILE_NAME" gateway run > /tmp/gateway.log 2>&1 &
echo $! > /tmp/mdcos-gateway.pid
disown
hermes -p "$PROFILE_NAME" cron status
```

`cron status` should now report the gateway running, its PID (matching `cat
/tmp/mdcos-gateway.pid`), and the next scheduled job. If it still reports not
running, check `/tmp/gateway.log` for a startup error.

To stop it later:

```bash
kill "$(cat /tmp/mdcos-gateway.pid)"
rm -f /tmp/mdcos-gateway.pid
```

> **Running this outside a NemoClaw sandbox, on a host with systemd?** Any
> environment without a running systemd — WSL included — still needs the
> foreground command above. Only where systemd is actually running does
> `gateway install` register it as a persistent service instead. See
> [Persistence and reboot behavior](#persistence-and-reboot-behavior) for the
> trade-off against `gateway run`.
>
> ```bash
> hermes -p "$PROFILE_NAME" gateway install
> hermes -p "$PROFILE_NAME" gateway start
> ```

At this point the schedule works over any rows already in the store. Slack and
Outlook are independent and optional; each unconfigured collector exits
successfully and reports that state.

### 5. Connect a messaging provider

Step 4 leaves you inside the sandbox shell. Exit it (or open a separate
terminal on your machine) before continuing — `openshell` and `nemohermes`
are host-side commands and are not available inside the sandbox.

Nothing so far requires a provider — the profile, jobs, and gateway all work
with an empty store. But an empty store is exactly what you will see if you
chat with it next: no messages ingested, nothing to rank. Check what is
already attached first, from your machine:

```bash
openshell sandbox provider list my-hermes
```

If nothing there exposes `SLACK_USER_TOKEN` or `MS_GRAPH_ACCESS_TOKEN`,
connect one now — see [Connect Messaging Providers](#connect-messaging-providers)
below for the full Slack and Outlook setup. Both are optional and
independent; connect one, both, or skip this step and use the
[offline fixtures](#offline-walkthrough-no-deployment) instead to see the
recipe's behavior without connecting anything.

### 6. A note on the web dashboard

`nemohermes hermes dashboard-url --quiet` (from your machine, not inside the
sandbox) prints a URL for the Hermes dashboard NemoClaw forwards for the
sandbox by default. That dashboard is launched isolated, under its own
dedicated profile home, specifically so it does **not** unify with other
profiles on the sandbox — it will not show this recipe's chat, memory, or
store, regardless of any `?profile=` query parameter appended to it. The
printed URL also carries a credential in its fragment; treat it like a
password and use it as printed, not retyped or shared.

The verified way to talk to this recipe is the terminal, from inside the
sandbox:

```bash
hermes -p memory-driven-chief-of-staff chat
```

A dedicated web view scoped to this one profile is possible through Hermes's
own `hermes dashboard --isolated`, run from inside the sandbox against this
profile — but that path (port choice, forwarding it out of the sandbox, and
its authentication flow) is not walked through end-to-end in this guide; see
Hermes's own dashboard documentation before relying on it.

### Things to try

Once real data is flowing, ask it the questions from the top of this
document:

> **What changed on this project since yesterday?**
>
> **Which conversations need a decision, response, or follow-up from me?**
>
> **What are the most important items on my todo list today?**
>
> **What should I know about this person or project, and how does it connect
> to my work?**

Then push on the ranking itself — this is where the intent gate shows up:

- "Why is this ranked above that?"
- "What's urgent right now that I haven't actually chosen to work on?"

Ask it to ground a claim in evidence rather than answer from general recall:

- "What should I know about [a real colleague]? How does it connect to my
  current work?"
- "What did [someone] say this week?"

And after you correct something (`priority ... low` or `ignore ...` via
`profile/scripts/correct.py`), ask again without re-explaining the
correction — it should already be reflected.

## Offline Walkthrough (No Deployment)

This does not deploy the recipe or produce a running assistant. It runs the
decision logic — ranking, the intent gate, correction durability, memory
self-checks — entirely on your own machine against recorded fixtures, with no
NemoClaw, no sandbox, no credentials, and no network access. Use it to verify
the recipe's behavior before investing in a real deployment, or skip straight
to [Quick Start](#quick-start) above if you already have a sandbox ready.

It needs only Python 3.10+ on macOS, Linux, or WSL.

### 1. Clone and enter the recipe

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/recipes/nvidia/memory-driven-chief-of-staff
```

### 2. Create isolated local state and run the walkthrough

```bash
export RECIPE_TMP_HOME="$(mktemp -d)"
export HERMES_HOME="$RECIPE_TMP_HOME"
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

The command prints seven stages and exits with status `0`. The important
outcomes are:

- eight messages are ingested and two are skipped;
- six obligations remain open;
- exactly three memory-gated obligations enter `high`;
- an urgent deadline unrelated to the user's chosen work stays in `medium`;
- a user pin and ignore survive a later recorded review;
- the memory checker is shown succeeding and failing on a deliberate defect.

### 3. Prove fixture ingestion is idempotent

Use a new profile home because the walkthrough has already populated the first
one.

```bash
export RECIPE_TMP_HOME_2="$(mktemp -d)"
export HERMES_HOME="$RECIPE_TMP_HOME_2"
python3 profile/scripts/load_fixtures.py --fixtures fixtures
python3 profile/scripts/load_fixtures.py --fixtures fixtures
```

The first loader run reports `"added": 8`; the second reports `"added": 0`.

### 4. Inspect or correct state

Replace the placeholder with a source identifier printed by the walkthrough.

```bash
python3 profile/scripts/memory_check.py
python3 profile/scripts/correct.py priority msg-priorities-match low
python3 profile/scripts/correct.py ignore msg-cc-only
python3 profile/scripts/correct.py unignore msg-cc-only
```

Repeated corrections are no-ops. Corrections against completed or incompatible
rows exit with status `3` and explain the required state transition.

## Configuration

### Environment variables

<!-- markdownlint-disable MD013 -->
| Name | Location | Required | Default / valid range | Meaning |
| --- | --- | --- | --- | --- |
| `HERMES_HOME` | Offline or sandbox | Yes for stateful scripts | No default | Existing Hermes profile home; state is written below `workspace/` |
| `PROFILE_NAME` | Sandbox installer | No | `memory-driven-chief-of-staff` | Target profile for installation and cron registration |
| `ALLOW_NO_API_KEY` | Sandbox installer | No | `0`; set to `1` only for a genuinely keyless non-NemoClaw endpoint | Explicit credential-check bypass; do not use for a managed NemoClaw route |
| `INTAKE_SLICE` | Scheduled runtime | No | `25`; integer `1..200` | Maximum pending rows given to an intake turn |
| `REVIEW_BATCH` | Scheduled runtime | No | `15`; integer `1..200` | Maximum open rows given to a review turn |
| `INTAKE_SLACK_BUDGET` | Scheduled runtime | No | `10`; integer `1..200` | Maximum Slack history calls per intake tick |
| `MEMORY_WINDOW_DAYS` | Scheduled runtime | No | `30`; integer `1..3650` | Evidence window used by the memory-writing selector |
| `RETENTION_DAYS` | Scheduled runtime | No | `30`; integer `1..3650` | Age at which stored message bodies are cleared |
| `SLACK_USER_TOKEN` | OpenShell provider | Injected | Rotating user token | Collector credential; do not set manually on the supported path |
| `MS_GRAPH_ACCESS_TOKEN` | OpenShell provider | Injected | Rotating delegated token | Outlook collector credential; the collector cannot currently attest which attached provider supplied it |
| `GRAPH_BACKFILL_DAYS` | Scheduled runtime | No | `7`; integer `1..3650` | Initial Outlook mailbox synchronization window |
| `GRAPH_CLIENT_ID` | Outlook setup on your machine | Yes | No default | Microsoft Entra application client ID |
| `GRAPH_TENANT_ID` | Outlook setup on your machine | No | `common` | Microsoft Entra directory tenant ID |
| `GRAPH_PROVIDER_NAME` | Outlook setup on your machine | No | `memory-driven-cos-graph` | Name used when creating the recipe provider; it does not resolve a conflicting attached provider that exposes the same credential key |
| `SANDBOX_STORAGE_PATH` | Provider setup on your machine | Yes | No default | Path whose encryption status protects sandbox storage |
| `OPENSHELL_SANDBOX_NAME` | Provider setup on your machine | No | Falls back to `SANDBOX_NAME`, then `hermes` | Sandbox receiving the provider |
| `SANDBOX_NAME` | Provider setup on your machine | No | `hermes` | Compatibility fallback for the sandbox name |
| `SLACK_PROVIDER_NAME` | Slack setup on your machine | No | `memory-driven-cos-slack-user` | OpenShell provider name |
| `STORE_ENCRYPTION_ACKNOWLEDGED` | Provider setup on your machine | No | `0`; unattended confirmation is `1` | Acknowledges an encryption result the script cannot prove |
| `FORCE_REAUTH` | Provider setup on your machine | No | `0`; replacement is `1` | Replaces an attached rotating provider credential |
<!-- markdownlint-enable MD013 -->

Scheduled environment variables must reach the target profile. Persist a value
through the profile environment file returned by Hermes rather than relying on
a temporary shell export. See [docs/data-lifecycle.md](docs/data-lifecycle.md)
for retention and memory settings, and
[docs/set-up-graph.md](docs/set-up-graph.md) for Outlook backfill.

### Public Slack channels

Direct messages and group DMs are discovered automatically. Public channels
are read only when explicitly listed at
`$HERMES_HOME/workspace/slack_channels.json`.

```json
{
  "channels": ["C0TEAM0001", "C0PROJECT2"]
}
```

### Ingest exclusions

Create `$HERMES_HOME/workspace/exclusions.json` to prevent matching rows from
ever reaching the store. Matching is exact and case-insensitive; glob patterns
are not supported. Invalid or unknown fields fail closed.

```json
{
  "senders": ["recruiter@agency.example", "U01RECRUIT"],
  "domains": ["agency.example"],
  "channels": ["C0SALARY01", "D0PRIVATE1"]
}
```

## Connect Messaging Providers

Slack and Microsoft Outlook are independent, optional inputs. Configure either
one or both after installing the recipe and setting any intake exclusions.
Each setup script requires encrypted sandbox storage and attaches a read-only
OpenShell provider to the NemoHermes sandbox.

### Profile configuration

The installer has already created the target profile from
`profile/distribution.yaml`. Its model block should have this shape:

```yaml
model:
  default: "<provider/model>"
  provider: "<provider>"
  base_url: "<https-endpoint>"
  api_key: sk-OPENSHELL-PROXY-REWRITE
```

The `api_key` value is the non-secret routing marker configured during
installation. OpenShell replaces it at egress; it is not a credential to rotate
or hide.

Provider setup now continues on **your machine, outside the sandbox**. The
current setup helpers require a Linux shell; use WSL on Windows.

### Slack

Slack setup is optional. Complete it only after placing the sandbox storage on
an encrypted volume; owner-only permissions are access control, not encryption.
See [docs/encrypted-storage.md](docs/encrypted-storage.md) first.

Run the setup script from the recipe checkout on **your machine**, not inside
the sandbox. Your machine has `openshell`; the sandbox has `hermes`.

```bash
export SANDBOX_STORAGE_PATH="<path-containing-sandbox-storage>"
export OPENSHELL_SANDBOX_NAME="my-hermes"
bash scripts/setup-slack.sh
```

The script imports `docs/slack_app_manifest.json`, requests user scopes, checks
the provider type and read-only policy, configures token rotation, and attaches
the provider to the named sandbox. The required scopes are:

```yaml
user_scopes:
  - im:read
  - im:history
  - mpim:read
  - mpim:history
  - channels:read
  - channels:history
  - users:read
```

Static user tokens, bot tokens, and app tokens are refused. Attachments are not
downloaded. Full setup and workspace-admin recovery steps are in
[docs/set-up-slack.md](docs/set-up-slack.md).

Verify the live collector from your machine through the supported sandbox exec
path. Replace both placeholders.

```bash
nemohermes my-hermes exec \
  --workdir /sandbox/memory-driven-chief-of-staff \
  -- env HERMES_HOME=/sandbox/.hermes/profiles/memory-driven-chief-of-staff \
  python3 profile/scripts/ingest_slack.py --recheck
```

Collector exit codes are stable diagnostics:

| Exit | Meaning |
| --- | --- |
| `0` | Fetch succeeded, or Slack is intentionally unconfigured |
| `1` | Other collector error |
| `2` | Missing/wrong credential type or unreachable API |
| `3` | Slack rate limit |
| `4` | Required Slack scope missing |

### Microsoft Outlook

Outlook intake uses the Microsoft Graph inbox delta API. Register a Microsoft
Entra application with public-client flows enabled and delegated `Mail.Read`,
`User.Read`, and `offline_access` permissions. Do not grant application-level
mail permissions, which would authorize access beyond the signed-in mailbox.

Run the device-code setup from the recipe checkout on your machine:

```bash
export SANDBOX_STORAGE_PATH="<path-containing-sandbox-storage>"
export OPENSHELL_SANDBOX_NAME="my-hermes"
export GRAPH_CLIENT_ID="<entra-application-client-id>"
export GRAPH_TENANT_ID="<entra-directory-tenant-id>"
bash scripts/setup-graph.sh
```

If the script reports that another attached provider already exposes
`MS_GRAPH_ACCESS_TOKEN`, treat that as a hard stop. Detach the conflicting
provider or use a dedicated sandbox, then rerun setup. Do not run the Graph
collector while the credential source is ambiguous.

On the supported path, the gateway stores and refreshes the delegated
credential, and the sandbox receives only an OpenShell placeholder. Confirm
that the attached provider has type `memory-driven-cos-graph-user` and that its
exported profile declares `access: read-only` with `enforcement: enforce` before
running the collector. The initial synchronization covers seven days by default
and resumes across intake ticks when more pages remain. Configure a different
`GRAPH_BACKFILL_DAYS` in the profile environment file before the first
synchronization. See [docs/set-up-graph.md](docs/set-up-graph.md) for the
application registration, provider inspection, backfill, revocation, and
recovery steps.

### Link identities across providers

Slack identifies a person by user ID, while email uses an address. The recipe
never assumes that matching display names belong to the same person. The memory
job reports likely matches as `identity_candidates`; only the user can confirm
or reject them.

Run the identity command from your machine through sandbox exec:

```bash
nemohermes my-hermes exec \
  --workdir /sandbox/memory-driven-chief-of-staff \
  -- env HERMES_HOME=/sandbox/.hermes/profiles/memory-driven-chief-of-staff \
  python3 profile/scripts/link_identity.py same \
    slack:U01DANA email:dana@example.com
```

Use `different` instead of `same` to reject a match. Confirmed relationships
compose across providers. Rejected candidates are not proposed again. If saved
answers conflict, the recipe reports `identity_conflicts` and changes nothing.
Existing page names remain stable after identities are linked so that index
entries and source-backed links do not move.

### Collector failures

When a collector fails, the intake batch records only its name, exit code, and
error class. It does not place collector output in the model prompt or the
scheduler log because that output can contain message text or authentication
material. Run the collector directly to inspect its full error.

Verify the collector from your machine:

```bash
nemohermes my-hermes exec \
  --workdir /sandbox/memory-driven-chief-of-staff \
  -- env HERMES_HOME=/sandbox/.hermes/profiles/memory-driven-chief-of-staff \
  python3 profile/scripts/ingest_graph.py --recheck
```

Outlook collector exit codes are:

| Exit | Meaning |
| --- | --- |
| `0` | Fetch succeeded, can resume, or Outlook is unconfigured |
| `1` | Other collector error |
| `2` | Missing, invalid, or refused credential |
| `3` | Microsoft Graph rate limit |
| `4` | Token is not a delegated mailbox token with the required scopes |

## Scheduled Operation

`scripts/register-jobs.sh` is idempotent: it edits jobs with matching names
instead of creating duplicates.

| Job | Schedule | Pre-step | Skill |
| --- | --- | --- | --- |
| intake | every 30 minutes | `select_intake.py` | `inbound-judging` |
| review | every 6 hours | `select_review.py` | `obligation-review` |
| memory writing | daily 01:00 | `select_memory.py` | `memory-writing` |
| retention | daily 02:00 | `retention.py` | — |
| memory repair | daily 03:00 | — | `memory-repair` |
| memory consolidation | daily 04:00 | — | `memory-consolidation` |
| preference update | daily 04:30 | — | `preference-update` |

Intake, review, and memory writing run their selector before an agent turn. If
no work is available, the selector's final non-empty line is the wake gate and
Hermes skips inference. Retention never wakes the agent. Memory writing runs
before repair and consolidation so every new page is checked and compacted in
the same nightly sequence.

### Persistence and reboot behavior

Jobs live in `$HERMES_HOME/cron/jobs.json`. The distribution does not own the
`cron` path, so profile updates leave job definitions and run history unchanged.

Jobs survive a reboot. Do they resume automatically?
Only if the gateway was installed as a service with `gateway install`. A
gateway started with `gateway run` is a foreground process and must be started
again after a reboot.

What happens to recurring runs missed while the gateway was down? One of them
runs, not the entire backlog. Hermes advances the schedule and runs once over
current state. A machine that was off for two days does not wake to ninety-six
intake runs; it wakes to one and then resumes its half-hourly schedule.

List or remove registered jobs inside the sandbox.

```bash
hermes -p memory-driven-chief-of-staff cron list
JOB_ID="<copy-an-id-from-the-list>"
hermes -p memory-driven-chief-of-staff cron remove "$JOB_ID"
```

Deleting the profile also deletes its workspace, store, and memory.

```bash
hermes profile delete memory-driven-chief-of-staff
```

## Data Lifecycle and Privacy

**Network boundary:** the offline walkthrough makes no network requests.
Scheduled jobs call the configured inference endpoint only when work is found.
The shipped provider profiles declare read-only access to `slack.com` and
`graph.microsoft.com`, and the shipped collectors contain no source-system
write operations.

> **Runtime provenance limitation:** the effective network boundary is the
> policy of the provider actually attached to the sandbox, not the YAML file in
> this checkout. `ingest_graph.py` currently trusts whichever attached provider
> supplies `MS_GRAPH_ACCESS_TOKEN`; it does not verify the provider name, type,
> or policy at runtime. A different provider exposing the same key can therefore
> bypass the setup-time refusal. Inspect the attached providers on your machine
> and do not run Graph intake unless the effective provider is the recipe's
> read-only, enforced profile.

**Source-system behavior:** the shipped collectors read Slack and the signed-in
Outlook mailbox but do not post, reply, edit, delete, move, or mark messages as
read. This describes the collector code; it is not a claim that an unrelated
read-write provider attached to the same sandbox would refuse writes from other
code.

- The offline fixtures are entirely synthetic and make no network request.
- Recipient lists are reduced to `direct`, `mentioned`, or `broadcast` and are
  never stored.
- Message bodies are cleared after 30 days by default; metadata, obligation
  state, and audit history remain.
- Exclusions are enforced at the shared insert boundary, before a row reaches
  the store.
- Export includes the complete store, memory, and learned policy in Markdown
  and JSON.
- Slack content deleted at the source is not detected immediately because a
  bounded history read cannot distinguish deletion from an older page. It ages
  out through retention.
- Outlook messages removed from the inbox are reconciled through Microsoft
  Graph. A confirmed deletion is tombstoned and its body is cleared immediately;
  the metadata, obligation, and audit history remain. A move to another folder
  is not treated as a deletion.
- Microsoft Graph files in `fixtures/` remain synthetic and exercise the same
  normalization path without contacting a mailbox.

The store and memory directories are created with owner-only permissions. That
does not protect a lost disk, disk image, or unencrypted backup. Before
connecting Slack or Outlook, follow
[docs/encrypted-storage.md](docs/encrypted-storage.md).

## Troubleshooting and FAQ

### `HERMES_HOME` is unset, missing, or points at the checkout

Stateful scripts require an existing profile-like directory and refuse a file,
a missing path, or an occupied non-profile directory. For an offline run, make
a fresh directory and export it first.

```bash
export HERMES_HOME="$(mktemp -d)"
```

### The walkthrough refuses a second run

The walkthrough demonstrates a clean first run and rejects state that contains
old corrections. Create a new temporary profile home.

```bash
export HERMES_HOME="$(mktemp -d)"
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

### Collector tests try to reach the real network or report HTTP 503

The Slack and Outlook tests use local HTTP stand-ins at `127.0.0.1`. If your
shell sets a proxy without a localhost bypass, the proxy can intercept those
requests. The documented test command extends both `NO_PROXY` and `no_proxy`;
for an individual test, apply the same bypass first.

```bash
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost"
export no_proxy="${no_proxy:+$no_proxy,}127.0.0.1,localhost"
python3 profile/scripts/tests/test_ingest_slack.py
python3 profile/scripts/tests/test_ingest_graph.py
```

### The installer says the platform is unsupported

The offline path runs on macOS, Linux, and WSL. Scheduled skills require the
Linux environment inside a NemoHermes sandbox. If `scripts/install.sh` reports
another platform, run it inside the sandbox rather than on your machine.

### The installer reports no model or API credential

The new profile receives three model routing settings but never a copied
secret. Set `model.default` if the source profile had none. On NemoClaw, set the
OpenShell rewrite sentinel as the target profile's `model.api_key`, then rerun
the installer.

```bash
MODEL_ID="<provider/model>"
hermes -p memory-driven-chief-of-staff \
  config set model.default "$MODEL_ID"
hermes -p memory-driven-chief-of-staff \
  config set model.api_key "sk-OPENSHELL-PROXY-REWRITE"
bash scripts/install.sh
```

The sentinel is a non-secret routing marker. Do not use
`ALLOW_NO_API_KEY=1` for a NemoClaw-managed inference route.

### How do I check whether my API key actually works, and replace it if not?

The real key does not live in this recipe's profile — the sentinel above is
not a credential. Check and rotate it at the NemoClaw/OpenShell layer, from
your machine, not inside the sandbox:

```bash
nemohermes my-hermes inference get
```

This reports the configured provider and model, but sends no request, so it
cannot tell you whether the key is valid. The global `nemohermes status`
(no sandbox name) cannot either — that reachability check counts HTTP
`401`/`403` as "reachable." The named-sandbox form does validate it, because
it sends one real inference request through the stored credential:

```bash
nemohermes my-hermes status
```

It reports `unauthorized` when that request is rejected with `401`/`403`.
For a final, recipe-level confirmation, also try a real chat turn inside the
sandbox:

```bash
hermes -p memory-driven-chief-of-staff chat
```

A real reply means the key works; an authentication error means it does not.

If it is wrong, replace it from your machine — do not edit the recipe
profile's `model.api_key`, which only ever holds the non-secret rewrite
sentinel. Export the replacement under the environment variable name your
configured provider expects, then rerun onboarding for the existing sandbox:

```bash
printf 'New inference API key: ' >&2
IFS= read -r -s PROVIDER_API_KEY_VAR_NAME
printf '\n' >&2
export PROVIDER_API_KEY_VAR_NAME
nemohermes onboard --name my-hermes \
  --non-interactive --yes --yes-i-accept-third-party-software
unset PROVIDER_API_KEY_VAR_NAME
```

`PROVIDER_API_KEY_VAR_NAME` above is a placeholder — substitute the actual
variable name your provider expects (this differs by provider; NemoClaw's
own credential rotation guide lists them). This updates the registered
OpenShell provider and normally reuses the existing sandbox; it does not
touch this recipe's installed profile or its scheduled jobs. Confirm the
replacement the same way — `nemohermes my-hermes status` or a real request,
not `inference get` or the global `status`.

### Jobs are registered but do not run

Registration does not start the scheduler. Check the gateway and cron status.

```bash
hermes -p memory-driven-chief-of-staff gateway status
hermes -p memory-driven-chief-of-staff cron status
```

Install and start the service, or use the foreground command shown in
[Quick Start](#quick-start).

### A collector reports `unconfigured`

That is a supported state. The scheduler continues over existing store rows.
Enable the source by running `scripts/setup-slack.sh` or
`scripts/setup-graph.sh` on your machine, then run its collector with
`--recheck` through sandbox exec.

### Provider setup says `openshell` is missing

The setup command is running inside the sandbox or on a machine without
OpenShell. Return to the checkout on your machine and confirm the CLI and
sandbox name.

```bash
command -v openshell
openshell sandbox list
```

### Slack is rate-limited or missing a scope

The collector exits `3` for a rate limit and `4` for a missing scope. Reduce
the named public channels or call budget for rate limits. For missing scopes,
have the workspace administrator grant the manifest scopes, reinstall the app,
and replace the rotating credential as described in
[docs/set-up-slack.md](docs/set-up-slack.md).

### Outlook synchronization is incomplete, rate-limited, or rejected

`"complete": false` means the bounded initial synchronization will resume on
the next intake tick. Exit `3` means Microsoft Graph rate-limited the current
round. Exit `4` means the token is not a delegated mailbox token with the
required `Mail.Read` and `User.Read` scopes. Follow the recovery steps in
[docs/set-up-graph.md](docs/set-up-graph.md).

### Graph setup refuses an attached provider with the same credential key

Treat the refusal as a provider collision. From your machine, inspect and
detach the conflicting provider or use a dedicated sandbox before starting
Graph intake.

```bash
openshell sandbox provider list my-hermes
openshell provider get "<provider-name>"
```

### Does the recipe modify Outlook or Slack?

The shipped collectors do not. They normalize source records into a local
SQLite store and contain no post, reply, move, delete, or mark-as-read calls.
The shipped provider profiles also declare read-only access. However, verify
the provider actually attached to the sandbox: the current Graph collector
cannot attest which provider supplied `MS_GRAPH_ACCESS_TOKEN`, so a foreign
read-write provider would make the platform-level write-refusal claim false.

## Limitations and Support

- Scheduled jobs require the Linux environment inside a NemoHermes sandbox.
  The current provider setup helpers require Linux or WSL on your machine.
- Recorded judgment turns test the workflow, not model quality.
- Live connectors currently cover Slack and a Microsoft Outlook inbox through
  Microsoft Graph. Other messaging providers need their own collector and
  OpenShell provider policy.
- Graph credential provenance is not yet enforced at collector runtime. An
  unrelated attached provider exposing `MS_GRAPH_ACCESS_TOKEN` can be used even
  after `setup-graph.sh` refuses it. Use a dedicated sandbox or remove the
  collision before enabling Graph intake.
- Slack deletion is not observed immediately; retention clears old bodies.
- The scheduled writer maintains people and attention pages. Other page types
  have schemas but no automatic writer.
- Memory compaction is model-guided. `memory_check.py` detects invariant and
  ceiling violations but does not invent a safe consolidation.
- Append-only reranking events are not compacted.
- This is a reference recipe for one user's work stream on a machine they
  control, not a hosted service or a production-readiness claim.

This NVIDIA-authored recipe was proposed and reviewed in
[NemoClaw Community #122](https://github.com/NVIDIA/nemoclaw-community/issues/122).
Support is best effort under the repository [support policy](../../../../SUPPORT.md).
Security reports should follow [SECURITY.md](../../../../SECURITY.md).

## For Contributors

The following sections document the implementation, contracts, and evidence
used to review or extend this recipe.

### Project Structure

Paths below are relative to this recipe directory.

<!-- markdownlint-disable MD013 -->
```text
memory-driven-chief-of-staff/
├── README.md                         # Start here: setup, operation, and API contract
├── profile/
│   ├── distribution.yaml            # Version, Hermes requirement, owned paths
│   ├── SOUL.md                       # Chief-of-staff persona and response boundary
│   ├── schema.md                     # Memory page types, provenance, decay, ceilings
│   ├── seed/                         # Initial index and attention pages for a new memory
│   ├── scripts/
│   │   ├── schema.sql                # Current v5 SQLite store schema
│   │   ├── schema-v1.sql             # Frozen schemas used by migration tests
│   │   ├── schema-v2.sql
│   │   ├── schema-v3.sql
│   │   ├── schema-v4.sql
│   │   ├── _db.py                    # Profile-home, connection, and transaction boundary
│   │   ├── identity.py               # Cross-provider identity relation resolver
│   │   ├── link_identity.py          # User command for identity confirmations
│   │   ├── normalize.py              # Source payloads to source-neutral item rows
│   │   ├── ingest_graph.py           # Optional read-only Outlook mailbox collector
│   │   ├── ingest_slack.py           # Optional read-only Slack collector
│   │   ├── select_intake.py          # Intake batch selector and wake gate
│   │   ├── select_review.py          # Review batch selector and wake gate
│   │   ├── select_memory.py          # Evidence selector for scheduled wiki writing
│   │   ├── apply_decisions.py        # Validates and commits agent envelopes
│   │   ├── ranking.py                # Deterministic cap, reservation, and cascade
│   │   ├── correct.py                # User pin, ignore, and unignore writer
│   │   ├── walkthrough.py            # Offline end-to-end entry point
│   │   ├── retention.py              # Scheduled message-body clearing
│   │   ├── exclusions.py             # Sender, domain, and channel filtering
│   │   ├── export_store.py           # Complete Markdown and JSON export
│   │   ├── reset.py                  # Store, memory, and policy reset
│   │   ├── migrate.py                # Forward-only store migration
│   │   ├── memory_check.py           # Deterministic memory invariant checker
│   │   └── tests/                    # 14 direct-execution unittest modules
│   └── skills/
│       ├── inbound-judging/          # New-message judgment instructions
│       ├── obligation-review/        # Scheduled re-judgment instructions
│       ├── memory-writing/            # Evidence-grounded people and attention pages
│       ├── memory-repair/            # Safe invariant repair instructions
│       ├── memory-consolidation/     # Bounded compaction instructions
│       └── preference-update/        # Repeated-correction learning instructions
├── fixtures/
│   ├── README.md                     # Fixture schema, controls, and provenance
│   ├── graph_messages.json           # Five synthetic Graph-shaped messages
│   ├── slack_messages.json           # Three synthetic Slack-shaped messages
│   ├── envelopes/intake.json         # Recorded intake model turn
│   └── memory/                       # Synthetic seed memory for the walkthrough
├── providers/
│   ├── graph-user.yaml               # Read-only delegated Graph mailbox policy
│   └── slack-user.yaml               # Read-only Slack endpoint and credential policy
├── scripts/
│   ├── install.sh                    # Sandbox: install profile and register jobs
│   ├── register-jobs.sh              # Sandbox: idempotent Hermes cron registration
│   ├── require-encrypted-storage.sh  # Shared connector storage prerequisite
│   ├── require-linux.sh              # Shared scheduled-runtime platform check
│   ├── setup-graph.sh                # Outside sandbox: authorize and attach Outlook access
│   ├── setup-slack.sh                # Outside sandbox: authorize and attach a Slack token
│   └── validate-provider-profile.sh  # Outside sandbox: validate provider policy
└── docs/
    ├── data-lifecycle.md             # Retention, exclusions, export, reset, migration
    ├── encrypted-storage.md          # Required storage-encryption checks
    ├── set-up-graph.md               # Full Outlook mailbox authorization walkthrough
    ├── set-up-slack.md               # Full Slack authorization walkthrough
    └── slack_app_manifest.json       # User-scoped Slack app manifest
```
<!-- markdownlint-enable MD013 -->

#### Dependencies

<!-- markdownlint-disable MD013 -->
| Dependency source | Path | Purpose |
| --- | --- | --- |
| Python package manifest | None | All Python modules use the standard library |
| Recipe manifest | `profile/distribution.yaml` | Pins recipe version and Hermes 0.19.0+ |
| SQLite schema | `profile/scripts/schema.sql` | Defines application state schema v5 |
| Outlook provider policy | `providers/graph-user.yaml` | Declares the recipe's intended read-only delegated `graph.microsoft.com` boundary |
| Slack provider policy | `providers/slack-user.yaml` | Declares the recipe's intended read-only `slack.com` boundary |
<!-- markdownlint-enable MD013 -->

### API and Module Reference

#### Decision envelope

`apply_decisions.py` reads one JSON document from standard input. The supported
decisions are `CREATE`, `KEEP_OPEN`, `MARK_DONE`, and `SKIP`. A create or keep
decision requires a rank, title, and intent-gate verdict.

```json
{
  "version": 1,
  "pass": "intake",
  "decisions": [
    {
      "source_id": "msg-priorities-match",
      "decision": "CREATE",
      "rank": 1,
      "intent_gated": true,
      "title": "Review the migration plan",
      "context": "Matches a current priority",
      "urgency_reason": "Requested before the planning review",
      "kind": "response",
      "est_effort": "minutes"
    },
    {
      "source_id": "msg-automated-noise",
      "decision": "SKIP"
    }
  ],
  "cursor": {
    "source": "email",
    "scope": "inbox",
    "value": "synthetic-cursor"
  }
}
```

Run the writer against a saved envelope from the recipe root.

```bash
python3 profile/scripts/apply_decisions.py < /path/to/envelope.json
```

Valid optional values are:

```yaml
kind:
  - response
  - action
  - null
est_effort:
  - minutes
  - hours
  - day
  - multi_day
  - null
```

#### Module contracts

<!-- markdownlint-disable MD013 -->
| Module | Reads | Writes / returns |
| --- | --- | --- |
| `normalize.py` | Graph- or Slack-shaped source objects | Source-neutral item dictionaries; recipient lists become one addressing value |
| `_db.py` | `HERMES_HOME`, `schema.sql` | Validated profile path, SQLite connection, transactions, automatic migration |
| `ingest_graph.py` | Delegated Graph token and inbox delta | New Outlook message rows, resumable cursor state, and source-removal tombstones |
| `ingest_slack.py` | Rotating Slack token and selected conversations | New Slack rows and per-conversation watermarks |
| `select_intake.py` | Collectors and pending rows | JSON batch or a final wake-gate line |
| `select_review.py` | Open obligations | Oldest-review-first JSON batch or a final wake-gate line |
| `select_memory.py` | Message evidence, open obligations, and user corrections | Bounded memory-writing evidence or a final wake-gate line |
| `apply_decisions.py` | Versioned JSON envelope on standard input | Items, obligations, cursor, and append-only events in one transaction |
| `correct.py` | One user command | Pin/ignore state plus `actor='user'` audit events |
| `identity.py` | Stored pairwise identity answers | Resolved identity groups, candidates, and conflicts |
| `link_identity.py` | User confirmation or rejection | Durable relationship between two provider identities |
| `ranking.py` | Open obligations and gate verdicts | Deterministic bounded tiers and positions |
| `preferences.py` | User correction events | Bounded preference policy after the fixed threshold is met |
| `memory_check.py` | Memory Markdown pages | Diagnostics and exit status; no model call |
| `retention.py` | Store and `RETENTION_DAYS` | Clears expired bodies; keeps metadata, obligations, and history |
| `export_store.py` | Store, memory, and policy | Complete Markdown and JSON export directory |
| `reset.py` | Profile workspace | Removes store, memory, policy, and collection state after confirmation |
| `migrate.py` | Existing store | Forward-only schema migration or compatibility check |
<!-- markdownlint-enable MD013 -->

#### Store and migration commands

```bash
python3 profile/scripts/retention.py --dry-run
python3 profile/scripts/retention.py
python3 profile/scripts/export_store.py --to /path/to/export
python3 profile/scripts/migrate.py --check
python3 profile/scripts/migrate.py
python3 profile/scripts/reset.py --dry-run
python3 profile/scripts/reset.py --yes
```

`reset.py --yes` is destructive. Stop or pause the schedule first, export if
needed, detach and revoke external credentials separately, and verify the
profile named by `HERMES_HOME` before running it.

### Verification

This is an integration-level reference implementation. Its evidence includes
an offline end-to-end walkthrough, deterministic tests, scheduled Linux
validation, plus live Slack and Outlook collector and credential-rotation
validation.

#### Offline acceptance walkthrough

```bash
export RECIPE_VERIFY_HOME="$(mktemp -d)"
export HERMES_HOME="$RECIPE_VERIFY_HOME"
python3 profile/scripts/walkthrough.py --fixtures fixtures
```

#### Full test suite

Run from the recipe root. Each test file is executed directly because some
tests verify direct-execution behavior.

```bash
cd profile/scripts
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost"
export no_proxy="${no_proxy:+$no_proxy,}127.0.0.1,localhost"
fail=0
for t in tests/*.py; do python3 "$t" || fail=1; done
echo "failed=$fail"
cd ../..
test "$fail" -eq 0
```

Expected result: every file ends with `OK`, the fourteen files report 610 tests
in total, and the final line is `failed=0`. Do not shorten the loop with an
early break; running every module is part of the documented check.

The suite covers schema migration, memory invariants, concurrency and crash
recovery, deterministic ranking, preference thresholds, normalization,
transactional decisions, correction state transitions, the walkthrough,
intake, review, and memory-writing selector wake gates, scheduler contracts,
lifecycle controls, and Slack and Outlook collection/rotation behavior.

### Recipe Metadata

```yaml
name: memory-driven-chief-of-staff
version: "0.1.0"
kind: nvidia-recipe
status: reference-example
target_runtime: NemoHermes
tech_stack:
  - "Python 3.10+"
  - SQLite
  - Bash
  - "Hermes >=0.19.0"
  - NemoClaw
  - OpenShell
entry_point: profile/scripts/walkthrough.py
install_entry_point: scripts/install.sh
configuration_manifest: profile/distribution.yaml
state_root: "$HERMES_HOME/workspace"
source_connectors:
  available:
    - Slack
    - "Microsoft Outlook (via Microsoft Graph)"
evidence_level: integration
license: Apache-2.0
```

## Catalog Metadata

| Catalog field | Value |
| --- | --- |
| Description | Builds a revisable local memory from email and Slack, then ranks obligations against the user's priorities while preserving pins and ignores without changing source systems. |
| Industry | ✨ Other |
| Requirements | Python 3.10+ · scheduled use: a Linux NemoHermes sandbox, Hermes 0.19+, and an inference provider API key · provider setup helpers: Linux/WSL · Slack and Microsoft Graph collectors optional |
