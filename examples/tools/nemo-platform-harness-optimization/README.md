<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# NeMo Platform Harness Optimization

| Catalog field | Value |
| --- | --- |
| Description | Deploys a CAD agent against a live desktop application, scores its output geometrically, turns its traces into Insights, and lets the platform author an eval and propose a fix against it. |
| Industry | 🏭 Manufacturing |
| Requirements | macOS · Python 3.12 or 3.13 · FreeCAD 1.1 with the MCP addon · NeMo Platform 0.6.0 on localhost · Docker for the verifier · a registered model provider |
| NemoClaw | N/A |
| Harness | LangChain Deep Agents 0.7.13 |
| OpenShell | N/A |


A worked, end-to-end loop for an agent that drives a real application: deploy it,
measure it against ground truth, find what it actually gets wrong, and let the
platform write the evaluation that detects that failure next time — then propose
the fixes and score them against it.

## Screenshot

![A NeMo Studio trace view: one agent session expanded into a tree of nested spans on the left, the JSON payload for the selected span on the right, and span count, duration and total tokens in the header](assets/studio-trace.jpg)

## At A Glance


| Question                           | Answer                                                                                                                                                                                                              |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Category                           | Developer Tool                                                                                                                                                                                                      |
| Contributor or provenance          | NVIDIA                                                                                                                                                                                                              |
| Use this when                      | You are building a specialised agent that calls out to an external application through tools, and you want to run a harness engineering loop over it: gather the traces, turn them into Insights, author the evals those Insights imply, then propose changes and score them against those evals. |
| You will get                       | A NeMo Platform deployment of a Deep Agents harness whose every run streams to Intake, plus a worked evaluation framework for a CAD application: reconstruct a parametric model from a mesh, score it by IoU, file Insights from the traces, and run an optimizer that proposes changes across system prompt, skills and subagents and scores each one against the authored eval suite. |
| Runs on                            | macOS with a FreeCAD GUI session on the same host. The agent runs on the host; only the verifier runs in a container.                                                                                               |
| Requires                           | FreeCAD 1.1 with the freecad-mcp addon, NeMo Platform 0.6.0, Docker, and a registered model provider.                                                                                                               |
| Verified on                        | macOS 15, FreeCAD 1.1, NeMo Platform 0.6.0, deepagents 0.7.13, Python 3.13.                                                                                                                                         |
| Evidence level                     | local/static for the bundled tests; live end-to-end for the published measurement runs.                                                                                                                             |
| Support and maturity               | Best-effort community support. See [SUPPORT.md](../../../SUPPORT.md). The optimization agents move faster than the rest of the platform, so pin versions.                                                           |
| External access, data, and actions | Sends prompts and geometry descriptions to your configured inference endpoint. Mutates the FreeCAD document open on your screen. Runs a Docker container for the verifier. Writes telemetry to your local platform. |
| Start here                         | [Start Here](#start-here)                                                                                                                                                                                           |
| Confirm success                    | [Verification](#verification)                                                                                                                                                                                       |


## Why this exists

Baseline general-purpose harnesses — Claude Code, Codex, Hermes, Deep Agents —
are very strong at general orchestration: planning a workflow, driving tools,
and keeping a long task on track.

What they do not carry is your domain. Plenty of workflows are specialised, and
the specialisation is exactly the part that matters: a company's tagging
strategy, its naming conventions, its house rules for how a model should be
built. That knowledge lives in the organisation, not in the base harness, and it
bites hardest when the agent is calling out to an external application. Moving
from a general-purpose harness to a **specialised agent** is how you put it back
in.

Computer-aided design is a good example. Turning a scanned or exported mesh into
a **parametric CAD model** is not a text problem. The output has to be a real
feature tree of sketches, constraints and features that a designer can open and
edit. A model that looks right and is not editable is worthless, and a model with
the right volume can still be the wrong shape. A general-purpose harness pointed
at FreeCAD will produce something; it will not reliably produce that.

Closing that gap is **harness engineering**: adding skills, subagent workflows
and middleware such as hooks on top of a general harness until it behaves like a
specialist. Done well it buys two things at once — better correctness on the
task, and a better trajectory to get there. Neither can be improved without
being observed, which is why traces matter here as much as scores: this example
reads token counts, span counts and wall time off the same traces it reads the
failures from, and reports accuracy and cost side by side.

This example is a minimal, reproducible loop on
[NVIDIA NeMo Platform](https://docs.nvidia.com/nemo-platform/documentation/home):

1. Deploy a CAD agent that drives a real CAD application through MCP.
2. Define an **evaluation suite**: a **scorer** that puts a number on how correct
  a result is, and an **Ethos** that says what that number is for — the standard
  you are tuning towards, and what you will not trade away to move it.
3. Run a **baseline** and collect traces.
4. Use **trace intelligence** to find what the agent actually gets wrong.
5. Hand the finding to the **Eval Author**, and let the platform write the
  evaluation that detects it next time.
6. Let the **Experimentalist** propose a fix and score it against that evaluation.

## Prerequisites

- **Python 3.12 or 3.13.** NeMo Platform 0.6.0 declares
`Requires-Python: >=3.12,<3.14`, so 3.11 and older and 3.14 and newer will
not resolve. The install command below pins the interpreter so a newer
system default cannot change which one the tool lands on. The offline test
suite under `tests/` runs in a separate interpreter of your choosing and
needs only Python 3.12 or newer; `requirements.txt` floors NumPy at 1.26,
the first release with Python 3.12 wheels.
- **NeMo Platform 0.6.0**, installed pinned and with pre-releases allowed. The
`[all]` extra depends on a pre-release adapter, and an unpinned install
resolves backwards without saying so. See the install commands below.
- **FreeCAD 1.1+** with the [freecad-mcp](https://github.com/neka-nat/freecad-mcp)
addon installed in your FreeCAD user `Mod/` directory and `auto_start_rpc`
enabled. Launch the GUI normally: a FreeCAD started by executing the binary
directly never attaches to the window server, so its RPC port answers while no
queued work executes.
- **Docker**, for Steps 6 and 7. The evaluation suite's verifier runs in a
container. The agent itself does not; see Step 6.
- **An inference provider** registered on the platform. Model entities are
auto-discovered; list them with `nemo models list --all-pages` and substitute
your own entity name into `agent/agent.yaml`.
- **No ambient Relay config.** If `~/.config/nemo-relay/plugins.toml` exists,
every deployment fails at startup. Move it aside.

Install the platform:

```bash
uv tool install --python 3.13 --prerelease allow "nemo-platform[all]==0.6.0"
nemo --version     # confirm; a bad resolution looks like success
```

Then `nemo setup` to connect the platform, register an inference provider and
discover its models, and `nemo services run` to start it.

If you are working with a coding assistant, install the NeMo skills first. They
give it the platform's CLI conventions, which saves a lot of guessing at command
syntax:

```bash
nemo skills list
nemo skills install --agent claude     # also: codex, cursor, opencode
```

## Start Here

```bash
cd examples/tools/nemo-platform-harness-optimization
```

### Step 1: Define the agent

An agent on NeMo Platform is one declarative file, `agent/agent.yaml`:

```yaml
config_format: nemo-agents-spec-v1
name: cad-agent

instructions:
  system:
    content: |
      You are a CAD Agent (Computer Aided Design).

      A skills library is available at /skills/. Before starting a task, check
      whether a skill applies and read the applicable SKILL.md with read_file.

default_harness: deepagents

models:
  default:
    provider: nvidia
    model: REPLACE_WITH_YOUR_MODEL_NAME

mcp:
  servers:
    freecad:
      transport: stdio
      url: /opt/homebrew/bin/uvx
      args: [--from, freecad-mcp==0.1.24, freecad-mcp, --only-text-feedback]
      exposure: harness_native

environment:
  workspace: ./workspace
  artifacts: ./artifacts
```

Three things matter here.

**`default_harness`** selects the agent runtime.
[NeMo Fabric](https://docs.nvidia.com/nemo/fabric/about-nemo-fabric/overview) is
the adapter layer underneath, so the same spec can target a different harness by
changing this one field. The model, tools, MCP servers, skills and telemetry are
declared once and reused. If none of the shipped harnesses fit, the
[adapter contract](https://docs.nvidia.com/nemo/fabric/adapter-contract/overview)
is a descriptor plus a small runtime that builds the agent however you want. You
keep the platform (Intake telemetry, Insights, evaluation, the deployment
lifecycle) and replace only the agent construction.

**The MCP server** connects the agent to a live FreeCAD session. `transport: stdio`
means `url` is the executable and `args` are its arguments. The agent gets tools
like `execute_code`, `create_object` and `list_documents`, and everything it does
appears in the FreeCAD window.

**The telemetry you do not write** is what makes the rest of this possible.
Every run streams its execution trace to
[**NeMo Intake**](https://docs.nvidia.com/nemo-helix/documentation/agents/observe-agents/)
in ATIF format, and without traces there is nothing to analyse. Note that there
is no `telemetry:` block above. From 0.6.0 the platform reads
`telemetry.enabled` as a tri-state: unset means *wire it for me*, so a
deployment gets its Intake export filled in from the platform's own base URL and
workspace. Declaring it by hand only hardcodes `localhost:8080` and `default`
back into the config. Opt out with `telemetry: {enabled: false}`.

The auto-wiring happens in the deployment backend, so it does not apply to
`nemo agents invoke --agent-config <file>`, which builds an agent directly. That
is why the trial config in Step 6 still declares its own telemetry.

### Step 2: Deploy it

```bash
cd agent
nemo agents create --name cad-agent --agent-config "$PWD/agent.yaml"
nemo agents deploy --agent cad-agent --name cad-agent-deployment --mode subprocess
nemo agents invoke --agent-deployment cad-agent-deployment \
  --input "List the FreeCAD documents currently open."
cd ..
```

`--agent-config` must be an absolute path. Useful while iterating:

```bash
nemo agents list
nemo agents deployments list
nemo agents logs cad-agent-deployment -f
nemo agents chat --agent-deployment cad-agent-deployment   # interactive session
```

There is still no in-place update in 0.6.0: every agent resource is
create/list/get/delete, with nothing that patches a registered agent. To ship a config change, undeploy, delete, then create and deploy again.
The platform serves the config captured at registration time, and `deploy`
snapshots the environment and compute spec onto the deployment as well.

### Step 3: Start with the eval, not the agent

This is the step teams skip, and it is the one that makes everything after it
possible. **Before improving anything, define how you will know it improved.**

The task: turn a mesh into a parametric CAD model. The prompt states *what* is
required and never *how*. It ships at
`harness/dataset/train/parametric-mug/instruction.md`, with the mesh path left as
an `@MESH_PATH@` placeholder because it must be absolute for FreeCAD and an absolute
path cannot be committed. The harness wrapper resolves it at invoke time; the
command below substitutes it with `sed`.

```text
Turn the mesh at
`@MESH_PATH@`
into a fully parametric FreeCAD model that a CAD designer can open and edit.

Build it in a new FreeCAD document named `EvalMug`, constructed
from scratch. Other documents may be open from earlier work: do not open,
copy, merge or `saveCopy` any of them. Confirm the document does not
already exist before you create it.

Requirements:
- The result must be a single valid solid.
- It must be a native sketch-based PartDesign feature tree, with sketches
  driving features, not a stack of fused boolean primitives.
- A designer must be able to change a named dimension and have the model rebuild.
- It must match the original mesh closely.

Leave the document open when you finish, with exactly one object visible:
the finished model. The result is scored from the open document.

Do not take screenshots; verify numerically.
```

The source is a 1,824-vertex coffee mug mesh, 15.50 x 10.33 x 13.44 mm.

#### The scorer

Geometry is scored by **IoU** (intersection over union) against the source mesh, the same metric the [BenchCAD](https://benchcad.com/leaderboard.html) leaderboard
uses for CAD geometry. A reference solid is built from the mesh, and the score is
the intersection volume divided by the union volume.

```bash
$ python3 scorer/score.py EvalMug meshes/reference_mug.obj
0.3969
```

This is deliberately minimal: one number, computed by per-XY-column Z-interval
ray casting, exact along Z and discretised at 0.1 mm in XY. That is enough to
make the loop work.

Keep the scorer **outside** the agent's directory, in `scorer/` rather than
`agent/`. Everything inside the agent directory is staged into the deployment and
readable by the agent's own file tools, and an agent that can read its grading
criteria will eventually optimize against them.

#### The Ethos: what the number is for

A scorer measures shape. It cannot say why shape matters, what you would trade
for it, or what would count as cheating. That belongs in an
[**Ethos**](https://docs.nvidia.com/nemo-helix/v0.6.0/documentation/agents/optimize-agents/ethos/):
`agent/ETHOS.md`, a single Markdown file stating the agent's intent, uploaded
alongside the agent by `nemo agents create`.

It has a fixed schema, YAML front matter plus fifteen required sections, so
tooling can read it rather than guess. The sections that earn their keep here:

```markdown
## Success Criteria

- IoU >= 0.85 against the reference mesh.
- A native sketch-based PartDesign tree - sketches driving features - not a
  stack of fused boolean primitives.
- At least one named dimension whose change measurably moves the geometry.
  Verify by reading the volume back after setDatum + recompute; an unchanged
  volume means the dimension is not driving anything.

## Principles

- The feature tree is the deliverable. Shape accuracy is necessary but not
  sufficient; a designer must be able to edit the result.
- Trust the read-back, not the summary. Self-reported success is the least
  reliable signal available.

## Trade-offs

- Parametric quality over raw IoU. Given a choice between a boolean pile at
  0.95 and a sketch-driven tree at 0.88, the tree wins.

## Change Scope

- System prompt: yes
- Skills under `workspace/skills/`: yes
- Subagents: yes
- Model selection and sampling parameters: no
- Eval task, reference mesh or scorer: no
- Evaluation harness, including `harbor_wrapper.py`: no
```

Two of those lines do more work than they look. *The feature tree is the
deliverable* is the only place in the entire system that says a high score can
still be a bad result, and it is not hypothetical. One run here scored **0.903**
with 43 geometry elements under 43 `Block` constraints and zero named dimensions.
Shape-accurate, fully constrained, and uneditable.

And `Change Scope` is machine-readable, so an automated optimizer can be told
what it may touch. Every lever is `yes` or `no`, because nothing in an automated
loop can act on "ask someone". The `yes` lines are exactly the surfaces a
deployed agent carries; Step 6 explains why the rest are pinned rather than
merely discouraged.

Validate it before relying on it, because the parser is strict:

```bash
python3 -c "
from nemo_agents_plugin.ethos_parse import parse_ethos
e = parse_ethos(open('agent/ETHOS.md').read(), strict=True)
print(len(e.sections), e.warnings, e.change_scope_levers)"
```

### Step 4: Run the baseline and look at the traces

> **This runs a live agent and spends tokens.** Prompts and geometry descriptions
> go to your configured inference endpoint, and the agent mutates the FreeCAD
> document open on your screen.

The gateway caps any single response at 300 s and returns `502` while the agent
keeps working, so raise it first:

```bash
export NEMO_AGENTS_GATEWAY_READ_TIMEOUT=1800
```

Run the task three times, into a different document each time:

```bash
for i in 1 2 3; do
  sed -e "s|@MESH_PATH@|$PWD/meshes/reference_mug.obj|" \
      -e "s/\`EvalMug\`/\`EvalMug$i\`/" \
      harness/dataset/train/parametric-mug/instruction.md > /tmp/prompt-$i.md
  nemo agents invoke --agent-deployment cad-agent-deployment \
    --timeout 1800 --input "$(cat /tmp/prompt-$i.md)"
  python3 scorer/score.py "EvalMug$i" meshes/reference_mug.obj
done
```

Run it three times, not once. Agent runs are noisy, and the next step needs more
than one trace to find a pattern. Ours took about three minutes each and every
one reported success.

The scorer disagreed: **0.3338, 0.3969 and 0.4323**, all well under the 0.85 the
Ethos asks for. The agent was confidently wrong, and only the measurement caught
it.

### Step 5: Trace intelligence

Now the interesting part. Instead of reading traces by hand, ask the platform to
analyse them:

```bash
export NEMO_DEFAULT_MODEL="default/<your-model>"
export NEMO_FAST_MODEL="default/<your-fast-model>"

nemo agents analyst run --agent cad-agent --ethos agent/ETHOS.md
```

The analyst reads the traces from Intake directly: no separate harness, no
containers, no exported files. It surveys spans, clusters similar failures across
sessions, and emits **Insights**: persistent entities with a title, an actionable
description, and the trace references that evidence them.

`--ethos` is optional and takes a path. Supply it and the analyst judges the traces against your success criteria; leave it out and it infers a standard of its own, which is usually reasonable and not necessarily yours.

In 0.6.0 Insights always go to the platform first, so they appear in Studio
regardless of where you run the analyst from, and `--insights-file-output`
mirrors them to a local YAML file with their platform ids. On 0.5.0 a discovered
`optimizer.yaml` redirected them to a file *instead of* the platform; if you are
following older notes, that is what changed.

You can also opt the agent into periodic analysis and let a platform controller
do it on a schedule:

```bash
nemo insights analysis enable --agent cad-agent
nemo insights analysis status
```

From three traces, and nothing else on a platform with no other history, it
filed a handful of Insights. Two of them describe the agent's behaviour on the
task:

> **1. Mesh-fidelity verification does not establish close geometric agreement**
>
> *"…the agent claims the result matches the reference without a robust overlap
> check… EvalMug2 reports only distances from reference vertices to the
> candidate surface (mean 0.1674 mm, RMS 0.2334 mm, p95 0.4099 mm); this one-way
> metric can look good while missing extra candidate geometry, incorrect wall
> occupancy, or other false-positive volume."*

> **2. Chatty reconstruction loops repeatedly replay large context**
>
> *"…12-17 provider model calls and approximately 218k, 222k and 381k tokens…*
> *every additional measurement or correction replayed an increasingly large*
> *history."*

Two defects, two different kinds. The first is **correctness**: the agent has no
way to check its own work. The second is **process**: it gets there by trial and
error.

The rest of this walkthrough optimizes against the first.

![A NeMo Studio Insight titled "Mesh-fidelity verification does not establish close geometric agreement", showing the agent name, a description, and the three observed sessions with their durations, spans and token counts](assets/studio-insight.jpg)

Two things are worth noticing. The scorer independently agrees with the first
Insight, and the analyst cites *"the 0.85 success criterion"*, a number that
appears nowhere except your `ETHOS.md`.

List what it filed:

```bash
curl -s http://localhost:8080/apis/insights/v2/workspaces/default/insights
```

#### From Insight to fix

You could stop here and fix it by hand: give the Insight and its linked traces to
a coding agent, and have it write a skill telling the agent to measure before
declaring success. That works, and it is where most teams stop.

But it does not scale, and it leaves the same gap open. A hand-written fix is
still unmeasured: nothing in the harness detects this failure the *next* time it
appears, so the next regression needs the same manual round trip.

The rest of this closes that loop instead. The platform will write the evaluation
that detects the Insight, propose a fix against it, and score that fix on a
split it could not read while the candidates were being written.

### Step 6: Turn the Insight into an eval

Step 5 told us what is wrong. Nothing in the harness *measures* it: the scorer
measures shape, while the Insight is about whether the agent verifies its own
work. Run any optimizer now and it would chase IoU and learn nothing about the
defect it diagnosed.

NeMo Platform closes that gap with two more agents that work on the same Insight
entity:


| Agent               | Takes                    | Produces                      |
| ------------------- | ------------------------ | ----------------------------- |
| **Analyst**         | Traces in Intake         | Insights                      |
| **Eval Author**     | One Insight + its traces | An eval suite that detects it |
| **Experimentalist** | One Insight + that suite | A set of scored candidates    |


The Eval Author has no command of its own. It runs as the first phase of
`nemo agents experimentalist`. What it needs from you is an evaluation the
platform can execute, as [Harbor](https://www.harborframework.com/) tasks. That
is what `harness/` is:

```text
harness/
  optimizer.yaml          # the shared profile
  experiment-config.yaml  # bounds on the search
  agent_source/           # what the loop may change
    harbor_wrapper.py     # how Harbor runs your agent
  task-template/          # one task with placeholders, filled from traces
  dataset/train/          # tasks to optimize against
  dataset/validation/     # tasks to score against, hidden during generation
```

A Harbor task is four files: `task.toml`, `instruction.md`, an `environment/`
container definition, and `tests/test.sh`. The three `tests/` directories are
byte-identical copies on purpose, because Harbor requires each task directory to
be self-contained.

Your agent drives a desktop application, which looks like a blocker: you cannot
put a live FreeCAD session in a container. You do not have to. Harbor runs the
agent on the **host** and uses the container only for the verifier, so the task
environment needs Python, not FreeCAD:

```toml
[environment]
image = "python:3.12-slim"    # verifier only; the agent runs on your machine
```

Harbor reaches your agent through one class you write,
`harbor_wrapper:WrappedAgent`. Nothing ships a default. This one builds the
agent from `agent.yaml` in its own directory, waits for the trace to reach
Intake, converts it to the OTLP the verifier reads, and scores the result
against the reference mesh.

Building from the candidate's own config is what makes the loop meaningful.
Every candidate is a full copy of `agent_source/`, so a candidate can change the
system prompt, declare a subagent, or add a skill under `workspace/skills/`, and
the next trial measures that change rather than a proxy for it. Everything else
in the copy is pinned: a loop optimizes whatever surface you leave open, so
leave open only what you can ship. `scorer/verify_candidates.py` is what makes
that a boundary rather than a request. It lives outside `agent_source/`, is
never copied into a candidate, and compares each one against the pristine
originals:

```bash
python3 scorer/verify_candidates.py harness/experiment
```

It exits non-zero and names the offender if a candidate changed
`harbor_wrapper.py` or a pinned `agent.yaml` block. Run it before trusting a
run's ranking. The config needs `api_key_env` and `base_url` under `models.default`,
which the deepagents adapter requires when the agent is built from a file.

The profile, `harness/optimizer.yaml`, points at all of it:

```yaml
agent: cad-agent
ethos: ../agent/ETHOS.md
workspace: default

agent_source: ./agent_source
task_template: ./task-template
datasets:
  train: ./dataset/train
  validation: ./dataset/validation
```

`agent_source` is not optional: the Insight names a *registered* agent, which the
loop cannot edit, so it needs a directory or a git URL. Only a git source can
open a pull request for the winner.

Check the whole chain before spending anything:

```bash
cd harness
nemo agents experimentalist doctor --insight <insight-id>
```

```text
Agent-source  ✓ evaluator entrypoint harbor_wrapper:WrappedAgent   ✓ git is available
              ⚠ remote candidate persistence requires agent_source to be a git URL
Artifacts     ✓ task_template  ✓ train dataset  ✓ validation dataset
Models        ✓ default=<your-model>; fast=<your-fast-model>
Platform      ✓ http://localhost:8080 reachable   ✓ insight verified
Profile       ✓ profile for agent 'cad-agent'
Runtime       ✓ docker daemon running             ✓ harbor importable
```

The one warning is expected: `agent_source` is a local directory here, so the
loop can score candidates but cannot open a pull request for the winner. The
`Profile` line is the check worth reading — it resolves the agent name in
`optimizer.yaml` against the registered agent, so it fails if the two drift
apart.

One setting is not optional. Concurrency defaults to your CPU count, but a live
FreeCAD session is a single shared resource, so trials must be serial. The same
file bounds the run. The defaults, 15 rounds of 3 candidates, are far too large
when every trial is a full reconstruction. `harness/experiment-config.yaml`:

```yaml
max_rounds: 1
max_candidates: 2
max_survivors: 3
min_rounds_before_stopping: 1
outcome_evaluator_config:
  n_concurrent_trials: 1  # a live FreeCAD session is one shared resource
  n_attempts: 2           # measure every task twice; the default is 1
storage:
  publish_winner: false   # defaults to true
  archive_candidates: false
regression_metrics:
  - name: eval_iou
    direction: maximize
```

`n_attempts` matters as much as the bounds. Agent runs are noisy, and a single
trial per task cannot separate a real improvement from run-to-run variance.

**What the Eval Author wrote for this Insight.** Given the Insight and its traces,
it authored a metric named `geometry_fidelity_validation`: does the agent perform
a *symmetric* geometry comparison and act on the answer? That is the Insight's
own complaint turned into something executable. The authored metric becomes the
run's objective, and every candidate is scored on it. It is re-authored on each
run, so if you need runs you can compare directly, freeze the suite and pass
`--no-insight`.

**`regression_metrics` is what keeps the loop honest.** The authored objective
asks whether the agent measured its own output — the right question for the
Insight, and the wrong question for the product. A candidate can score 1.000 on
it while building a worse mug, and that is not hypothetical: an earlier run
produced a winner whose authored metric rose 67% while IoU fell from 0.6207 to
0.5442.

So the deliverable goes in as a floor rather than as a second objective.
Objectives are *ranked*; a candidate that worsens a regression metric against the
baseline is **dropped before ranking**, so a gain on the authored metric cannot
pay for a loss on geometry. Adding objectives widens the Pareto front and makes
selection noisier. Adding a guardrail only ever removes candidates.

`eval_iou` reaches the loop through the trace, because the verifier runs in a
container and can never open FreeCAD. Three small pieces carry it:

- `scorer/trial_metric.py` runs `scorer/score.py` on the host once the agent
  finishes and returns the IoU as an `eval.iou` span, which `harbor_wrapper.py`
  appends to the trace it hands the verifier.
- `tests/check_iou.py`, inside the container, reads that span back out and
  writes `{"eval_iou": ...}`; a missing span exits non-zero rather than scoring
  zero, because a broken scorer must not look like a broken reconstruction.
- `tests/merge_metrics.py` folds it into `reward.json` under the name
  `experiment-config.yaml` lists as a regression metric.

`trial_metric.py` and the `score.py` it calls both live in `scorer/`, outside
`agent_source/` — the directory the optimizer copies into every candidate and
invites a coding agent to edit. The wrapper loads them from the example root and
refuses to run if either ever resolves inside the candidate: a candidate that
can rewrite its own guardrail can pass it.

### Step 7: Let the platform fix it

```bash
nemo agents experimentalist run \
  --insight <insight-id> \
  --task-template ./task-template \
  --config experiment-config.yaml \
  -o ./experiment
cd ..
```

**`--config` is load-bearing.** `experiment-config.yaml` does not take effect by
existing; without that flag you get the defaults.

The run builds a baseline, analyses the Insight's root cause, proposes candidate
changes, has a coding agent implement each one, and scores them on the validation
split. That split is physically moved out of reach during candidate generation
and restored only for scoring, so the agent writing the candidates never reads
it. The isolation is in the mechanism, not in the content: this example's
validation task is the training task with a different document name, so a
validation score here measures repeatability on the same part, not
generalization to a new one. Point it at a different mesh with different
requirements if you want the second thing.

#### What one run produces

A round is a baseline plus `max_candidates` **rival** agents. Each candidate is
a full copy of `agent_source/` with the change proposed for it applied by a
coding agent; candidates are alternatives competing against each other, never a
combined patch. A single candidate is not limited to one surface — the
Experimentalist can propose a system prompt edit and a skill together:

```text
harness/experiment/eval-and-optimize/
  agents/agent-0/       the baseline, unchanged
  agents/agent-1/       candidate A, one change
  agents/agent-2/       candidate B, a different change
  results/agent-N-train/       scored trials per arm
  results/agent-N-validation/
  OPTIMIZATION.md       per-round reward tables, root-cause analysis, the winner
```

With `max_rounds: 1` and `max_candidates: 2`, one run gives you `agent-0`,
`agent-1` and `agent-2`, and `OPTIMIZATION.md` reports which won. A longer run
carries survivors into the next round and mutates those.

#### What it proposed

The Experimentalist proposes changes wherever it judges the Insight is best
fixed, not just in the system prompt. Across runs and candidates against this
same Insight it reached for three different parts of the agent, each one a
surface you can deploy:

```text
workspace/skills/geometry-fidelity-policy/SKILL.md   a policy document
agent.yaml  instructions.system.content              a completion gate
agent.yaml  harnesses...deepagents.subagents         an analysis subagent
```

All three are shipped verbatim in
[`results/candidates/`](results/candidates/) so you can read what a coding agent
writes when it is given traces, an Insight, and nothing else. None is preloaded
into `agent/`: the agent you deploy in Step 2 is the naive one, and a change
only arrives if the loop produces it. The runs behind them are written up in
[`results/optimization-run.md`](results/optimization-run.md).

These three were measured one surface at a time, so each number below is
attributable to the surface that produced it. They differ in kind, not just in
wording:

- the **skill** states a standard the agent should apply, and the agent decides
whether to read it
- the **system prompt** makes the same standard a completion gate that fires
after every geometry change, with no opt-out
- the **subagent** splits the work, forcing a measured analysis phase to return
a structured `ReferenceFittingSpecification` before construction starts

Each reinvented the same idea from the traces alone: declare a tolerance first,
then produce **bidirectional** evidence, because a one-way nearest-distance
result hides both missing source features and extra candidate geometry. That is
exactly the IoU the scorer computes in Step 3, which the optimizer cannot see.

#### The result

Promoted one at a time onto the baseline agent and measured separately, same
task, same FreeCAD session, one invocation each, scored by `scorer/score.py`
out of loop. Four agents, four independent measurements:


| Agent         | Surface changed                    | IoU        | Tokens  | Spans | Wall time |
| ------------- | ---------------------------------- | ---------- | ------- | ----- | --------- |
| baseline      | nothing                            | 0.4783     | 196,289 | 135   | 3m23s     |
| skill         | `workspace/skills/`                | 0.5370     | 236,650 | 151   | 5m04s     |
| system prompt | `instructions.system.content`      | **0.8974** | 235,581 | 154   | 4m14s     |
| subagent      | `harnesses...deepagents.subagents` | **0.9414** | 632,265 | 289   | 8m44s     |


Step 8 has the `cp` command for each surface.

Two things worth reading off that table.

**The two unconditional changes won.** The skill barely moved the baseline,
while the completion gate and the subagent roughly doubled it. The skill is
read only if the agent judges it relevant, and the failure being fixed is
precisely the agent judging that it does not need to check. A standard the
agent can decline to consult is a weak fix for a discipline problem.

**Accuracy is bought, and the two winners have very different price tags.** The
system prompt gains 0.42 IoU for 20% more tokens. The subagent gains 0.46 for
**3.2x** the tokens and 2.6x the wall time, because its analyst measures the
reference densely before any geometry is built. Per token spent it is much the
worse deal, which makes the system prompt the better default and the subagent
the choice when accuracy dominates cost.

### Step 8: Promote the fix, then measure what you shipped

A skill reaches the agent through `environment.workspace` on a *deployed* config,
which is exactly the surface the trials could not exercise. So promoting is not
the end of the validation; it is the start of it.

Promote whichever surface your winner used. A config change is one copy:

```bash
# a winner that changed agent.yaml (system prompt, subagents)
cp harness/experiment/eval-and-optimize/agents/agent-1/agent.yaml agent/agent.yaml

# a winner that added a skill
mkdir -p agent/workspace/skills
cp -r harness/experiment/eval-and-optimize/agents/agent-1/workspace/skills/* \
      agent/workspace/skills/

# or promote one of the shipped examples instead, to reproduce a published
# measurement without running the loop:
#   cp    results/candidates/system-prompt.yaml           agent/agent.yaml
#   cp    results/candidates/subagent.yaml                agent/agent.yaml
#   cp -r results/candidates/geometry-fidelity-policy     agent/workspace/skills/

nemo agents undeploy --agent cad-agent --yes
nemo agents delete cad-agent --yes
cd agent
nemo agents create --name cad-agent --agent-config "$PWD/agent.yaml"
nemo agents deploy --agent cad-agent --name cad-agent-deployment --mode subprocess
cd ..
```

Mark the Insight resolved only once the redeployed agent clears the bar on a
measurement you ran yourself:

```bash
curl -s -X PATCH \
  http://localhost:8080/apis/insights/v2/workspaces/default/insights/<id> \
  -H 'Content-Type: application/json' -d '{"status":"resolved"}'
```

## What this loop actually is

Nothing here is CAD-specific:

1. **Deploy** the agent with telemetry on.
2. **Define a scorer**: one number, measured, not asserted.
3. **Write an Ethos**: what the number is for, and what you will not trade for it.
4. **Run a baseline** several times and collect traces.
5. **Analyse the traces** to find what is actually wrong. *(Analyst)*
6. **Author an eval for what you found**, so the next iteration can see it. *(Eval Author)*
7. **Propose and score a fix** against that eval. *(Experimentalist)*
8. **Deploy the winner and re-measure**, because a trial builds the agent
  from a config file while production serves a registered deployment.

Steps 5 to 7 are the ones the platform automates, and step 6 is what makes it a
loop rather than a single repair. A scorer written up front can only measure the
failures you anticipated; the analyst finds the ones you did not. Until something
turns those into a measurement, every discovery is a one-off fix.

What does not automate is judgment, and the loop's own numbers will not supply
it. Across these runs:

- The scorer said **IoU 0.6207** while the agent reported success. Re-measured at
n=3, the same agent scored **0.334 to 0.432**; the first number was a lucky draw.
- The authored metric grades whether the agent *checks its work*, not whether
the mug is right, and that gap is exactly the room a candidate has to win the
metric while losing the product. In the recorded run the two happened to
coincide, which is luck, not design.
- The winner that did hold up cost **50% more tokens** than the naive agent. Read
in isolation, that is a regression.

Every one of those numbers is real and correctly measured. The conclusion each
invited on its own was wrong, because each answered a narrower question than the
one that mattered.

The lesson is not to distrust the loop. It is to **put the thing you actually
care about inside it**, and to measure it more than once. A proxy makes a fine
objective; it makes a terrible sole criterion. That is why `eval_iou` is a
guardrail in Step 6 rather than an afterthought here.

**An optimization loop improves whatever it can measure.** Automating the writing
of evals does not repeal that; it raises the stakes, because now the loop also
chooses what to measure. Which is why the scorer and the Ethos stay outside the
loop, as the things it answers to rather than things it can edit.

## Credentials and environment

Copy `.env.example` to `.env`, which is git-ignored. The example file names every
variable and carries no values.


| Variable                           | Default                 | What it does                                                                                    |
| ---------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------- |
| `NEMO_DEFAULT_MODEL`               | none                    | Workspace-qualified model for the analyst and optimizer. Required.                              |
| `NEMO_FAST_MODEL`                  | none                    | Workspace-qualified fast model. Required.                                                       |
| `NMP_BASE_URL`                     | `http://localhost:8080` | The local platform.                                                                             |
| `NMP_WORKSPACE`                    | `default`               | Workspace the agent is registered in.                                                           |
| `NEMO_AGENTS_GATEWAY_READ_TIMEOUT` | `300`                   | Raise it. The gateway caps any response at 300 s and returns 502 while the agent keeps working. |
| `FREECAD_RPC`                      | `http://127.0.0.1:9875` | The MCP addon's RPC endpoint.                                                                   |
| `FREECAD_BIN`                      | platform default        | FreeCAD binary used for headless scoring.                                                       |
| `CAD_SCORER`                       | `scorer/score.py`       | Absolute path to the scorer.                                                                    |
| `CAD_AGENT_TIMEOUT`                | `3600`                  | Seconds to wait for one invocation.                                                             |
| `CAD_AGENT_TRACE_WAIT`             | `3600`                  | Seconds to wait for the trace to reach Intake, which ingests asynchronously.                    |


No API key belongs in `agent.yaml`. Platform-routed models take their credential
from the gateway, and the runner injects it into the deployment process.

## Troubleshooting


| Symptom                                                                        | Cause                                                                                                    | Fix                                                                                                  |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `502 Bad Gateway`, but the deployment logged `200`                             | The gateway caps a response at 300 s while the agent keeps building.                                     | Raise `NEMO_AGENTS_GATEWAY_READ_TIMEOUT`. Recover tokens and latency from the trace, not the client. |
| Every deployment fails at startup                                              | An ambient `~/.config/nemo-relay/plugins.toml`.                                                          | Move it aside; select Relay configs with `HERMES_NEMO_RELAY_PLUGINS_TOML`.                           |
| `agents create` fails with `File exists: .../-ethos-upload-`                   | `--agent-config` was a relative path.                                                                    | Pass an absolute path.                                                                               |
| Config edits change nothing                                                    | There is no update command; the platform serves the config captured at registration.                     | Undeploy, delete, create and deploy again, as in Step 8.                                             |
| Scorer raises `ConnectionRefusedError`                                         | FreeCAD went down. The score is void, not zero.                                                          | Probe port 9875, relaunch the GUI, discard the run.                                                  |
| RPC port listens but nothing executes                                          | FreeCAD was started by running the binary directly, so it never attached to the window server.           | Quit it and launch the GUI normally.                                                                 |
| A metric scores 0.000 for a tool the agent called, or counts are inflated ~70x | Intake nests MCP calls inside LangGraph node spans, and every model turn replays the whole tool history. | Walk span payloads for `{"type": "tool_call"}` and de-duplicate on `call["id"]`, not on position.    |
| Optimizer used the defaults you thought you overrode                           | `experiment-config.yaml` takes effect only when passed with `--config`.                                  | Pass `--config experiment-config.yaml` explicitly.                                                   |
| The skill never appears in the system prompt                                   | `skills.paths` is not the loading mechanism here.                                                        | Keep the skill under `agent/workspace/skills/` and the pointer in the system prompt.                 |


## Known limitations

- **Only promotable surfaces are measurable, by design.** The harness and every
`agent.yaml` block outside `instructions` and `harnesses` are pinned, so a
candidate cannot win with a change you could not ship. The cost is that
genuinely useful work is out of reach: an MCP tool or a middleware hook needs
a human, or a custom Fabric adapter.
- **A trial runs the agent from a config file, production serves a deployment.**
`harbor_wrapper.py` builds each candidate from its own `agent.yaml`, so the
change surface is real, but a trial and a deployed run are not byte-identical
environments: a trial needs `api_key_env`, `base_url` and its own `telemetry:`
block in the config — all three of which a deployment gets filled in for it —
and it does not pass through the gateway. Step 8 re-measures on the deployment
for that reason.
- **The validation split is the training task under a different document name.**
The `.aad-heldout/` mechanism that hides it during candidate generation is
real, but the mesh and the requirements are identical, so a validation score
here reports repeatability rather than generalization.
- **Non-determinism here is branch divergence, not sampling noise**, and the
sampling surface is one knob: `temperature`. `models.default.settings` is never
read on the deepagents path, so a `seed` placed there is inert, and there is no
`seed` or `top_p` in the agent spec at all.
- **The sample sizes needed for statistical confidence do not fit the budget.**
Detecting a 0.10 difference at the observed spread needs roughly 35 runs per
arm. Use the optimizer to generate hypotheses and score winners out of loop.
- **macOS only, as verified.** Nothing here is inherently macOS-specific except
the FreeCAD paths, but no other platform was tested.
- **The Eval Author is non-deterministic.** The same Insight produced three
differently-named metrics across three runs. Re-authoring is a re-baselining
event; freeze the suite and use `--no-insight` for comparable runs.

## Verification

**Evidence level:** local/static

```bash
cd examples/tools/nemo-platform-harness-optimization
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests
```

**Expected result:**

```text
Ran 83 tests

OK
```

**This verifies:** the interval arithmetic and ray-casting core of the scorer
against hand-computed values, and the trace-conversion logic in the harness
wrapper, including the tool-call de-duplication that collapses 153 replayed
mentions back to 17 real calls.

**This does not verify:** the live FreeCAD export path, the deployed agent, the
analyst, the optimizer loop, or any behaviour on a platform other than macOS.
Those require the credentialed end-to-end path above.

## Running the agent outside NeMo Platform

The platform is where the agent is measured and evolved. It is not the only
place it can run. One script exports a config three ways:

```bash
python3 export_agent.py agent/agent.yaml --to ~/cad-export
```

It reads the same `agent.yaml` the platform deploys, so a promoted candidate
exports exactly as the baseline does, and it prints what each target could not
carry.

**1. The deployment, over HTTP.** A deployment already speaks
chat-completions, so any OpenAI client works:

```bash
curl -s -X POST "http://localhost:8080/apis/agents/v2/workspaces/default\
/deployments/cad-agent-deployment/-/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Who are you?"}]}'
```

The `/-/` segment is required. Multi-turn and `"stream": true` both work. A
`tools` parameter is accepted and **ignored**: this is an agent behind a model's
interface, not a model, so a coding harness cannot drive it. It can still be a
tool *inside* one, either by shelling out to that curl or by wrapping the
endpoint in a small MCP server.

**2. The Deep Agents SDK, directly.** `harness/standalone/run_agent.py` builds
the agent from `agent.yaml` with no platform involved, streaming every tool call
as it happens:

```bash
python3 harness/standalone/run_agent.py agent/agent.yaml
```

This is the highest-fidelity path: the model, MCP servers, skills workspace and
subagents come across unchanged, because NeMo's `subagents` passthrough is
literally the `create_deep_agent` argument.

**3. dcode**, the terminal agent on the same SDK, for an interactive session
with approval prompts:

```bash
~/cad-export/dcode/run.sh
```

Four things cost an afternoon to find, so they are worth stating:

| Symptom | Cause |
| --- | --- |
| `Unsupported provider='nemo'` | dcode accepts only known provider ids. The gateway is configured as `openai` with a custom `base_url`. |
| Hangs with no output | `api_key` in `config.toml` is not used for this shape; without `OPENAI_API_KEY` set it blocks on stdin. |
| Skills and subagents not found | dcode resolves the project root as the nearest ancestor with `.git`. The export runs `git init` for this reason. |
| `requires approval, but this headless runtime has no approval UI` | dcode gates MCP actions that are mutating or unannotated, and `freecad-mcp` annotates none of its tools. `--yolo` is ignored headless; use the interactive TUI. |

Subagents translate to `.deepagents/agents/<name>/AGENTS.md`, frontmatter plus
the prompt as the body, and dcode loads them: asked what it can delegate to, the
exported agent lists `reference-geometry-analyst`. The `response_format` does
not survive, because dcode reads only `name`, `description` and `model` from
that frontmatter. The system prompt lands in `.deepagents/AGENTS.md` and is
*appended* to dcode's own coding-agent identity rather than replacing it.

Leaving the platform costs the loop: no ATIF telemetry means no Intake traces,
no Analyst, no Insights, no optimizer. Use these for interactive work and
inspection, and the deployment for anything you intend to measure.

## Teardown

```bash
nemo agents undeploy --agent cad-agent --yes
nemo agents delete cad-agent --yes
```

Close any `Eval*` documents left open in FreeCAD. Optimizer output under
`harness/experiment/` is run output and is git-ignored; delete it freely.

Harbor leaves one verifier container per trial behind, and they accumulate fast
across runs. Clear them with:

```bash
docker container prune -f
```

## Provenance and license

Contributed by NVIDIA under the repository's
[Apache-2.0 license](../../../LICENSE). The `freecad-mcp` server is invoked
through `uvx` and is not vendored here.
