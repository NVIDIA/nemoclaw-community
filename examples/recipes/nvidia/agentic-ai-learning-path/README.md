<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Agentic AI Learning Path

| Catalog field | Value |
| --- | --- |
| Description | Runs the seven-module Build an Agent workshop in an OpenShell sandbox with an AI tutor. |
| Industry | 🎓 Academia/Education |
| Requirements | Linux · Docker · OpenShell · inference, NVIDIA, and Tavily API keys · Slack or Outlook · CPU-first; module 4 training is read-through |

[NVIDIA's **Build an Agent** workshop](https://github.com/brevdev/workshop-build-an-agent)
is a hands-on developer course: seven JupyterLab modules that take you from
your first tool-calling agent (Build an Agent) through Agentic RAG,
Evaluation, Customization, Deep Agents, Agent Safety, and Harnesses &
Skills. It is best known as a popular [Brev Launchable](https://brev.nvidia.com)
— a one-click cloud GPU environment learners spin up on a fresh instance.

This example adapts that workshop to NemoClaw. Instead of a fresh cloud
machine, the workshop runs **inside a locked-down OpenShell sandbox that
this example deploys itself** (`bash scripts/bring-up.sh`), and the
sandboxed resident agent does the heavy lifting: it clones the workshop
content, builds the environment, launches JupyterLab from inside its own
sandbox, and then serves as an AI tutor for the modules — explaining
concepts, giving graduated hints, and checking progress without completing
the learner's exercises. The workshop also doubles as a live demonstration
of the platform: every install, clone, and API call it makes runs under the
sandbox's kernel-level enforcement and L7 egress policy.

Two things this example is **not**: it is not a general getting-started
guide for NemoClaw itself (its deployment is one opinionated, enterprise-
flavored stack), and it does not contain the workshop content. It ships
**the deployment plus the workshop skills**; the notebooks, lessons, and
code stay in the upstream
[workshop repo](https://github.com/brevdev/workshop-build-an-agent)
and are cloned into the sandbox at setup time through a repo-scoped egress
grant.

## How the pieces fit together

Three pieces combine, in this order:

| | Piece | What it provides | What you do |
| --- | --- | --- | --- |
| 1 | The included deployment (`scripts/`, `agents/`, `providers/`, `extras/`, `policy.yaml`) | **The foundation.** An OpenShell gateway on this host, running a sandboxed NemoClaw (Hermes) resident agent under Landlock/seccomp enforcement, with enterprise messaging channels (Slack/Outlook). | Deploy it first — Prerequisites below, then `bash scripts/bring-up.sh`. |
| 2 | This example's skills | The skills that turn that resident agent into the workshop installer and tutor, plus the host-side operator procedure (egress policy, staging, port-forward). | Run the Quickstart below. |
| 3 | [Build an Agent workshop content](https://github.com/brevdev/workshop-build-an-agent) | The course itself — notebooks, lessons, code. Origin of the Brev Launchable. | Nothing — the resident agent clones it during setup. |

If you are brand new to this repo: fill in `.env` (Prerequisites below), run
`bash scripts/bring-up.sh`, confirm the sandboxed agent is up (`docker ps`
shows an `openshell-hermes-direct-…` container), then run the Quickstart.

## What is in here

| Skill | Runs | Purpose |
| --- | --- | --- |
| [`setup-workshop-nemoclaw-operator`](skills/setup-workshop-nemoclaw-operator/SKILL.md) | Sandbox **host** (e.g. Claude Code) | The entry point. Egress policy, skill staging, optional key staging, kicking the in-sandbox agent, port-forwarding, lifecycle pitfalls. |
| [`setup-workshop-nemoclaw`](skills/setup-workshop-nemoclaw/SKILL.md) | **Inside** the sandbox (resident agent) | Clones the workshop repo, builds the venv, works around sandbox constraints (seccomp netlink shim, proxy CA, launcher fixes), launches JupyterLab, hands back the token URL. |
| [`workshop`](skills/workshop/SKILL.md) | Tutor (agent library + JupyterLab `claude`) | Workshop overview and router: module arc, prerequisites, cross-module connections, shared tutoring policy, glossary, progress checks. |
| [`module-1`](skills/module-1/SKILL.md) … [`module-7`](skills/module-7/SKILL.md) | Tutor | Per-module learning assistants (concepts, hints, troubleshooting) for Build an Agent, Agentic RAG, Evaluation, Customization, Deep Agents, Agent Safety, and Harnesses & Skills. |

In this repository the `setup-workshop-nemoclaw` pair **is** the workshop
setup pathway. The workshop repo's own `setup-workshop` skill (a bare-metal
AI-Workbench/GPU installer) is deliberately not part of this example — it
cannot run inside a sandbox and is only relevant for non-NemoClaw installs.

## Deployment model

This example is self-contained. Its deployment — vendored verbatim from the
[Developer Community Chief of Staff](../developer-community-chief-of-staff/README.md)
recipe at `21bd3cb` (NemoClaw v0.0.105 base, Hermes 0.20.0, native NeMo
Relay integration; minus that example's autoheal machinery, its script
tests, and its product docs) — stands up an OpenShell gateway on a single
host, running a Hermes agent inside a `hermes-direct` sandbox with L7 egress
allowlists, credential placeholders, Landlock/seccomp enforcement, and
enterprise messaging channels. `bash scripts/bring-up.sh` creates the
sandbox; the vendored copies may diverge deliberately from the
chief-of-staff recipe over time.

The vendored agent image also carries the source recipe's in-image skills,
including the NVTeam role-lens personas: those are added by that Community
recipe and are not a built-in capability of the core NemoClaw product —
their labels describe task-scoped lenses, not real people or core-product
behavior.

Everything is driven from two sides:

1. **Host side (operator).** Only the host can widen egress policy, stage
   files into the sandbox, and open an inbound path. The operator skill
   stages this example's skills into the agent's skill library
   (`/sandbox/.hermes-data/skills/`) and kicks the agent.
2. **Sandbox side (agent).** The resident agent runs `setup-workshop-nemoclaw`
   under full sandbox enforcement: scoped `git clone`, `uv` installs through
   the proxy CA, an `LD_PRELOAD` shim so Jupyter kernels survive the seccomp
   netlink block, and a single JupyterLab server on `127.0.0.1:8888`.

Module coverage is honest about the sandbox: **modules 1–3 and 5–7 run
end-to-end on CPU (optional Docker-gated demos are read-through); module 4's
training notebooks need a GPU the sandbox deliberately lacks and are
read-through here — its SDG half runs, and module 7's optional cudf exercise
falls back to CPU** (the setup marks the affected lessons with sandbox
notes).

## Prerequisites

- A Linux host with Docker and the OpenShell CLI, v2 providers enabled:
  `openshell settings set --global --key providers_v2_enabled --value true --yes`.
- `cp .env.example .env`, then fill in an inference key (`COMPATIBLE_API_KEY`)
  and at least one messaging channel — Slack (`SLACK_BOT_TOKEN` +
  `SLACK_APP_TOKEN`; the lightest — [docs/set-up-slack.md](docs/set-up-slack.md))
  or Outlook ([docs/set-up-outlook-bridge.md](docs/set-up-outlook-bridge.md)).
  On corporate VPNs, route inference through `scripts/host-tls-proxy.py`
  ([docs/host-tls-proxy.md](docs/host-tls-proxy.md)).
- Run `bash scripts/bring-up.sh`. When it finishes, `docker ps` shows the
  `openshell-hermes-direct-…` container: that container hosts the sandboxed
  agent this example stages its skills into.
- An **NVIDIA API key** (`nvapi-…` from [build.nvidia.com](https://build.nvidia.com)) and a **Tavily API Key** (`tvly-…` from [www.tavily.com](https://app.tavily.com/home)).
  The learner sets it in the workshop's **Secrets Manager** tile after launch
  — deliberately not staged up front. Optional: `LANGSMITH_API_KEY` (module-3 tracing).

## Quickstart (operator, on the sandbox host)

The authoritative, failure-mode-aware procedure is the
[operator skill](skills/setup-workshop-nemoclaw-operator/SKILL.md). The
fastest path is to hand it to a host-side agent: start Claude Code from a
checkout of this repository on the sandbox host (the skill is discovered
from this directory) and give it this prompt, adjusting the sandbox name if
yours differs:

```text
I just started a new openshell sandbox (with a NemoClaw agent) called
hermes-direct on this host system. I would like to set up the
agentic-ai-learning-path workshop located under the examples/recipes/nvidia
folder to run inside of this sandbox and be able to access the workshop
environment at a URL. Use the setup-workshop-nemoclaw-operator skill inside
of the repo to accomplish this, and let me know what I need to do to access
the sandboxed workshop environment once you are done working.
```

Stay reachable while it runs: the permission layer will (correctly) stop the
agent on the actions that need a human — the egress-widening
`openshell policy set` and, on a fresh sandbox, the token-window-guarded
container restart that boots the `/dev/pts` + `/sys/fs/cgroup` filesystem
grants and the agent-stack relaunch that follows it (the skill's
Phase 1b). Approve them when the prompts name exactly what is being opened.
The agent finishes by handing you the laptop tunnel command and the
JupyterLab token URL.

To follow the same procedure by hand instead, in outline:

```bash
SANDBOX=hermes-direct
# Fail-closed container selection by OpenShell labels (not substring grep):
C=$(docker ps --filter 'label=openshell.ai/managed-by=openshell' \
              --filter "label=openshell.ai/sandbox-name=$SANDBOX" --format '{{.Names}}')
EXAMPLE=examples/recipes/nvidia/agentic-ai-learning-path

# 1. Apply the workshop policy blocks (block rationale in the operator
#    skill's references/policy-blocks.md). `openshell policy set` REPLACES
#    the whole document, so compose live policy + additions with the builder
#    (idempotent, self-verifying). The live policy is thereafter the source
#    of truth: do NOT edit the recipe's policy.yaml template, and treat
#    captures as regenerable scratch files. (`--full` prepends a metadata
#    header that must be stripped.)
openshell policy get "$SANDBOX" --full | sed '1,/^---$/d' > /tmp/live.yaml
python3 "$EXAMPLE"/skills/setup-workshop-nemoclaw-operator/scripts/build-workshop-policy.py \
  /tmp/live.yaml /tmp/apply.yaml
# then (typically run by the human):
openshell policy set "$SANDBOX" --policy /tmp/apply.yaml --wait

# 1b. Boot the filesystem grants: container restart while the sandbox is
#     still inside its bootstrap-token window, then relaunch the agent stack
#     (age guard + exact steps: operator skill, Phase 1b)

# 2. Verify the policy is live (probes under real enforcement)
bash "$EXAMPLE"/skills/setup-workshop-nemoclaw-operator/scripts/verify-sandbox-ready.sh

# 3. Stage this example's skills into the agent's skill library
#    (transactional per skill; excludes the host-side operator skill)
SANDBOX="$SANDBOX" bash "$EXAMPLE"/skills/setup-workshop-nemoclaw-operator/scripts/stage-skills.sh

# 4. Kick the in-sandbox agent (one-shot session; single-line prompt)
openshell sandbox exec -n "$SANDBOX" --no-tty -- sh -lc \
  'cd /sandbox && hermes --accept-hooks -z "Run the setup-workshop-nemoclaw skill from your skill library: clone the workshop repo, run preflight, setup, and start-jupyter, then save the token URL to /sandbox/workshop-url.txt and report back."'

# 5. Open the inbound path (foreground; leave running) and get the URL
openshell forward service "$SANDBOX" --target-port 8888 --local 8888
docker exec "$C" cat /sandbox/workshop-url.txt
```

Then from your laptop: `ssh -N -L 8888:localhost:8888 <user>@<host>` (or the
Teleport equivalent) and open the token URL. The launcher shows 11 tiles
(7 modules, Secrets Manager, and three client apps); set the NVIDIA key in
the **Secrets Manager** tile and start with Module 1 — or just ask the
resident agent, which now carries the `workshop` and `module-N` tutor skills.
If Slack is configured in your `.env`, you can also DM the deployment's
Slack bot — the same sandboxed agent — for tutoring help from anywhere.

## Verification

- Offline (no sandbox, no network; needs python3 with PyYAML):
  `bash tests/validate-example.sh` — syntax, policy-composition unit tests,
  and operator-script behavior tests. CI runs it on every change to this
  example (`.github/workflows/example-validation.yml`).
- `verify-sandbox-ready.sh` prints PASS for the policy probes (note: it
  probes with the binaries each policy block actually allows — an exec'd
  `curl` false-negatives against the NIM block).
- `docker exec "$C" ls /sandbox/.hermes-data/skills` lists the staged skills.
- After the kick: `docker exec "$C" cat /sandbox/workshop-url.txt` has the
  token URL, and `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8888/lab`
  on the host returns `302` while the forward is up.
- The operator skill's end-to-end checklist covers the rest (tiles, kernels,
  a module-2 rerank call, the Terminal tile's `/dev/pts` dependency).

## Teardown

- Stop the forward (`pkill -f "forward service $SANDBOX"` — it is not tracked
  by `openshell forward list`).
- The workshop lives entirely inside the sandbox filesystem; a sandbox
  **recreate** (or this example's `scripts/tear-down.sh`) removes it. Note a recreate
  also wipes the staged skills, the clone, the venv, and `secrets.env`, and
  re-renders policy from the `policy.yaml` template — to run the workshop
  again, repeat the quickstart (all steps are idempotent).
- `docker restart` of the sandbox container is safe only inside the
  bootstrap-token window (~1 h from create; the token is never refreshed):
  within it a restart recovers and boots dormant filesystem grants (verified
  on OpenShell v0.0.96); past it the sandbox bricks in an `ExpiredSignature`
  crash loop (verified on v0.0.53 and v0.0.96). See the operator skill's
  Phase 1b guard and lifecycle notes.

## Security and data-handling considerations

The vendored deployment carries its own boundary set (Slack/Outlook
channels, GitHub read-only REST, host-side mirror services), unchanged from
the chief-of-staff recipe it was copied from; the table below covers what
the **workshop** adds on top.

Phase 1 of the setup widens the sandbox deliberately; everything stays
deny-by-default until then, each grant is scoped to the listed hosts, paths,
and binaries, and no credential is pre-staged — a service receives nothing
until the learner opts in by setting their own key in the Secrets Manager
tile.

| Boundary | Allows | What leaves the sandbox | Cost / account |
| --- | --- | --- | --- |
| `github.com` clone route | Anonymous read-only smart-HTTP for the one workshop repo | The clone request itself | None |
| `pypi.org`, `files.pythonhosted.org` (GET) | `uv` install of the pinned workshop deps | Names of requested packages | None |
| `integrate.api.nvidia.com`, `ai.api.nvidia.com` | NIM chat/embedding/rerank calls from notebooks | Prompt and document content of the cells the learner runs | Learner's `nvapi-…` key ([build.nvidia.com](https://build.nvidia.com) credits) |
| `api.tavily.com`, `mcp.tavily.com` (optional) | Modules 1/2/5 web search | Search queries and extraction URLs | Learner's `TAVILY_API_KEY` |
| `api.smith.langchain.com` (optional) | Module-3 eval and tracing. ⚠️ The workshop's `variables.env` enables tracing globally: once `LANGSMITH_API_KEY` is set, traces of executed cells (prompts and outputs) are exported | LangChain run traces | Learner's `LANGSMITH_API_KEY` |
| `registry.npmjs.org` (GET-only) | Module-5 demo client `npm install` | Names of requested packages | None |
| `openaipublic.blob.core.windows.net` (GET `/encodings/**`) | tiktoken BPE data download (module 7) | Nothing content-derived | None |
| `/dev/pts` (rw), `/sys/fs/cgroup` (ro) filesystem grants | JupyterLab Terminal-tile PTYs; duckdb resource probe (modules 3/4) | Nothing (local) | — |
| `LD_PRELOAD` netlink shim | Stubs `getifaddrs`/`if_nameindex` so Jupyter kernels survive the seccomp netlink block; applied only to the Jupyter process tree | Nothing (local) | — |
| `hermes --accept-hooks` (setup kick) | Keeps the one-shot setup session non-interactive by pre-accepting hooks already configured in the deployed agent stack — the workshop clone does not yet exist at that point | Nothing (local) | — |

Landlock/seccomp and the L7 audit log remain in force throughout; every
allow/deny verdict is inspectable (operator skill, Phase 5).
