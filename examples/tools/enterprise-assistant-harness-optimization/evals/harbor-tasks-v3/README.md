# Experimental trace-derived Harbor tasks

Four tasks target the approval-boundary behavior identified in the production
Insights report. The [suite manifest](../flywheel-eval-set-v3.json) freezes two
development tasks and two held-out tasks. Each arm runs every task three times:
12 trials per arm, 24 total. Human task/Relevant experience review is pending.

Use the [walkthrough](../../docs/walkthrough.md) to provision the model provider,
OpenShell, and host-side MCP, then run the two splits through
`scripts/run_harbor_eval.py`. These are measured Hermes runs, not Oracle controls.

The task-local stdio MCP uses the same fixture implementation for offline
controls; measured Hermes reaches the host's HTTP MCP through OpenShell policy.
Each task's README explains its source request, grading, and review status.
The [declassified proof receipts](../task-proofs/README.md) bind passing controls
to the exact task trees. Do not edit those trees without regenerating their proof.
