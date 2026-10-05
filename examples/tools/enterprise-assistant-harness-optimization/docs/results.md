# Reference experiment

The frozen candidate improves both splits in a complete fresh-host comparison:

| Split | Baseline | Candidate |
| --- | ---: | ---: |
| Development: 2 tasks × 3 attempts | [3/6](../results/baseline-development-summary.json) | [6/6](../results/candidate-development-summary.json) |
| Held out: 2 tasks × 3 attempts | [4/6](../results/baseline-held-out-summary.json) | [6/6](../results/candidate-held-out-summary.json) |

All 24 trials have complete Relay capture and zero runtime exceptions. Neither
task regresses; both preparation/no-send controls remain 3/3. The
[comparison](../results/measured-ab-v3.json) includes per-task scores, tool-call
counts from trusted MCP logs, Wilson intervals, and the accepted pilot decision.
The [artifact chain](../results/artifact-chain.json) binds these scores to
actual trial identities, task checksums and runtime fingerprints.

## Evidence and hypothesis

The starting corpus contains 42 distinct production-like requests to Hermes in
OpenShell, calling the fictional company's MCP service outside the sandbox.
[Production Insights](../results/production-insights.yml) identified messages
sent after requests to write or compose a draft. Codex used Eval Author to create
four Harbor tasks: two development and two held out.

The original [development report](../results/baseline-development-insights.yml)
reproduced unauthorized sends in two of six scored traces. Together, these
reports led to the [candidate proposal](../results/candidate-proposal.md) and
[profile](../profiles/candidate-soul.md): preparation is not sending, a tool-issued
token is not user consent, and sending requires explicit authorization.
Across the measured arms, only the profile changes behavior; model, tools, 60-turn limit, world, policy,
API retry budget, runtime deadline and verifier match across measured arms.

Independent [production](../results/verification-production-insights.yml) and
[scored-baseline](../results/verification-baseline-development-insights.yml)
analyses corroborate that frozen hypothesis. The latter cites all three actual
send failures in the measured baseline, alongside three passing controls.
Design evidence and later verification inputs remain separate in the artifact
chain; later reports are not presented as the original cause of the candidate.
The additional retrieval hypotheses in the production reanalysis are not
measured improvements: helper payloads are redacted, and query reformulations
must be distinguished from legitimate page advances.

## Reproduction and limits

The full verification used fresh Ubuntu 24.04 on a Brev CPU host, native Docker,
OpenShell 0.1.2, Hermes 0.21.3 and Harbor 0.22.0, with
`nvidia/nemotron-3-ultra-550b-a55b` through NVIDIA Build. All twenty offline
NOP/Oracle/unauthorized-send controls also reproduced their expected outcomes.
Run `make validate-pilot PYTHON=.harbor-venv/bin/python` to verify the saved chain.

This is a focused approval-boundary pilot, not a benchmark of every enterprise
capability. Three attempts per task do not establish statistical significance.
The held-out requests come from the discovery corpus: a protocol holdout, not
an unseen production distribution. An [independent check](../results/replication-check.json)
improved aggregate scores but lost one content-check pass and was rejected.
Do not pool different runtime configurations or expect identical model outputs;
preserve per-task gates when reproducing the experiment.

The profile guides model behavior. Production systems should also enforce user
permission for consequential actions in trusted code. Use the
[review sheet](../evals/REVIEW.md) and walkthrough Step 4's checklist to assess
whether these tasks measure the behavior you intend. Additional tasks are
needed to assess explicitly authorized sends and broader assistant capabilities.
