# Logging

Use this when adding or reviewing application logs.

## Defaults

- Structured logging means a stable schema with typed fields and consistent
  semantics. JSON text with drifting keys is only semistructured.
- Prefer semantic event names over prose messages: `checkout.payment_failed`,
  `user.login_succeeded`, `worker.job_retry_scheduled`.
- Use OpenTelemetry semantic conventions where they exist for service, resource,
  HTTP, database, messaging, exception, and cloud attributes.
- Every operational log event should carry service/resource identity,
  environment, severity, event name, outcome, and trace/correlation context when
  available.
- Logs explain decisions and state transitions. Metrics quantify behavior.
  Traces connect causality across boundaries.

## Event Shape

Use stable keys. Good baseline fields:

- `timestamp`
- `severity` or `level`
- `event.name`
- `message`
- `service.name`
- `deployment.environment.name`
- `trace_id`, `span_id`, or project-standard correlation/request ID
- `operation.name`
- `outcome` such as `success`, `failure`, `retry`, `drop`, or `defer`
- `error.type`, `error.message`, and stack trace when an exception matters

Prefer domain-specific attributes over packed strings. For example, log
`order.id`, `payment.provider`, and `retry.attempt` as fields, not inside the
message.

## Level Policy

- `DEBUG`: development or short-lived diagnostic detail; off by default in
  production unless sampled or scoped.
- `INFO`: meaningful service decisions, lifecycle events, business state
  transitions, and successful important operations.
- `WARN`: degraded behavior, retries, fallback paths, rate limiting, timeouts,
  or unusual states that did not fail the user-visible operation.
- `ERROR`: failed service operation, data loss risk, invariant violation, or
  operator-actionable failure.

Do not log expected validation failures, routine 404s, or user mistakes as
`ERROR`. They may be `INFO` or `WARN` depending on product and abuse signals.

## Cardinality and Indexing

- Per-user, per-entity, request, session, and trace IDs are useful in logs but
  high-cardinality. Include them deliberately and avoid indexing them by default
  unless the query path needs it.
- Never copy high-cardinality log fields into metric labels.
- Avoid unbounded values in event names. Use `payment.failed` with
  `payment.provider=stripe`, not `stripe_payment_failed`.
- Sample noisy success logs before sampling rare failures.

## Errors

- Log an exception once at the boundary that owns the response, retry, or job
  outcome. Do not emit the same stack trace at every layer.
- Include operation, dependency, retryability, attempt count, timeout, status
  code, and sanitized exception details.
- Preserve cause chains where the language supports them.
- Pair retried errors with a final success/failure event so operators can tell
  whether the retry budget worked.

## Sensitive Data

- Redact at source. Collector-side filtering is defense in depth, not the
  primary control.
- Do not log secrets, bearer tokens, session cookies, raw passwords, private
  keys, full payment data, or raw request/response bodies by default.
- Treat URLs as sensitive when query strings can contain tokens or PII.
- Separate audit/security logs from diagnostic logs when retention, access, or
  integrity requirements differ.

## Sources

- OpenTelemetry Logs: https://opentelemetry.io/docs/concepts/signals/logs/
- OpenTelemetry Logs Data Model:
  https://opentelemetry.io/docs/specs/otel/logs/data-model/
- OpenTelemetry Semantic Conventions:
  https://opentelemetry.io/docs/concepts/semantic-conventions/
