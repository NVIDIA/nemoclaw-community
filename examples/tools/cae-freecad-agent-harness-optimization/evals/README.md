<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# cad-agent evals

Regression evals for the CAD agent, authored with
[NeMo Eval Author](https://github.com/NVIDIA-NeMo/eval-author)'s
trace-to-task workflow and run with [Harbor](https://www.harborframework.com/) 0.24.0.

## Cases

34 tasks share one instruction and one verifier, [verifier/](verifier/) (the nine checks, built
once as the `cad-verifier` image every task's `tests/Dockerfile` starts from). Only the
meshes (stored gzipped), the reference solution and the solution's face count (`REF_FACES` in
`tests/test.sh`) differ. They are split three ways ([splits.json](splits.json) gives each task's split,
family and slice):

| Split | Tasks | Used for |
| --- | --- | --- |
| [train/](train/) | 20 generated: 4 each of turned parts, lofted tubs, cups with handles, scoops and ribbed brackets | Everything the experimenters see: meshes, runs and traces. |
| [val/](val/) | 7 generated, from the same families | The keep decision: two runs per task. Never read by an experimenter. |
| [test/](test/) | 3 generated at sizes outside the training range, 2 tee fittings (a family never trained on), and the two hand-made parts | Read once, on the final agent and the base agent. |

The two hand-made parts came first:
[part-1-reconstruction](test/part-1-reconstruction/) from Helix trace
`01a11fc2-cbe4-7353-837a-f20c04071618`, cited by NeMo Compass Insights of the first baseline,
and [part-2-reconstruction](test/part-2-reconstruction/), a second first-party part added by
the owner. The generated tasks are parametric FreeCAD parts in a random pose and mesh
resolution; each one's reference solution is the model its mesh was exported from. The
agent's mesh (`environment/reference.obj.gz`, unpacked to `/app/reference.obj`) may be
tessellated more coarsely than the verifier's (`tests/reference.obj.gz`) and carry vertex
noise.

The agent gets the [instruction](test/part-1-reconstruction/instruction.md): rebuild
`/app/reference.obj` as an editable PartDesign model and save it to `/app/model.FCStd`.
The verifier grades that file in its own container with nine checks, all of which must
pass ([verifier/check_model.py](verifier/check_model.py)): `recomputes-after-reopen`, `single-valid-solid`, `native-feature-tree`,
`named-dimension-drives-geometry`, `independent-dimensions` (two named dimensions that
each change the part in a different way), `mesh-fidelity` (IoU ≥ 0.9),
`no-missing-feature` (no whole feature left out), `single-visible-object` and
`compact-model` (at most 10× the reference solution's faces). See the [grading explanation](test/part-1-reconstruction/README.md#verification-explanation).

## How a trial runs

```text
harbor run (host) ── per trial, in parallel ──┐
                                              ▼
  task container (evals/<split>/<task>/environment)  verifier container (.../<task>/tests)
  headless FreeCAD 1.1.3 + Deep Agents + NeMo Relay   FROM cad-verifier: FreeCAD 1.1.3, no network
  /agent  ← agent/ (prompt, skills)                  grades /app/model.FCStd → reward
  /app    reference.obj → model.FCStd ─────────────▶
  network: NeMo Helix only (model gateway, Intake)
```

[`harness/cad_agent.py`](../harness/cad_agent.py) uploads the agent folder and starts
[`harness/run_agent.py`](../harness/run_agent.py), which runs the agent for at most
5 minutes (`CAD_AGENT_TIMEOUT`) and sends its trace to Intake. After a job,
[`publish.py scores`](../publish.py) attaches each run's reward, IoU, failed checks
and complexity counts to its trace for NeMo Compass.

## Setup

Run every command from the example root
(`examples/tools/cae-freecad-agent-harness-optimization`). You need:

- Harbor 0.24.0: `uv tool install harbor==0.24.0`.
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
docker build -t cad-verifier evals/verifier   # every task's verifier starts from it
for s in train val test; do   # one split per job
  harbor run -y -p evals/$s -a nop    -n 4 --jobs-dir runs --job-name nop-$s
  harbor run -y -p evals/$s -a oracle -n 4 --jobs-dir runs --job-name oracle-$s
done
# Negative controls: each hand-made task's solution broken one way, generated in the task image
docker build -t cad-env evals/test/part-1-reconstruction/environment
for t in part-1-reconstruction part-2-reconstruction; do mkdir -p controls/$t
  docker run --rm -v "$PWD":/x -w /x -e SOLUTION=evals/test/$t/solution/reference-solution.FCStd \
    -e OUT=controls/$t cad-env freecadcmd controls/make_negatives.py
  for n in visible broken scripted nolast; do
    PYTHONPATH=controls harbor run -y -p evals/test/$t -a replay_agent:ReplayModel \
      --ak model=controls/$t/$n.FCStd --jobs-dir runs --job-name $t-$n
  done
done
```

The agent on one split ([loop/eval.sh](../loop/eval.sh) wraps this, with the verifier
image, grading onto the traces and a summary; `-m` overrides the model in `agent.yaml`, `--ak agent_dir=...`
picks the agent folder):

```bash
PYTHONPATH=harness harbor run -y -p evals/val -a cad_agent:CadAgent --ak agent_dir=$PWD/results/final-agent \
  -m nvidia-nvidia-nemotron-3-5-super-vl --n-attempts 2 -n 4 --max-retries 2 --retry-include GatewayLost \
  --jobs-dir runs --job-name agent-val
python publish.py scores runs/agent-val
```

Each trial's `verifier/results` lists the checks and `verifier/reward.txt` is 1 only
when all pass; `agent/run.log` starts with the run's Intake trace ID. Browse jobs with
`harbor view --jobs runs`.

## Proof

Every generated task was proved when it was made: the Oracle scores 1 and NOP 0 on all
32, and leaving out any one feature of the reference solution fails
`no-missing-feature`. In the published run every round's Insights were checked against
these checks by hand (Eval Author's skills were not run then); none needed a new or changed
check.

The hand-made tasks were re-proved on 2026-10-26 with nine checks, Harbor 0.24.0, in the container setup above
(separate verifier, no network), after four verifier fixes that Eval Author found after the first proof: `no-missing-feature` sized its voxels by the bounding diagonal only, so on
part 2's thin walls it measured 0 even for a missing feature (the `nolast` control passed
every check); the dimension checks could measure a part left shifted by an earlier probe;
they measured FreeCAD's loose bounding box, which counts spline control points, so a
dimension could seem to move a lofted part that did not move; and a model whose rebuild
hung got no grade. Every control below gives the same result before and after, except
`nolast` on part 2, which now fails as it should:

| Control | part-1 | part-2 | Fails |
| --- | --- | --- | --- |
| NOP (2 runs) | 0, 0 | 0, 0 | every check |
| Oracle (2 runs) | 1, 1 (IoU 0.9039, 7 faces) | 1, 1 (IoU 0.9985, 36 faces) | none |
| `visible`: solution with every feature and sketch visible | 0 | 0 | `single-visible-object` |
| `broken`: solution with its last feature's profile removed | 0 | 0 | `recomputes-after-reopen`, `named-dimension-drives-geometry`, `independent-dimensions` |
| `scripted`: solution's solid as a scripted base shape, plus one sketch-driven pocket | 0 | 0 | `native-feature-tree`, `named-dimension-drives-geometry`, `independent-dimensions` |
| `nolast`: solution with its last additive feature suppressed (part 2: IoU 0.966) | 0 | 0 | part 1: `mesh-fidelity`, `no-missing-feature`, `independent-dimensions`; part 2: `no-missing-feature` |
| `slices`: a real agent run, 32 stacked pads (IoU 0.91, 1,658 faces) | 0 | n/a | `independent-dimensions`, `compact-model` |
| `no-branch`: a real agent run that left out its branch (IoU 0.918) | 0 | n/a | `no-missing-feature` |
| `one-dimension`: a real agent run, 4 ruled lofts driven by one `Params.Length` (IoU 0.970 / 0.943) | 0 | 0 | `independent-dimensions` |

`visible`, `broken`, `scripted` and `nolast` are generated from each task's reference solution by
[controls/make_negatives.py](../controls/make_negatives.py) (see Rerun). `slices`,
`no-branch` and `one-dimension` were real agent runs; their results are recorded here, and
the models are not shipped.

Isolation, probed with Harbor 0.22.0 on Colima (not probed again under 0.24.0, whose allowlist runs through an egress proxy): the agent reaches only
`host.docker.internal` (public hosts are blocked; the allowlist is per host, so every
port on the host is reachable), and the verifier reaches nothing. The agent's
container holds only the mesh; the solution and tests stay with the verifier.
