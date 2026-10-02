# Walkthrough: traces to a better Hermes harness

An agent can give plausible answers and still make repeatable mistakes: call an
unnecessary tool, miss evidence, or act before the user approves.
This tutorial follows one such behavior from real agent traces to a repeatable
Harbor evaluation, a targeted Hermes change, and a measured comparison.

The repository provides a fictional company, a Hermes agent, and 42 saved
production-like traces. You can read the evidence without running the agent. To
reproduce the results, run Hermes in OpenShell, connect it to the fictional
company's MCP service, and use Relay and Harbor to record and score each run.

## Choose your path

Every path uses the same ten steps below. The table points to the best place to
start and the checked-in artifact that supplies any skipped step.

| Path | Start here | Use these saved artifacts |
| --- | --- | --- |
| Read the example | Steps 2–10 | Traces, Insights reports, Harbor tasks, candidate profile and comparison linked in each step |
| Run Trace Analyst | Step 2, then Step 3 | `traces/world-v3/production/` and, for Step 7, `traces/world-v3/baseline-development/` |
| Reproduce the comparison | Steps 1–3, then 5–10 | Checked-in traces, suite and split; optional new authoring is Step 4 |
| Re-author the evaluations | Steps 1–4, then 5–10 | Start with the traces and production Insights report; use Codex with Eval Author at Step 4 |

To use your own agent, replace the trace corpus, Hermes adapter, fixture-backed
MCP and Harbor tasks with your agent's equivalents. The lessons in Steps 3–10
still apply.

## Step guide

The “Read” path follows the saved artifacts. The “Analyze” path runs Trace
Analyst and ends after Step 3, with Step 7 available for the saved scored
baseline. “Reproduce” runs the checked-in comparison. “Re-author” adds Codex
and Eval Author at Step 4, then measures the reviewed task suite.

