---
name: sre-sre-operations
description: Diagnose and improve service reliability using an evidence-first SRE workflow for incidents, capacity, logs, on-call runbooks, postmortems, and reliability engineering.
---

# SRE Operations

Use this skill for an outage, error-budget concern, noisy alert, capacity risk,
or reliability review.

1. Establish scope: service, customer impact, environment, start time, and
   recent changes. State unknowns instead of filling them with guesses.
2. Collect read-only evidence first: health, error rate, latency, saturation,
   logs, traces, deploy history, and dependency status.
3. Classify the failure: availability, latency, correctness, capacity,
   dependency, deployment, configuration, or observability gap.
4. Propose the smallest reversible mitigation. Get explicit approval before a
   production restart, rollback, scale change, or configuration change.
5. Record the timeline, decision, owner, and follow-up. A postmortem should
   focus on contributing conditions and concrete prevention work.

Do not expose credentials or circumvent the sandbox's network and tool policy.
This is original Hermes guidance informed by the requested SRE workflow layout
from `zhaoxuya520/AI-Fullstack-Delivery-Workflow`.
