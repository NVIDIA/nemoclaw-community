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
3. Tell the owner, in five lines: the goal (the ETHOS success criteria), the budget, two runs
   per part per candidate, the run limit, the keep rule (the skill's). Wait for one "go".
4. Step 0, once: a frontier solve of each part in the agent's image, from the ETHOS, the
   instruction and the mesh alone. Write `experiments/<run>/FRONTIER.md`: what worked, with
   no numbers or shapes specific to these parts. Experimenters read only that.
5. Each round `N` in `experiments/<run>/round-<N>/`:
   - Step 1 on the agent under study (`--ak agent_dir=...`, `--max-retries 2
     --retry-include GatewayLost`), then `publish.py scores`.
   - Step 2: Compass on this round's traces, then `publish.py insights`. Start nothing
     else until `insights.yml` exists.
   - Step 3: Eval Author checks each Insight against the eval. A new or fixed check is
     proven (NOP 0, Oracle 1, a realistic negative 0) before it is applied, and stored
     runs are regraded (`harbor jobs regrade`), never re-run. Decide on the new grades.
   - Step 4: two experimenter subagents with the `cad-experimenter` skill, each given a
     different area. Measure their candidates and apply the skill's keep rule.
   - Append to `experiments/<run>/LOG.md`: time stamps, results, the decision and why.
6. Never change the ETHOS, the keep rule, the runs per part or the run limit during the run;
   log the request for the next one. A run lost to the infrastructure is VOID: re-run it,
   never count it, and stop if the same failure repeats.
7. Stop at the budget, or after two rounds in a row with no kept candidate. Confirm the
   final agent against the base agent, 5 runs per part each, and write
   `experiments/<run>/REPORT.md`: the eval and its changes, every round and decision, the
   Insights and what resolved each, and the final agent against the base agent.
