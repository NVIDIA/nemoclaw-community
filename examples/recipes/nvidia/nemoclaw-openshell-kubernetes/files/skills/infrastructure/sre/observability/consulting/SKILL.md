---
name: observability-consulting
description: Use for observability, logs, metrics, traces, health checks, dashboards, alerts, and SLOs.
---

# Observability

## Iron Law

`NO USER-REACHABLE SERVICE PATH SHIPS BLIND.`

## When to Use

- Logs, metrics, traces, health checks, dashboards, SLOs, alerts,
  dependency health, incident diagnosis, OpenTelemetry, RED/USE,
  cardinality, exemplars, or burn-rate alerts.

## When NOT to Use

- Local-only scripts or libraries with no operational surface.
- Error type design; use `error-handling`.
- Release sequencing; use `release`.

## Core Ideas

1. Instrument behavior customers depend on, not just process internals.
2. Logs are structured events with stable names, typed fields,
   severity, outcome, and trace/correlation IDs. JSON alone is not
   enough.
3. Use OpenTelemetry semantic conventions where they exist before
   inventing custom field names.
4. Metrics need bounded labels; cardinality is a production cost and
   reliability risk.
5. Traces show cross-boundary causality; logs explain decisions.
6. Critical dependencies expose latency, error, timeout, retry,
   circuit-breaker state, and saturation signals.
7. Dashboards answer current health and likely fault location. Alerts
   are SLO-backed, actionable, and tied to runbooks.
8. Health checks separate liveness from readiness.
9. Sensitive data is redacted at source; collector filtering is
   defense in depth.

## Workflow

1. Identify the user-facing path, dependency, queue, or resource being
   observed. Choose RED for request paths, USE for resources.
2. Add structured logs, metrics, and spans per project conventions;
   for logging changes, load `references/logging.md`.
3. Bound metric labels and high-cardinality log fields. Redact
   sensitive fields at the source.
4. Add dashboards for health, latency, errors, saturation, and
   dependency state. Add alerts only when action and escalation are
   clear.

## Verification

- [ ] New user-reachable paths emit request/error/duration or
      equivalent RED signal.
- [ ] Logs are structured with stable event names, typed fields,
      severity, outcome, and trace/correlation ID; levels distinguish
      expected client failures from operator-actionable errors.
- [ ] Traces cover important inbound and outbound boundaries.
- [ ] Critical dependencies emit latency, error, timeout, retry, and
      saturation or circuit-state signals.
- [ ] Metric labels are bounded; high-cardinality log attributes are
      intentional.
- [ ] Logs, metrics, and spans exclude secrets, tokens, raw PII,
      payment data, and unreviewed payload bodies.
- [ ] Liveness does not depend on external systems; readiness does.
- [ ] Dashboards answer health, latency, errors, saturation, and
      dependency state; alerts link to runbooks with action and
      escalation.
- [ ] For prototypes, deferred observability is recorded and the path
      is promoted to the full checklist before real users.

## Tripwires

| Trigger | Do this instead | False alarm |
|---|---|---|
| "We logged the error, so it is observable" | Add stable event names, outcome, severity, and trace/correlation ID. | Existing project logger adds those fields automatically and tests prove it. |
| "Put user ID / request ID / path in a metric label" | Bound metric labels. Put high-cardinality values in logs or traces. | The label set is proven bounded and low-cardinality. |
| "Alert on every error" | Alert on user impact, SLO burn, or actionable dependency failure. | Low-volume critical security or data-loss event. |
| "Health check should test the database" | Keep liveness local. Put external dependencies in readiness or dependency health. | The endpoint is explicitly readiness, not liveness. |
| "The collector will redact it" | Redact sensitive fields at the source; collector filtering is defense in depth. | Source redaction is impossible and the risk is documented. |
| "Dashboard later" | Add the view needed to identify current health and likely fault location. | Local-only prototype with deferred observability recorded. |

## Handoffs

- Use `documentation` for runbook shape.
- Use `async-systems` for stream lag, fanout, replay, consumer group, and
  delivery semantics before instrumenting them.
- Use `release` for rollout gates and production verification.
- Use `error-handling` for remote dependency timeout, retry, and
  circuit-breaker behavior before instrumenting it.

## References

- `references/logging.md`: structured and semantic logging rules.
