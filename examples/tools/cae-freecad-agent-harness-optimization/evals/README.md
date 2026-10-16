<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# cad-agent evals

Regression evals for the CAD agent, authored with
[NeMo Eval Author](https://github.com/NVIDIA-NeMo/eval-author)'s
trace-to-task workflow and run with [Harbor](https://www.harborframework.com/) 0.22.0.

## Cases

Both tasks share one instruction, one verifier and the same eight checks; only the
reference mesh and solution differ, so the suite tests that the agent's method works
for more than one shape.

| Case | Source |
| --- | --- |
| [part-1-reconstruction](part-1-reconstruction/) | Helix trace `01a11fc2-cbe4-7353-837a-f20c04071618`, cited by NeMo Compass Insights of the first baseline. |
| [part-2-reconstruction](part-2-reconstruction/) | A second first-party part added by the owner; no source trace. |

The agent gets the [instruction](part-1-reconstruction/instruction.md): rebuild
`/app/reference.obj` as an editable PartDesign model and save it to `/app/model.FCStd`.
The verifier grades that file in its own container with eight checks, all of which must
pass: `recomputes-after-reopen`, `single-valid-solid`, `native-feature-tree`,
`named-dimension-drives-geometry`, `independent-dimensions` (two named dimensions that
each change the part in a different way), `mesh-fidelity` (IoU ≥ 0.9),
`single-visible-object` and `compact-model` (at most 10× the reference solution's
faces). See the [grading explanation](part-1-reconstruction/README.md#verification-explanation).

## How a trial runs

```text
harbor run (host) ── per trial, in parallel ──┐
                                              ▼
  task container (evals/<task>/environment)          verifier container (evals/<task>/tests)
  headless FreeCAD 1.1.3 + Deep Agents + NeMo Relay   FreeCAD 1.1.3, no network
  /agent  ← agent/ (prompt, skills)                  grades /app/model.FCStd → reward
  /app    reference.obj → model.FCStd ─────────────▶
  network: NeMo Helix only (model gateway, Intake)
```

[`harness/cad_agent.py`](../harness/cad_agent.py) uploads the agent folder and starts
[`harness/run_agent.py`](../harness/run_agent.py), which runs the agent for at most
5 minutes and sends its trace to Intake. After a job,
[`publish.py scores`](../publish.py) attaches each run's reward, IoU, failed checks
and complexity counts to its trace for NeMo Compass.

## Setup

Run every command from the example root
(`examples/tools/cae-freecad-agent-harness-optimization`). You need:

- Harbor 0.22.0: `uv tool install harbor==0.22.0`.
- A Docker engine that can enforce per-container network rules. Docker Desktop on
  macOS cannot; [Colima](https://github.com/abiosoft/colima) can. Give it room for
  parallel trials (each is capped at 3 GiB):

  ```bash
  colima start --cpu 4 --memory 16
  export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
  ```

  Colima mounts only your home folder, so keep the example and jobs folders under it.
  The tasks reach the host as `host.docker.internal`, which Colima and Docker Desktop
  provide; on native Linux, map it to the host gateway.
- For agent runs: NeMo Helix running on the host, and where the containers reach it:

  ```bash
  export CAD_HELIX_URL=http://host.docker.internal:8080   # Helix's port on this host
  export NHX_BASE_URL=http://localhost:8080 NHX_WORKSPACE=default
  ```

## Rerun

`-y` accepts Harbor's prompt about the variables the tasks read from your shell.
Controls, which need no agent or Helix:

```bash
harbor run -y -p evals -a nop    --n-attempts 2 -n 4 --jobs-dir runs --job-name nop
harbor run -y -p evals -a oracle --n-attempts 2 -n 4 --jobs-dir runs --job-name oracle
# Negative controls: each task's solution broken one way (controls/make_negatives.py)
for f in controls/*/*.FCStd; do t=$(basename $(dirname $f)); n=$(basename $f .FCStd)
  PYTHONPATH=controls harbor run -y -p evals/$t -a replay_agent:ReplayModel \
    --ak model=$f --jobs-dir runs --job-name $t-$n
done
```

The agent (`-m` overrides the model in `agent/agent.yaml`; `--ak agent_dir=...` runs
another agent folder):

```bash
PYTHONPATH=harness harbor run -y -p evals -a cad_agent:CadAgent \
  -m nvidia-nvidia-nemotron-3-ultra --n-attempts 2 -n 4 --jobs-dir runs --job-name agent
python publish.py scores runs/agent
```

Each trial's `verifier/results` lists the checks and `verifier/reward.txt` is 1 only
when all pass; `agent/run.log` starts with the run's Intake trace ID. Browse jobs with
`harbor view --jobs runs`.

## Proof

Re-proved on 2026-10-16 with eight checks in the container setup above (separate
verifier, no network):

| Control | part-1 | part-2 | Fails |
| --- | --- | --- | --- |
| NOP (2 runs) | 0, 0 | 0, 0 | every check |
| Oracle (2 runs) | 1, 1 (IoU 0.9039, 7 faces) | 1, 1 (IoU 0.9985, 36 faces) | none |
| `visible`: solution with every feature and sketch visible | 0 | 0 | `single-visible-object` |
| `broken`: solution with its last feature's profile removed | 0 | 0 | `recomputes-after-reopen`, `named-dimension-drives-geometry`, `independent-dimensions` |
| `scripted`: solution's solid as a scripted base shape, plus one sketch-driven pocket | 0 | 0 | `native-feature-tree`, `named-dimension-drives-geometry`, `independent-dimensions` |
| `slices`: a real agent run, 32 stacked pads (IoU 0.91, 1,658 faces) | 0 | n/a | `independent-dimensions`, `compact-model` |
| `one-dimension`: a real run of the final agent, 4 ruled lofts driven by one `Params.Length` (IoU 0.970 / 0.943) | 0 | 0 | `independent-dimensions` |

Isolation, probed with Harbor 0.22.0 on Colima: the agent reaches only
`host.docker.internal` (public hosts are blocked; the allowlist is per host, so every
port on the host is reachable), and the verifier reaches nothing. The agent's
container holds only the mesh; the solution and tests stay with the verifier.
