<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Agentic AI Learning Path: Build-an-Agent Workshop on NemoClaw

[NVIDIA's **Build an Agent** workshop](https://github.com/brevdev/workshop-build-an-agent)
is a hands-on developer course: seven JupyterLab modules that take you from
your first tool-calling agent (Build an Agent) through Agentic RAG,
Evaluation, Customization, Deep Agents, Agent Safety, and Harnesses &
Skills. It is best known as a popular [Brev Launchable](https://brev.nvidia.com)
— a one-click cloud GPU environment learners spin up on a fresh instance.

This example adapts that workshop to NemoClaw. Instead of a fresh cloud
machine, the workshop runs **inside the locked-down OpenShell sandbox of an
existing NemoClaw deployment**, and the sandboxed resident agent does the
heavy lifting: it clones the workshop content, builds the environment,
launches JupyterLab from inside its own sandbox, and then serves as an AI
tutor for the modules — explaining concepts, giving graduated hints, and
checking progress without completing the learner's exercises. The workshop
also doubles as a live demonstration of the platform: every install, clone,
and API call it makes runs under the sandbox's kernel-level enforcement and
L7 egress policy.

Two things this example is **not**: it is not a getting-started recipe for
NemoClaw itself (it is a layer you add once a NemoClaw deployment is already
running — see the prerequisite below), and it does not contain the workshop
content. It ships **skills only**; the notebooks, lessons, and code stay in
the upstream [workshop repo](https://github.com/brevdev/workshop-build-an-agent)
and are cloned into the sandbox at setup time through a repo-scoped egress
grant.

## How the pieces fit together

Three separately-owned pieces combine, in this order:

| | Piece | What it provides | What you do |
| --- | --- | --- | --- |
| 1 | [Developer Community Chief of Staff](../../recipes/nvidia/developer-community-chief-of-staff/README.md) recipe | **The prerequisite.** Stands up the foundation this example needs: an OpenShell gateway on a host, running a sandboxed NemoClaw (Hermes) resident agent under Landlock/seccomp enforcement. | Deploy it first — follow its README through `scripts/bring-up.sh`. |
| 2 | This example | The skills that turn that resident agent into the workshop installer and tutor, plus the host-side operator procedure (egress policy, staging, port-forward). | Run the Quickstart below. |
| 3 | [Build an Agent workshop content](https://github.com/brevdev/workshop-build-an-agent) | The course itself — notebooks, lessons, code. Origin of the Brev Launchable. | Nothing — the resident agent clones it during setup. |

If you are brand new to this repo: start with the chief-of-staff recipe's
README, confirm its sandboxed agent is up (`docker ps` shows an
`openshell-hermes-direct-…` container), then come back here.

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

The prerequisite
[Developer Community Chief of Staff](../../recipes/nvidia/developer-community-chief-of-staff/README.md)
recipe provides the deployment: an OpenShell gateway on a single host,
running a Hermes agent inside a `hermes-direct` sandbox with L7 egress
allowlists, credential placeholders, and Landlock/seccomp enforcement. This
example layers the learning path onto that deployment; it does not create
sandboxes itself.

Everything is driven from two sides:

1. **Host side (operator).** Only the host can widen egress policy, stage
   files into the sandbox, and open an inbound path. The operator skill
   stages this example's skills into the agent's skill library
   (`/sandbox/.hermes-data/skills/`) and kicks the agent.
2. **Sandbox side (agent).** The resident agent runs `setup-workshop-nemoclaw`
   under full sandbox enforcement: scoped `git clone`, `uv` installs through
   the proxy CA, an `LD_PRELOAD` shim so Jupyter kernels survive the seccomp
   netlink block, and a single JupyterLab server on `127.0.0.1:8888`.

Module coverage is honest about the sandbox: **modules 1–3, 5, and 7 run
end-to-end on CPU; modules 4 and 6 need a GPU/Docker the sandbox deliberately
lacks and are read-through here** (the setup marks the affected lessons with
sandbox notes).

## Prerequisites

- A deployed
  [Developer Community Chief of Staff](../../recipes/nvidia/developer-community-chief-of-staff/README.md)
  recipe — the prerequisite example described above. Its
  `scripts/bring-up.sh` must have completed, and `docker ps` must show the
  `openshell-hermes-direct-…` container: that container hosts the sandboxed
  agent this example stages its skills into.
- The workshop policy blocks applied to the sandbox (`github_git_clone`,
  `pypi_install`, `nvidia_retrieval`, `tavily_search`, `langsmith_api`,
  `npm_install`, `mcp_tavily`, `tiktoken_encodings`, `openclaw_inference`,
  the NIM `/v1/ranking` rules, and the `/dev/pts` + `/sys/fs/cgroup`
  filesystem grants). The recipe's stock policy does not include them — the
  operator skill carries the exact YAML and apply workflow in its
  [`references/policy-blocks.md`](skills/setup-workshop-nemoclaw-operator/references/policy-blocks.md).
  Once applied, the sandbox's **live** policy is the sole carrier of these
  grants — do not edit the recipe's `policy.yaml` template, and treat policy
  captures as scratch artifacts (regenerate on demand, do not track them).
  A recreate through the recipe's own scripts re-renders the stock template
  and silently reverts every workshop grant; recreate from the live policy
  instead (the operator skill's Phase 1b) or re-run the apply afterwards
  (idempotent).
- An **NVIDIA API key** (`nvapi-…` from [build.nvidia.com](https://build.nvidia.com)).
  The learner sets it in the workshop's **Secrets Manager** tile after launch
  — deliberately not staged up front. Optional: `TAVILY_API_KEY` (modules
  1/2/5 web search) and `LANGSMITH_API_KEY` (module-3 tracing).

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
agentic-ai-learning-path workshop located under the examples/workshops
folder to run inside of this sandbox and be able to access the workshop
environment at a URL. Use the setup-workshop-nemoclaw-operator skill inside
of the repo to accomplish this, and let me know what I need to do to access
the sandboxed workshop environment once you are done working.
```

Stay reachable while it runs: the permission layer will (correctly) stop the
agent on the actions that need a human — the egress-widening
`openshell policy set` and, on a fresh sandbox, the delete/recreate that
boots the `/dev/pts` + `/sys/fs/cgroup` filesystem grants (the skill's
Phase 1b). Approve them when the prompts name exactly what is being opened.
The agent finishes by handing you the laptop tunnel command and the
JupyterLab token URL.

To follow the same procedure by hand instead, in outline:

```bash
SANDBOX=hermes-direct
C=$(docker ps --format '{{.Names}}' | grep "openshell-$SANDBOX")
EXAMPLE=examples/workshops/agentic-ai-learning-path

# 1. Apply the workshop policy blocks (exact YAML + apply semantics in the
#    operator skill's references/policy-blocks.md). `openshell policy set`
#    REPLACES the whole document — build live policy + additions. The live
#    policy is thereafter the source of truth: do NOT edit the recipe's
#    policy.yaml template, and treat captures as regenerable scratch files.
#    (`--full` prepends a metadata header that must be stripped.)
openshell policy get "$SANDBOX" --full | sed '1,/^---$/d' > /tmp/live.yaml
#   ... append the workshop blocks, then (typically run by the human):
openshell policy set "$SANDBOX" --policy /tmp/apply.yaml --wait

# 2. Verify the policy is live (probes under real enforcement)
bash "$EXAMPLE"/skills/setup-workshop-nemoclaw-operator/scripts/verify-sandbox-ready.sh

# 3. Stage this example's skills into the agent's skill library
for d in "$EXAMPLE"/skills/*/; do
  name=$(basename "$d")
  [ "$name" = "setup-workshop-nemoclaw-operator" ] && continue
  docker exec "$C" rm -rf "/sandbox/.hermes-data/skills/$name"
  docker cp "$d" "$C:/sandbox/.hermes-data/skills/$name"
done
docker exec "$C" chown -R sandbox:sandbox /sandbox/.hermes-data/skills

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

## Verification

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
  **recreate** (or the recipe's `tear-down.sh`) removes it. Note a recreate
  also wipes the staged skills, the clone, the venv, and `secrets.env`, and
  re-renders policy from the `policy.yaml` template — to run the workshop
  again, repeat the quickstart (all steps are idempotent).
- Never `docker restart` the sandbox container (stale-bootstrap-JWT crash
  loop; see the operator skill's lifecycle notes).
