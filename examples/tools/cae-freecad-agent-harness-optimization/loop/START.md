<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Run the loop

Paste the prompt below into a fresh coding-agent session (Claude Code, Codex or another)
opened in `examples/tools/cae-freecad-agent-harness-optimization`, after the
[Prerequisites](../README.md#prerequisites). Fill in `<run>` and the budget. It runs the
README's Steps 0 to 4 round by round, from the base agent in `agent/`, and stops for you
once, before the first round.

---

You run one harness-optimization run of the FreeCAD CAD agent, `<run>`, with a budget of
`<N>` rounds. You schedule and decide; fresh subagents do the experimenting.

1. Read `ETHOS.md`, `README.md` (Start Here, Steps 0 to 4) and the
   `cad-experimenter` skill (`npx skills add ./skills --skill cad-experimenter --agent <you> --yes`).
   Do not read `results/`, the README's Results, or other folders under `experiments/`:
   earlier runs must not shape this one.
2. Check the stack: Helix answers (`nemo --version`, the gateway lists the agent's model and
   Compass's), Docker reaches Colima, `harbor` and `compass` are installed, `.env` is filled.
   Run the eval's controls once (`evals/README.md`, Rerun): NOP 0, Oracle 1, every negative
   0. Stop and report anything that fails.
3. Tell the owner, in five lines: the goal (the ETHOS success criteria), the budget, the
   splits (`evals/train`, `evals/val`, `evals/test`) with one run per train task and two per
   val task, the run limit, the keep rule (the skill's). Wait for one "go".
4. Step 0, once: a frontier solve of a few train parts of different families in the agent's
   image, from the ETHOS, the instruction and the mesh alone. Write
   `experiments/<run>/FRONTIER.md`: what worked, with no numbers or shapes specific to these
   parts. Experimenters read only that.
5. Each round `N` in `experiments/<run>/round-<N>/`, with the agent under study in its
   `agent/` (round 0: a copy of `agent/`):
   - Step 1: `loop/eval.sh` on train (1 run per task); in round 0 also on val (2 runs per
     task), the baseline. A kept candidate brings its val runs with it.
   - Step 2: `loop/compass.sh` on this round's train runs. Start nothing else until
     `insights.yml` exists.
   - Step 3: Eval Author checks each Insight against the eval, and passing models against
     the Ethos ([EVAL-AUTHOR.md](EVAL-AUTHOR.md)); stop for the owner on any proposal.
     A new or fixed check is proven (NOP 0, Oracle 1, a realistic negative 0) before it
     is applied, and stored runs are regraded (`harbor jobs regrade`), never re-run.
     Decide on the new grades.
   - Step 4: two experimenter subagents with the `cad-experimenter` skill, each given a
     different area. They read train only: never `evals/val`, `evals/test` or
     `evals/splits.json`. Measure each candidate on val (2 runs per task) and on train (1 run per task) with
     `loop/eval.sh`, and
     apply the keep rule on val (`loop/summary.py CANDIDATE_VAL AGENT_VAL`).
   - Append to `experiments/<run>/LOG.md`: time stamps, results, the decision and why.
6. Never change the ETHOS, the keep rule, the splits, the runs per task or the run limit
   during the run; log the request for the next one. A run lost to the infrastructure is VOID: re-run it,
   never count it, and stop if the same failure repeats.
7. Stop at the budget, or after two rounds in a row with no kept candidate. Read test once:
   the final agent and the base agent, 5 runs per task each (`loop/eval.sh ... test 5`), and
   write
   `experiments/<run>/REPORT.md`: the eval and its changes, every round and decision, the
   Insights and what resolved each, and the final agent against the base agent.
