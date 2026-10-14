<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# cad-agent evals

Regression evals for the CAD agent, authored with
[NeMo Eval Author](https://github.com/NVIDIA-NeMo/eval-author)'s
trace-to-task workflow and run with [Harbor](https://www.harborframework.com/) 0.22.0.

## Cases

| Case | Tests | Source |
| --- | --- | --- |
| [part-1-reconstruction](part-1-reconstruction/) | Rebuild `reference_part.obj` as an editable PartDesign model. Five checks, all must pass: `single-valid-solid`, `native-feature-tree`, `named-dimension-drives-geometry`, `mesh-fidelity` (IoU ≥ 0.9, recomputed by the verifier), and `single-visible-object` (added 2026-10-14). See its [instruction](part-1-reconstruction/instruction.md) and [grading explanation](part-1-reconstruction/README.md#verification-explanation). | Helix trace `01a11fc2-cbe4-7353-837a-f20c04071618`, cited by both NeMo Compass Insights of the first baseline. |
| [part-2-reconstruction](part-2-reconstruction/) | The same instruction and five checks for a second part, `reference_part_2.obj`, so the suite tests that the method works for more than one shape. | Added by the owner on 2026-10-14; no source trace. |

## Setup

Run every command from the example root
(`examples/tools/cae-freecad-agent-harness-optimization`). You need:

- Harbor 0.22.0: `uv tool install harbor==0.22.0`.
- A Docker engine that can run containers without network access. Docker Desktop on
  macOS cannot; [Colima](https://github.com/abiosoft/colima) can, for files under
  your home folder: `colima start` and
  `export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"`.
- For agent runs only: the Helix services, the `cad-agent-deployment`, and FreeCAD
  with its RPC server. The
  Harbor agent is [`harness/helix_cad_agent.py`](../harness/helix_cad_agent.py).
  Agent runs must be serial (`-n 1`): there is one FreeCAD session.

## Rerun

`-p evals` runs both tasks. Task controls, which need no agent or FreeCAD:

```bash
harbor run -p evals -a nop    --jobs-dir results/runs --job-name nop
harbor run -p evals -a oracle --jobs-dir results/runs --job-name oracle
```

The agent:

```bash
PYTHONPATH=harness harbor run -p evals \
  -a helix_cad_agent:HelixCadAgent --n-attempts 3 -n 1 \
  --jobs-dir results/runs --job-name <name>
```

Results land in `results/runs/<name>/`. Each trial's `verifier/results` lists
the checks; `verifier/reward.txt` is 1 only when all pass. Browse them with
`harbor view --jobs results/runs`.

## Results

**Task controls** (separate verifier, no network), rerun on 2026-10-14 with the 0.9
IoU threshold:

| Control | part-1 | part-2 |
| --- | --- | --- |
| NOP (2 runs) | 0, 0 | 0, 0 |
| Oracle (2 runs) | 1, 1 (IoU 0.9038) | 1, 1 (IoU 0.9985) |
| Negative (1 run) | 0 (IoU 0.3223) | 0 |

Eval Author's finalized receipts cover part-1's first, four-check version.

Agent results, round by round, are in [results/](../results/README.md).
