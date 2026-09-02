<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# Common Production Blockers

Issues that frequently block production readiness and how to address them.

## Reliability Blockers

### No SLOs Defined

**Problem**: Service has no clear reliability targets.

**How to Fix**:

1. Identify critical user journeys
2. Define availability target (start with 99.9% if unsure)
3. Define latency targets (p50, p95, p99)
4. Document in service README
5. Set up SLO-based alerting

**Template**:

```
SLO Definition:
- Availability: 99.9% (43.2 min downtime/month allowed)
- Latency: p99 < 500ms, p50 < 100ms
- Error Rate: < 0.1% of requests
- Measurement Window: Rolling 30 days
```

---

### Single Points of Failure

**Problem**: Service depends on single instance/resource.

**Common SPOFs**:

- Single database instance
- Single cache node
- Single load balancer
- Hardcoded dependency endpoints
- Single region deployment

**How to Fix**:

- Add replicas for stateful components
- Use managed services with built-in HA
- Implement connection failover
- Use service discovery instead of hardcoded IPs
- Consider multi-region for critical services

---

### No Circuit Breakers

**Problem**: Dependency failures cascade to your service.

**How to Fix**:

```python
# Example circuit breaker pattern
circuit_breaker = CircuitBreaker(
    failure_threshold=5,      # Open after 5 failures
    recovery_timeout=30,      # Try again after 30s
    expected_exception=ConnectionError
)

@circuit_breaker
def call_dependency():
    return external_service.request()
```

**Libraries**:

- Python: `pybreaker`, `circuitbreaker`
- Java: Resilience4j, Hystrix (deprecated)
- Go: `sony/gobreaker`
- Node.js: `opossum`

---

### Missing Timeouts

**Problem**: Requests hang forever when dependencies are slow.

**How to Fix**:

- Set timeouts on ALL external calls
- Set shorter timeouts for non-critical operations
- Implement deadline propagation

**Guidelines**:
| Call Type | Recommended Timeout |
|-----------|---------------------|
| Database queries | 5-30 seconds |
| Cache operations | 100-500ms |
| HTTP API calls | 5-30 seconds |
| Message queue publish | 5 seconds |

---

## Observability Blockers

### No Structured Logging

**Problem**: Logs are unstructured, hard to search/analyze.

**Bad**:

```
User login failed for user123
```

**Good**:

```json
{
  "level": "warn",
  "message": "User login failed",
  "user_id": "user123",
  "reason": "invalid_password",
  "trace_id": "abc123",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**How to Fix**:

- Use structured logging library
- Include trace_id in all logs
- Log at appropriate levels
- Include context (user_id, request_id, etc.)

---

### Missing Distributed Tracing

**Problem**: Can't follow requests across services.

**How to Fix**:

1. Add OpenTelemetry SDK
2. Configure trace propagation headers
3. Instrument HTTP clients and servers
4. Add spans for key operations
5. Export to tracing backend (Jaeger, Zipkin, etc.)

**Minimum Instrumentation**:

```
Required Spans:
- HTTP server (incoming requests)
- HTTP client (outgoing requests)
- Database queries
- Cache operations
- Message queue operations
```

---

### Alert Fatigue

**Problem**: Too many alerts, team ignores them.

**Signs**:

- > 5 alerts per on-call shift
- Alerts with no clear action
- Same alert fires repeatedly
- Alerts that auto-resolve quickly

**How to Fix**:

- Alert on symptoms, not causes
- Use SLO-based alerting (burn rate)
- Require runbook for every alert
- Delete alerts that never get actioned
- Tune thresholds based on actual incidents

---

## Security Blockers

### Hardcoded Credentials

**Problem**: Secrets in code or config files.

**How to Find**:

```bash
# Search for common patterns
grep -rn "password" --include="*.py" .
grep -rn "api_key" --include="*.js" .
grep -rn "secret" --include="*.yaml" .
```

**How to Fix**:

- Move to secret manager (Vault, AWS Secrets Manager, etc.)
- Use environment variables for local dev
- Rotate any exposed credentials immediately
- Add pre-commit hooks to detect secrets

---

### Missing TLS

**Problem**: Internal traffic unencrypted.

**How to Fix**:

- Enable TLS on all services
- Use service mesh for automatic mTLS
- Configure TLS in load balancers
- Verify certificate chains

**Quick Check**:

```bash
# Test TLS connection
openssl s_client -connect service:443 -servername service
```

---

## Operations Blockers

### No Rollback Plan

**Problem**: Can't quickly revert bad deployments.

**How to Fix**:

```
Rollback Plan Template:

1. Trigger Criteria:
   - Error rate > 1% for 5 minutes
   - Latency p99 > 2x baseline
   - Any SEV1/SEV2 incident

2. Rollback Steps:
   - [ ] Verify rollback version is known
   - [ ] Execute: kubectl rollout undo deployment/<name>
   - [ ] Verify pods are running previous version
   - [ ] Monitor error rates for 10 minutes

3. Time Estimate: 5 minutes

4. Data Considerations:
   - Database migrations: [reversible/not reversible]
   - Cache invalidation: [required/not required]
```

---

### Missing Runbooks

**Problem**: On-call doesn't know how to respond.

**Minimum Runbooks**:

- Service restart procedure
- Database failover
- Cache flush
- Dependency failure response
- Capacity scaling

**Runbook Template**:

```markdown
# [Service] - [Issue Type]

## Symptoms

- What alerts fire
- What users see

## Impact

- Who is affected
- Severity level

## Steps

1. Step one
2. Step two
3. Step three

## Verification

- How to confirm fix worked

## Escalation

- Who to contact if this doesn't work
```

---

### No Load Testing

**Problem**: Unknown capacity limits.

**How to Fix**:

1. Define expected peak traffic
2. Create load test scenarios
3. Run tests in staging environment
4. Test to 2x expected peak
5. Document capacity limits

**Minimum Scenarios**:

- Steady-state load (expected traffic)
- Peak load (2x expected)
- Spike test (sudden traffic increase)
- Soak test (sustained load over time)