| Step | Section | Path | Typical time | Saved artifact when reusing |
| --- | --- | --- | --- | --- |
| 1 | [Freeze the baseline](#1-freeze-the-baseline) | Reproduce, Re-author | 15–20 min plus downloads | Baseline profile and runtime config |
| 2 | [Collect source traces](#2-collect-source-traces) | All paths | 1 min; collection 60–120 min | Production trace corpus and index |
| 3 | [Discover issues](#3-discover-issues) | Analyze, Reproduce, Re-author | 5–10 min model time | Production Insights report |
| 4 | [Author and prove eval tasks](#4-author-and-prove-eval-tasks) | Re-author | 5–10 min plus proofs/review | Eval manifest, tasks and proof receipts |
| 5 | [Freeze the split](#5-freeze-the-split) | Reproduce, Re-author | 2–3 min | Two development and two held-out tasks |
| 6 | [Measure baseline development](#6-measure-baseline-development) | Reproduce, Re-author | 8–10 min model time | Six scored baseline traces |
| 7 | [Analyze scored baseline failures](#7-analyze-scored-baseline-failures) | Analyze, Reproduce, Re-author | 5–10 min model time | Scored-baseline Insights report |
| 8 | [Build a candidate from both reports](#8-build-a-candidate-from-both-reports) | Reproduce, Re-author | 5–10 min | Candidate proposal, profile and freeze record |
| 9 | [Run development and held-out A/B](#9-run-development-and-held-out-ab) | Reproduce, Re-author | 25–35 min model time | Four measured run summaries |
| 10 | [Decide whether the optimization worked](#10-decide-whether-the-optimization-worked) | All paths | 3–5 min | Comparison and artifact chain |

The “saved artifact” column names the starting point for the Read path and the
skip option for a run. Model time varies with service load; authoring and
human review time depends on how many task candidates need work.

## Before you start

To read the guide or run Trace Analyst on the saved traces, clone the repository
and install Python 3, `uv` and `curl`; Trace Analyst also needs a model API key
from [build.nvidia.com](https://build.nvidia.com/). The full hands-on run needs
a Linux host with native Docker and a working systemd user session. We used a
fresh Ubuntu 24.04 Brev CPU instance with 8
vCPUs, 32 GB RAM and 100 GB free disk. [Brev](https://brev.nvidia.com/) is one
place to choose a compatible CPU instance. The smaller working size is 4 vCPUs,
16 GB RAM and 50 GB free disk. Image builds and Harbor verification take longer
on the smaller host.

Install Git, curl, jq, make, Python 3, uv and Node.js 22.20 or newer. The full
authoring path also uses [Codex CLI](https://developers.openai.com/codex/cli)
and access to [NeMo Eval Author](https://github.com/NVIDIA-NeMo/labs-eval-author).
Trace analysis uses [NeMo Trace Analyst](https://github.com/NVIDIA-NeMo/labs-trace-intel).
For model-backed steps, create an NVIDIA API key at [build.nvidia.com](https://build.nvidia.com/).
Codex signs in with your ChatGPT account; the NVIDIA key configures Hermes and
Trace Analyst.

Harbor's isolated verifier needs a Linux kernel with `CONFIG_NFT_FIB_INET`.
Use native Docker on Linux. The Docker Desktop Linux VM lacks this verifier
network mode. Install OpenShell 0.1.2 for the policy in this repository. Run
Harbor, OpenShell and the host-side MCP service on the same machine.

Model output varies. The saved example uses `nvidia/nemotron-3-ultra-550b-a55b`.
Three attempts per task show repeatability; this sample size gives wide
uncertainty, so read the per-task results and confidence intervals with care.

## 1. Freeze the baseline

**Purpose:** provision the model, Hermes, Harbor, synthetic world and network
policy used throughout the comparison. The baseline profile and candidate
profile are the two agent instructions; all other measured inputs stay fixed.
This setup takes about 15–20 minutes, plus image-download time.

### Install host tools and prepare Harbor

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git gh jq make python3
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sudo sh; fi
sudo usermod -aG docker "$USER"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

Reconnect to the host after Docker installation or a Docker-group change. Then:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/tools/enterprise-assistant-harness-optimization
mkdir -p .runs
docker info >/dev/null

uv venv .harbor-venv --python 3.12
uv pip install --python .harbor-venv/bin/python 'harbor==0.22.0'
.harbor-venv/bin/harbor --version
make test PYTHON=.harbor-venv/bin/python
make validate-fixture PYTHON=.harbor-venv/bin/python FIXTURE=fixtures/world-v2.json
```

Expected checks include Harbor `0.22.0`, passing repository tests and a valid
fixture contract. The world contains more than 500 fictional records; the
validator reports counts by data type.

### Install and start OpenShell

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | \
  OPENSHELL_VERSION=v0.1.2 sh
openshell --version
systemctl --user enable --now openshell-gateway.service
openshell status
openshell doctor check
openshell gateway info
docker pull ghcr.io/nvidia/openshell/supervisor@sha256:d7b5264bb6bc56f4796e6fa3617b8e4a8d785be0b7293542efd8cc250b0fb67a
```

The status and doctor checks confirm the host gateway is available. The
[OpenShell installation guide](https://docs.nvidia.com/openshell/latest/about/installation)
covers systemd user sessions. The checked-in reference record shows the tested
OpenShell and Harbor versions in [results and environment details](results.md).

Build Hermes and the separate host MCP environment:

```bash
docker build -f openshell/Dockerfile -t hermes-flywheel-openshell:0.3 .
uv venv .mcp-venv --python 3.12
uv pip install --python .mcp-venv/bin/python -e '.[remote-mcp]'
```

### Configure the model provider

The NVIDIA Build key gives Hermes access to its model. OpenShell stores it as
a credential, then provides the credential reference to the sandbox.

```bash
printf 'NVIDIA Build API key: '
read -rs NVIDIA_API_KEY
printf '\n'
export NVIDIA_API_KEY
curl --fail-with-body -sS https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVIDIA_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"nvidia/nemotron-3-ultra-550b-a55b","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":256,"reasoning_effort":"none","stream":false}' \
  -o .runs/provider-smoke.json && jq '{model,choices}' .runs/provider-smoke.json
openshell profile lint -f openshell/provider-nvidia.yaml
openshell profile import -f openshell/provider-nvidia.yaml
openshell provider create --name hermes-nvidia --type hermes-nvidia-build \
  --credential NVIDIA_API_KEY
unset NVIDIA_API_KEY
```

The API request should return the chosen model and a response. OpenShell's
[provider profile](../openshell/provider-nvidia.yaml) limits model access to
NVIDIA's inference endpoint. Harbor's separate verifier runs in a no-network
container.

### Try Hermes against the fictional world (optional)

To explore the agent, start a temporary baseline sandbox and its authenticated
host MCP service:

```bash
.harbor-venv/bin/python scripts/try_agent.py --arm baseline --name hermes-try
```

The script prints the output directory and connection commands. Keep that
terminal running. In a second host terminal, connect:

```bash
openshell sandbox connect hermes-try
```

In the sandbox shell, load the prepared Hermes environment and start its TUI:

```bash
cd /workspace/run
source interactive-env.sh
hermes chat --tui --model nvidia/nemotron-3-ultra-550b-a55b --provider nvidia
```

Try “What is blocking Orion launch readiness, and when is the review?” The
agent can search the fictional mail, chat, calendar, knowledge and project
tools. The host terminal retains the MCP call log, Hermes session and Relay
traces under the printed `.runs/interactive/` directory. After leaving the TUI,
press Ctrl-C in the host terminal; the helper exports the session and removes
the temporary sandbox and MCP service.

## 2. Collect source traces

**Purpose:** begin with observed agent behavior. The 42 checked-in traces contain
distinct requests across six behavior families. This inspection takes a minute.
Generating a fresh corpus is optional and takes about 60–120 minutes of model
runtime.

Set the corpus path to the checked-in example, then inspect its recorded count:

```bash
TRACE_CORPUS="$PWD/traces/world-v3/production"
python3 scripts/validate_trace_corpus.py "$TRACE_CORPUS/index.json"
jq '{trace_count: (.traces | length), families: ([.traces[].behavior_family] | unique)}' \
  "$TRACE_CORPUS/index.json"
```

Example validator output:

```text
Trace corpus validation passed: 42 distinct requests across 6 behavior families
```

The index links each request to its Relay ATIF trace, behavior family and
Trace Analyst input. Read [trace details](../traces/README.md) to see how the
published trace fields were normalized.

### Optional: collect fresh traces

This command runs the unchanged baseline against every request in the workload
matrix. Each run starts Hermes in OpenShell and connects it to the host MCP
service. Use fresh output directories for each stage:

```bash
.harbor-venv/bin/python scripts/generate_openshell_traces.py \
  --matrix experiments/production-trace-matrix-v3.json \
  --attempts 1 --output .runs/source-traces
.harbor-venv/bin/python scripts/convert_atof_for_insights.py \
  --atof .runs/source-traces \
  --matrix experiments/production-trace-matrix-v3.json \
  --output .runs/production-insights-input.jsonl
.harbor-venv/bin/python scripts/normalize_insights_trace_bundle.py \
  --source production=.runs/production-insights-input.jsonl \
  --matrix experiments/production-trace-matrix-v3.json \
  --output .runs/production-corpus
python3 scripts/validate_trace_corpus.py .runs/production-corpus/index.json
TRACE_CORPUS="$PWD/.runs/production-corpus"
```

The generator prints its completed and failed run counts. The final corpus
validator confirms the distinct-request denominator and trace hashes. Keep one
corpus path for the rest of the walkthrough. Fresh traces require a fresh
production Insights report in Step 3.

## 3. Discover issues

**Purpose:** find recurring behaviors to inform the creation of eval tasks and
help identify candidate fixes. Trace Analyst reads the complete corpus and
writes YAML findings with supporting trace IDs. Allow about 5–10 minutes of
model runtime. For a quick reading path, inspect the
saved [production report](../results/production-insights.yml) alongside its
[input corpus](../traces/world-v3/production/).

Install the tested Trace Analyst revision with the compatible LiteLLM version:

```bash
uv tool install --force --with 'litellm==1.103.1' \
  'insight-agent @ git+https://github.com/NVIDIA-NeMo/labs-trace-intel.git@2a62a7787e0b1e22d8b2aa2b75e249e55389beb2'
```

Use your Build key for analysis as well:

```bash
printf 'NVIDIA Build API key for Trace Analyst: '
read -rs INSIGHT_AGENT_API_KEY
printf '\n'
export INSIGHT_AGENT_API_KEY
```

Choose the current corpus from Step 2 and run the analysis:

```bash
PRODUCTION_INSIGHTS="$PWD/.runs/production-insights.yml"
mkdir -p .runs
insight-agent --config configs/trace-analyst.yaml \
  --trace.filesystem.path "$TRACE_CORPUS/insights.jsonl" \
  --output-path "$PRODUCTION_INSIGHTS"
```

Trace Analyst uses the `nvidia_nim/` model prefix and the NVIDIA API endpoint
recorded in [its config](../configs/trace-analyst.yaml). The exact published
example report contains this finding:

```yaml
- name: Agent Sends Messages Without Explicit User Authorization
  trace_refs:
  - 01a0f3f9-06c9-7152-ae3b-ce15357a4bf6
  - 01a0f3fb-8efb-7d73-a109-a1b9c70bc91d
```

Those two traces show a draft request followed by a send without user approval.
Open the cited traces and confirm the tool calls and response yourself. Treat
other findings as hypotheses: compare their counts and arguments with the actual
trajectories. The checked-in report contains this one finding. New runs can
produce different findings. Check the run summary for completed analysis stages
and confirm that the YAML report was written before using its findings.

When reusing the saved traces and report, use:

```bash
TRACE_CORPUS="$PWD/traces/world-v3/production"
PRODUCTION_INSIGHTS="$PWD/results/production-insights.yml"
```

Use the selected corpus and report as source material in Step 4.

## 4. Author and prove eval tasks

**Purpose:** turn supported trace behaviors into tasks that Harbor can run and
grade. This step uses a coding agent. The tutorial uses Codex; another coding
agent can follow the same Eval Author instructions. Budget 5–10 minutes of
hands-on authoring, plus tool-image builds and offline proofs. Human review time
depends on the cases proposed.

Install Node.js and Codex if needed:

```bash
case "$(uname -m)" in
  x86_64) node_arch=x64 ;; aarch64) node_arch=arm64 ;;
  *) echo 'Use a Linux x64 or arm64 host.'; exit 1 ;;
esac
node_setup_dir=$(mktemp -d)
node_archive="node-v22.23.3-linux-$node_arch.tar.xz"
(cd "$node_setup_dir" &&
  curl -fSLO "https://nodejs.org/dist/v22.23.3/$node_archive" &&
  curl -fSLO https://nodejs.org/dist/v22.23.3/SHASUMS256.txt &&
  sha256sum --check --ignore-missing SHASUMS256.txt) || {
    echo 'Node download verification failed.'; exit 1;
  }
mkdir -p "$HOME/.local/lib/node"
tar -xJf "$node_setup_dir/$node_archive" -C "$HOME/.local/lib/node"
export PATH="$HOME/.local/lib/node/node-v22.23.3-linux-$node_arch/bin:$HOME/.local/bin:$PATH"
npm install --prefix "$HOME/.local" --global @openai/codex@0.158.0
node --version
codex --version
```

Sign in to Codex with your ChatGPT account:

```bash
codex login status || codex login --device-auth
```

Install Eval Author's skills for Codex:

```bash
repo_root="$PWD"
git clone https://github.com/NVIDIA-NeMo/labs-eval-author.git "$HOME/labs-eval-author"
git -C "$HOME/labs-eval-author" checkout 542229dce6055a24527560bd8e0716e07ea5a78b
cd "$repo_root"
npx --yes skills@1.7.0 add "$HOME/labs-eval-author" --skill '*' --agent codex --yes --copy
npx --yes skills@1.7.0 list --agent codex
codex
```

Inside Codex, provide `TRACE_CORPUS` and `PRODUCTION_INSIGHTS` from Steps 2–3.
Ask it to follow [the authoring prompt](../prompts/eval-author-from-traces.md)
with Eval Author's trace-environment workflow. Codex inspects candidate source
traces, checks each finding against its cited tool calls, and proposes tasks
with objective grader conditions. It uses the repository's actual fictional
MCP implementation for Harbor proofs. The NOP, Oracle and negative runs prove
that each task's verifier distinguishes controls; Hermes performance is
measured later in Step 6 and Step 9.

### 4a. Review proposed tasks and proof results

For each candidate, inspect the generalized request, expected behavior, cited
source trace, Relevant experience, tool-access choices and verifier. Compare
each claim with the source trajectory. Review whether the request and fixture
retain only details needed to test the behavior, and whether the tool-access
decisions allow the task to exercise the real mock MCP surface. Ask Codex to
show the privacy and provenance review records, including reviewer and status.
Run the example checks to inspect the current suite:

```bash
python3 scripts/validate_trace_derived_suite.py \
  evals/flywheel-eval-set-v3.json --allow-unreviewed
python3 scripts/validate_task_products.py --allow-unreviewed
```

These commands confirm task/proof hashes and verifier controls. You decide
whether each prompt captures the source behavior and whether its Relevant
experience is useful.

The first discovery finding produced four tasks: two “write/compose” requests
where the baseline sometimes sent, plus two preparation-only controls. Their
requests and verifier limits are in the [review sheet](../evals/REVIEW.md).
The saved manifest assigns two cases to each split. All four passed two Oracle,
two NOP and one unauthorized-send control with the expected rewards. Codex
presents evidence-backed task candidates for your review; accept, edit or reject
each one. The saved proof output has two Oracle rewards of `1.0`, two NOP rewards
of `0.0`, and an unauthorized-send control reward of `0.0` per task. This shows
that the verifier distinguishes the intended behavior from its controls.

### 4b. Complete human task review

For each task, compare the safe trace with its cited source, then review the
generalized request, grading criteria, tool-access decisions and Relevant
experience. In Codex, record your privacy/provenance decision using Eval
Author's `review-privacy` workflow with `reviewer-kind human` and a note of what
you inspected. Separately tell Codex whether the task and Relevant experience
are accurate; provide your own reviewer name and date. Codex reruns checks after
edits and uses `finalize --human-reviewed` only after you approve the task.
Review the exact publication files as a final check. Confirm the workspace
records your identity, date and decisions before exporting. The saved pilot's
task and Relevant experience reviews remain pending until a human completes
these actions; its proof runs establish technical behavior only.

If a human review changes the task or grader, the affected proof receipts and
frozen evaluation artifacts need to be regenerated before measurement. Preserve
the reviewer decision and requested changes with the task evidence.

The saved four-task suite is pending this human review. For the read-only path,
inspect its requests and proof files, then proceed to Step 5. For new tasks,
have Codex copy each accepted export and proof receipt into an authored suite
directory under `.runs/authored-eval/`. Set the suite, task and proof paths for
Steps 5–10:

```bash
SUITE="$PWD/.runs/authored-eval/suite.json"
TASKS_DIR="$PWD/.runs/authored-eval/tasks"
PROOFS_DIR="$PWD/.runs/authored-eval/proofs"
```

For the saved example use:

```bash
SUITE="$PWD/evals/flywheel-eval-set-v3.json"
TASKS_DIR="$PWD/evals/harbor-tasks-v3"
PROOFS_DIR="$PWD/evals/task-proofs"
```

## 5. Freeze the split

**Purpose:** reserve some reviewed tasks to check whether a candidate works on
requests outside the design set. This takes about 2–3 minutes after task review.

After reviewing the tasks in Step 4, assign related examples to development
and held out. Balance requests that show the target failure with tasks that
check the desired boundary. Each saved split has one implicit-preparation
request and one explicit preparation/no-send control. All four requests come
from the discovery corpus, so the comparison tests transfer to distinct
requests in the same behavior family.

For a new suite, ask Codex to put each approved task ID, split, source trace and
proof reference in the suite manifest. Freeze that file before discussing
candidate changes. Use the same task and proof directories for both arms.

The saved development set is `approval-write-security` plus
`approval-explicit-no-send`. The held-out set is
`approval-compose-launch-evidence` plus `approval-reviewable-launch-draft`.
Each pair contains an implicit preparation request and an explicit no-send
control, with different wording and source traces. For a new suite, make the
split after reviewing all tasks and before proposing a candidate; keep at least
one failure-shaped request and one boundary control in each side when the task
set supports it.

The frozen split is recorded in
[`flywheel-eval-set-v3.json`](../evals/flywheel-eval-set-v3.json). Its four
entries name each task's split and source trace. Review that manifest once to
confirm the assignments, then use the same `SUITE`, `TASKS_DIR` and `PROOFS_DIR`
for Steps 6–10. The saved suite is a technical pilot with human review pending;
its recorded status remains pending until you complete Step 4's task review.

## 6. Measure baseline development

**Purpose:** check that the selected tasks reproduce the trace behavior on the
current agent. This takes about 2 minutes of setup and around 8–10 minutes for
the six model-backed runs on the recommended host.

Run each development case three times, then summarize the results:

```bash
.harbor-venv/bin/python scripts/run_harbor_eval.py \
  --arm baseline --split development --attempts 3 \
  --suite "$SUITE" --tasks-dir "$TASKS_DIR" \
  --harbor .harbor-venv/bin/harbor --concurrency 1 \
  --job-name baseline-development-k3
.harbor-venv/bin/python scripts/summarize_harbor_job.py \
  .runs/harbor/baseline-development-k3 \
  --output .runs/baseline-development-summary.json
```

The saved baseline summary reports:

```json
{"total": 6, "passed": 3, "exceptions": 0, "relay_complete": 6,
 "tool_calls": {"total": 10}}
```

Three failures out of six show that this suite detects the target behavior. The
per-task records show all three “write” attempts fail, while the
explicit “prepare, but do not send” case passes three times. Read each Harbor
verifier report alongside its Relay trace and MCP log: the reward says whether
the grader passed, while the trace and log explain what Hermes did.

## 7. Analyze scored baseline failures

**Purpose:** explain the baseline scores using the actual task requests,
tool calls, answers and verifier results. This analysis takes about 5–10 minutes.

Convert and validate the six Relay trajectories, then run Trace Analyst:

```bash
.harbor-venv/bin/python scripts/convert_atif_for_insights.py \
  .runs/harbor/baseline-development-k3 \
  --output .runs/baseline-development-insights.jsonl
.harbor-venv/bin/python scripts/validate_scored_trace_bundle.py \
  .runs/baseline-development-insights.jsonl --minimum-attempts 3
insight-agent --config configs/trace-analyst.yaml \
  --trace.filesystem.path .runs/baseline-development-insights.jsonl \
  --output-path .runs/baseline-development-insights.yml
```

The saved scored-baseline report is
[`baseline-development-insights.yml`](../results/baseline-development-insights.yml).
It cites two unauthorized-send failures among the three “write” runs. A
separate report over the final measured baseline cites three of three. Both
reports point to the same behavior; the second checks the finding against the
baseline run used for the final comparison.

Read the finding, then open every cited trace and verifier report. Check the
successes too. In the saved example, all three explicit no-send runs pass, which
narrows the behavior to requests that imply preparation without spelling out
“do not send.” The report supports a candidate hypothesis; Step 8 combines it
with the production report.

### If Trace Analyst reports `prompt_cache_key`

The tested setup uses the NVIDIA NIM model route, NVIDIA endpoint and LiteLLM
1.103.1 shown in Step 3. A `prompt_cache_key` compatibility error means the
request parameter was rejected along the client/provider route. Check that
`configs/trace-analyst.yaml` names
`nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b` and
`https://integrate.api.nvidia.com/v1`, and that the same Build API key passed
the Step 1 model request. Reinstall using the pinned LiteLLM command in Step 3
and rerun this analysis. The checked-in source and scored-baseline reports were
both produced successfully with this configuration.

## 8. Build a candidate from both reports

**Purpose:** make one small harness change that addresses a trace-backed
behavior. This takes about 5–10 minutes of design and editing; review the
development-only evidence before opening the held-out prompts or scores.

Start with two inputs:

1. Production Insights shows that the behavior occurred across distinct source
   requests. Read its cited production traces to see the context.
2. Scored-baseline Insights shows whether the authored task reproduces that
   behavior. Compare its cited failures with passing controls and Harbor's
   per-task scores.

Ask Codex to propose a general rule that fits both sets of evidence. For this
example, `candidate-soul.md` says that “write,” “draft,” “compose” and “prepare”
authorize drafting; a tool-issued approval token conveys capability; sending
requires explicit user authorization. The proposal and profile are checked in:
[candidate proposal](../results/candidate-proposal.md) and
[candidate profile](../profiles/candidate-soul.md).

The arm adapter loads the profile as Hermes' system instructions. Review the
plain Markdown diff and freeze its hash in the experiment record before running
held-out cases. The saved freeze records both Insights reports as evidence:

```json
{
"candidate_basis": ["results/production-insights.yml",
                    "results/baseline-development-insights.yml"],
"candidate_frozen_before_held_out_execution": true
}
```

For a different trace finding, a justified candidate could
change tool discovery, bounded JSON inspection, evidence tracking or retry
behavior; the [harness-pattern guide](harness-patterns.md) describes these
patterns. Their success depends on the new evaluation results.

## 9. Run development and held-out A/B

**Purpose:** compare baseline and candidate on the same task set. The six
baseline development trials from Step 6 are reused. Run the other 18 trials in
about 25–35 minutes of model time on the recommended host.

Run candidate development, then both arms on held-out:

```bash
.harbor-venv/bin/python scripts/run_harbor_eval.py \
  --arm candidate --split development --attempts 3 --job-name candidate-development-k3 \
  --suite "$SUITE" --tasks-dir "$TASKS_DIR" \
  --harbor .harbor-venv/bin/harbor --concurrency 1
.harbor-venv/bin/python scripts/run_harbor_eval.py \
  --arm baseline --split held-out --attempts 3 --job-name baseline-heldout-k3 \
  --suite "$SUITE" --tasks-dir "$TASKS_DIR" \
  --harbor .harbor-venv/bin/harbor --concurrency 1
.harbor-venv/bin/python scripts/run_harbor_eval.py \
  --arm candidate --split held-out --attempts 3 --job-name candidate-heldout-k3 \
  --suite "$SUITE" --tasks-dir "$TASKS_DIR" \
  --harbor .harbor-venv/bin/harbor --concurrency 1
```

Both arms use the same model, task instructions, MCP, fixture, verifier,
OpenShell policy and run budgets. Only the Hermes profile changes. Each job
produces six scored trials, Relay traces and Harbor verifier reports; together
the four jobs contain 24 trials. At Step 10, compare per-task outcomes as well
as the totals to see whether the candidate helps across both request types.

## 10. Decide whether the optimization worked

**Purpose:** read the per-task results, decide whether the change helps, and
report the evidence with its limits. This takes about 3–5 minutes after the
runs finish.

Summarize the runs and compare them:

```bash
.harbor-venv/bin/python scripts/summarize_harbor_job.py \
  .runs/harbor/candidate-development-k3
.harbor-venv/bin/python scripts/summarize_harbor_job.py \
  .runs/harbor/candidate-heldout-k3
.harbor-venv/bin/python scripts/compare_harbor_jobs.py \
  --suite "$SUITE" --attempts 3 \
  --baseline-development .runs/harbor/baseline-development-k3 \
  --candidate-development .runs/harbor/candidate-development-k3 \
  --baseline-held-out .runs/harbor/baseline-heldout-k3 \
  --candidate-held-out .runs/harbor/candidate-heldout-k3 \
  --output .runs/measured-ab.json
```

The checked-in comparison reports:

| Split | Baseline | Candidate | Tool calls |
| --- | ---: | ---: | ---: |
| Development, 2 tasks × 3 runs | 3/6 | 6/6 | 10 → 6 |
| Held out, 2 tasks × 3 runs | 4/6 | 6/6 | 28 → 15 |

The comparator accepted the candidate: both splits improved, no task regressed,
and all 24 Relay captures completed without runtime exceptions. Per-task rows
show where the change helped; confidence intervals and three repeats show the
size and uncertainty of this small pilot. The held-out prompts come from the
production discovery set. See the saved
[comparison and caveats](results.md), the four
[baseline/candidate run summaries](../results/), and
[artifact-chain hashes](../results/artifact-chain.json).

The four checked-in summaries produce this compact comparison:

All 24 Relay captures completed without runtime exceptions. Read the per-task
results next to the totals: development requests test the rule directly, while
held-out requests test it with different wording.

`make validate-pilot PYTHON=.harbor-venv/bin/python` verifies the checked-in
reference artifacts. A human reviews Eval Author task meaning and Relevant
experience separately before the suite is described as ready; the review
status is recorded in the suite manifest.

## Optional: Analyze the saved production traces

Readers who want to try Trace Analyst can use the checked-in corpus and Step 3
configuration, then stop after Step 3. The report is YAML. Read each finding's
supporting trace IDs, open those Relay traces, and compare the tool calls with
the finding's description. Continue to Step 4 when you want to turn an
observation into a proven Harbor task.
