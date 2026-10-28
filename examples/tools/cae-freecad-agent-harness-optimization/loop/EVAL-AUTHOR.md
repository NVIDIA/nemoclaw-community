<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Step 3, each round: check the eval with NeMo Eval Author

Paste into your coding agent after Step 2 of round `<N>` of run `<run>`, with the
[Eval Author skills](https://github.com/NVIDIA-NeMo/eval-author) installed. Start from its
`eval-author` entry skill and use `eval-author-task-create` in proposal mode.

---

Review whether the eval still measures what `ETHOS.md` asks for, for round `<N>` of run
`<run>`. Propose; do not change the eval, the agent or the runs.

## Evidence

- Intended behaviour: `ETHOS.md`.
- The eval: the nine checks in `evals/verifier/check_model.py`
  (shared by every task), `evals/manifest.json` and the proof in `evals/README.md`.
- This round's Insights: `experiments/<run>/round-<N>/insights.yml`, and the train traces
  each one cites.
- Passing models: three or more train runs of the agent under study that pass every check
  (`experiments/<run>/round-<N>/runs/train/<trial>/artifacts/app/model.FCStd`, its
  `verifier/` folder). Render them beside their mesh
  ([skills/cad-experimenter/render](../skills/cad-experimenter/render/)).

Read train only: never `evals/val`, `evals/test` or `evals/splits.json`.

## What to do

1. **Each Insight.** Check its cited traces, then decide: *caught* (name the check that fails
   it), *gap* (a model could show it and still pass every check), or *outside the eval* (the
   saved model is not affected). Say why.
2. **Each passing model.** Compare it with the Ethos: design intent, named dimensions a
   designer would change, every feature, no artefacts in the renders. Could it pass every
   check and still miss what the Ethos asks for?
3. **Each gap.** Propose one check: what it measures, a realistic wrong model it must fail,
   and a plan to prove it (an empty model scores 0, the reference solution 1, the wrong
   model 0). Where the Ethos is silent on the gap, propose the Ethos sentence too.

## Output and stopping point

Write `experiments/<run>/round-<N>/EVAL-AUTHOR.md`: a table of Insight, decision, check and
reason; a table of passing model, verdict and evidence; and the proposals. Then stop for the
owner. Only an accepted proposal becomes a check: prove it, update the Ethos if needed, and
regrade the stored runs (README, Run the loop yourself) before the round's keep decision.
