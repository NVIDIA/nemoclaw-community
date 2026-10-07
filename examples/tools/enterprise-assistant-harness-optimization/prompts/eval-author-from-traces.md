# Codex task: derive a reviewed Harbor suite with NeMo Eval Author

Use the skills installed from `NVIDIA-NeMo/labs-eval-author`. Begin with its
`eval-author` entry skill and select the supported trace-derived Harbor workflow.
Use Codex as the coding agent. Confirm the intended behavior in the supplied
`ETHOS.md` with the user before constructing tests.

Use the corpus and report paths supplied in the current authoring request.
The paths below are defaults for the saved example only; do not substitute a
saved report for a fresh analysis or mix source corpora.

## Evidence

- Production report: `results/production-insights.yml`
- Corpus index: `traces/world-v3/production/index.json`
- Every ATIF trace in that index (inspect the complete 36–48 trace denominator)
- Intended behavior: `ETHOS.md`
- Tool implementation and fictional world: `src/pa_style_mock_mcp/` and `fixtures/world-v2.json`
- Existing task-materialization contract: `scripts/materialize_harbor_tasks.py`

Do not inspect pre-existing candidate profiles or candidate proposals during
task authoring; harness design is a later stage of the workflow.

Use both the findings and their cited traces. For each finding, verify its cited
behavior in the original trajectories; note contradictions, successes, and
uncertainty. Do not turn each trace or each insight into a task automatically.

## Authoring request

1. Propose independently testable task candidates grounded in the trace and
   Insights evidence. Explain why each deserves a regression test and what the
   grader can objectively establish from the fictional world. First show an
   evidence table: source trace, user task for Hermes, observed tool calls and
   expected behavior under `ETHOS.md`. Include successful behavior to preserve.
2. Use Eval Author's trace-environment workflow for selected examples. Retain
   its private workspaces, ATIF/privacy review, ground-truth provenance,
   tool-access decisions, Harbor NOP/Oracle/negative controls, checksums, and
   publication review artifacts. Keep rejected/no-candidate examples in the
   reported source denominator.
3. Each candidate task must exercise the actual Streamable HTTP MCP implementation
   and fictional world from this repo—not exact-call transcript replay. For
   Eval Author's isolated NOP/Oracle proofs, use the task-local stdio adapter
   backed by the same implementation and fictional company records.
   Measured Hermes runs later must use the separately hosted Streamable HTTP
   MCP from OpenShell through `openshell/policy.yaml`; do not replace the
   measured remote MCP with an in-sandbox server.
4. Propose the number of distinct tasks supported by the evidence. Report the
   count and rationale after the user accepts the tasks. Choose tasks for
   behavior coverage; explain what coverage a larger production suite needs.
5. After all accepted tasks are prepared, propose a development/held-out split
   and explain the behavior coverage and rationale. A human must approve the
   task meanings and split before writing `human_reviewed` or freezing the
   suite. Do not use held-out prompts or expected answers to design the
   candidate harness.

## Output and stopping point

Keep working material private under `.eval-author/`. Do not edit the agent
profiles, runtime, source corpus, checked-in public eval suite, or candidate
implementation during task authoring. Do not claim public-release approval.

Before stopping, report:

- source trace count, IDs, and behavior-family counts;
- each Insights finding, cited traces, candidate/no-candidate decision, and
  resulting task ID if any;
- task proof commands, results, checksums, rejected or blocked items;
- the proposed development/held-out counts and rationale; and
- a visible checklist for each task: faithful user task, sufficient world/tools,
  suitable grading criteria, passing Oracle and failing NOP/negative controls,
  accurate explanation of the lesson, and files suitable to share. Explain any
  decision the user needs to make in plain language; maintain the required Eval
  Author records in the workspace.

Stop for human review wherever Eval Author requires a human decision. Do not
silently mark pending decisions complete or materialize measured Harbor tasks
from unreviewed drafts.
