<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# Example Runbooks

Complete runbook examples for common scenarios.

## API Service - High Error Rate

```markdown
# API Service - High Error Rate Investigation

## Overview
Investigate and resolve elevated 5xx error rates in the API service.

**Last Updated**: 2024-01-15
**Owner**: Platform Team
**Related Alerts**: api-high-error-rate, api-slo-breach

## Symptoms
- Alert: `api-high-error-rate` firing
- Error rate > 1% on dashboard
- User complaints about failures

## Impact
- **Users Affected**: All API consumers
- **Severity**: SEV2 if > 5%, SEV3 if 1-5%
- **Business Impact**: Failed transactions, poor user experience

## Diagnostic Steps

### Step 1: Confirm Error Rate
```bash
# Check current error rate
curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~'5..'}[5m]))/sum(rate(http_requests_total[5m]))" | jq '.data.result[0].value[1]'
```

### Step 2: Identify Error Types
```bash
# Check error distribution by status code
kubectl logs -l app=api-service -n production --tail=1000 | grep -E '"status":\s*5[0-9]{2}' | jq -r '.status' | sort | uniq -c
```

**Common patterns**:
- 500: Application error → Check app logs
- 502: Upstream error → Check dependencies
- 503: Service unavailable → Check resources
- 504: Timeout → Check latency/dependencies

### Step 3: Check Recent Changes
```bash
# Recent deployments
kubectl rollout history deployment/api-service -n production

# Recent config changes
kubectl get configmap api-config -n production -o yaml | head -20
```

### Step 4: Check Dependencies
```bash
# Database connectivity
kubectl exec -it deployment/api-service -n production -- nc -zv db-host 5432

# Cache connectivity  
kubectl exec -it deployment/api-service -n production -- redis-cli -h cache-host ping
```

## Resolution Options

### Option A: Rollback (if recent deployment)
```bash
kubectl rollout undo deployment/api-service -n production
kubectl rollout status deployment/api-service -n production
```

### Option B: Restart (if memory/state issue)
```bash
kubectl rollout restart deployment/api-service -n production
kubectl rollout status deployment/api-service -n production
```

### Option C: Scale Up (if capacity issue)
```bash
kubectl scale deployment/api-service -n production --replicas=10
kubectl get pods -n production -l app=api-service
```

### Option D: Enable Circuit Breaker (if dependency issue)
```bash
# Update feature flag
curl -X POST "http://feature-flags/api/flags/circuit-breaker-enabled" -d '{"value": true}'
```

## Verification
```bash
# Error rate should drop within 5 minutes
watch -n 30 'curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~\"5..\"}[5m]))/sum(rate(http_requests_total[5m]))" | jq ".data.result[0].value[1]"'
```

- [ ] Error rate < 0.1%
- [ ] No new alerts firing
- [ ] User complaints resolved

## Escalation
1. **Platform Team**: #platform-oncall Slack
2. **Service Owner**: Page via PagerDuty
3. **VP Engineering**: If SEV1 > 30 minutes
```

---

## Kubernetes - Pod OOMKilled

```markdown
# Kubernetes - Pod OOMKilled Recovery

## Overview
Respond to pods being killed due to memory exhaustion.

**Last Updated**: 2024-01-15
**Owner**: Platform Team
**Related Alerts**: pod-oomkilled, container-memory-high

## Symptoms
- Alert: `pod-oomkilled` firing
- Pods in CrashLoopBackOff with OOMKilled reason
- Application errors related to memory

## Diagnostic Steps

### Step 1: Identify Affected Pods
```bash
kubectl get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]?.lastState.terminated.reason=="OOMKilled") | "\(.metadata.namespace)/\(.metadata.name)"'
```

### Step 2: Check Memory Usage History
```bash
# Current memory usage
kubectl top pods -n [namespace] | grep [pod-prefix]

# Memory limits
kubectl get pod [pod-name] -n [namespace] -o jsonpath='{.spec.containers[*].resources.limits.memory}'
```

### Step 3: Analyze Memory Pattern
```bash
# Check if memory grew over time (leak) or spiked (traffic)
# View in Grafana: [dashboard-link]

# Check recent traffic
kubectl logs [pod-name] -n [namespace] --tail=500 | grep -c "request"
```

## Resolution Options

### Option A: Increase Memory Limit (temporary)
```bash
# Patch deployment with higher limits
kubectl patch deployment [deployment] -n [namespace] -p '{"spec":{"template":{"spec":{"containers":[{"name":"[container]","resources":{"limits":{"memory":"1Gi"}}}]}}}}'
```

### Option B: Scale Horizontally
```bash
# Add more replicas to distribute load
kubectl scale deployment [deployment] -n [namespace] --replicas=5
```

### Option C: Restart to Clear Leak
```bash
kubectl rollout restart deployment/[deployment] -n [namespace]
```

## Long-Term Fix
- [ ] Profile application memory usage
- [ ] Identify memory leaks
- [ ] Right-size resource limits
- [ ] Add memory-based HPA

## Verification
```bash
# No OOMKilled events in last 10 minutes
kubectl get events -n [namespace] --field-selector reason=OOMKilled --sort-by='.lastTimestamp'
```
```

---

## Database - Connection Exhaustion

```markdown
# Database - Connection Pool Exhaustion

## Overview
Resolve database connection pool exhaustion causing application errors.

**Last Updated**: 2024-01-15
**Owner**: DBA Team
**Related Alerts**: db-connections-high, db-connection-errors

## Symptoms
- Alert: `db-connections-high` firing
- Application logs: "too many connections" or "connection pool exhausted"
- Slow or failed database queries

## Diagnostic Steps

### Step 1: Check Current Connections
```sql
-- PostgreSQL
SELECT count(*), state 
FROM pg_stat_activity 
GROUP BY state;

-- Check max connections
SHOW max_connections;
```

### Step 2: Identify Connection Holders
```sql
-- PostgreSQL - connections by application
SELECT application_name, count(*) 
FROM pg_stat_activity 
GROUP BY application_name 
ORDER BY count DESC;

-- Long-running queries holding connections
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY duration DESC
LIMIT 10;
```

### Step 3: Check for Connection Leaks
```bash
# Check application connection pool metrics
curl http://[app-host]/metrics | grep db_pool
```

## Resolution Options

### Option A: Kill Idle Connections
```sql
-- PostgreSQL - kill idle connections older than 10 minutes
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE state = 'idle' 
AND query_start < now() - interval '10 minutes';
```

### Option B: Restart Application Pods
```bash
# Force new connection pool
kubectl rollout restart deployment/[app] -n production
```

### Option C: Increase Max Connections (temporary)
```sql
-- PostgreSQL (requires restart)
ALTER SYSTEM SET max_connections = 200;
-- Then restart PostgreSQL
```

### Option D: Kill Blocking Queries
```sql
-- Find and kill long-running queries
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE duration > interval '5 minutes'
AND state != 'idle';
```

## Verification
```sql
SELECT count(*) FROM pg_stat_activity;
-- Should be well below max_connections
```

## Long-Term Fix
- [ ] Review connection pool settings in applications
- [ ] Implement connection pooler (PgBouncer)
- [ ] Add connection timeout settings
- [ ] Monitor for connection leaks
```

---

## Redis - Memory Pressure

```markdown
# Redis - Memory Pressure Response

## Overview
Respond to Redis memory pressure that may cause evictions or failures.

**Last Updated**: 2024-01-15
**Owner**: Platform Team
**Related Alerts**: redis-memory-high, redis-evictions

## Symptoms
- Alert: `redis-memory-high` firing
- Increased cache miss rate
- Eviction warnings in Redis logs

## Diagnostic Steps

### Step 1: Check Memory Usage
```bash
redis-cli -h [redis-host] INFO memory | grep -E "used_memory|maxmemory"
```

### Step 2: Check Key Distribution
```bash
# Find large keys
redis-cli -h [redis-host] --bigkeys

# Count keys by pattern
redis-cli -h [redis-host] --scan --pattern "session:*" | wc -l
redis-cli -h [redis-host] --scan --pattern "cache:*" | wc -l
```

### Step 3: Check Eviction Policy
```bash
redis-cli -h [redis-host] CONFIG GET maxmemory-policy
```

## Resolution Options

### Option A: Clear Specific Cache Pattern
```bash
# Clear session cache (example)
redis-cli -h [redis-host] --scan --pattern "cache:expired:*" | xargs -L 100 redis-cli -h [redis-host] DEL
```

### Option B: Adjust TTLs
```bash
# Set TTL on keys without expiration
redis-cli -h [redis-host] --scan --pattern "temp:*" | while read key; do
  redis-cli -h [redis-host] EXPIRE "$key" 3600
done
```

### Option C: Scale Redis (if using cluster)
```bash
# Add shard to cluster
redis-cli --cluster add-node [new-node]:6379 [existing-node]:6379
redis-cli --cluster rebalance [existing-node]:6379
```

## Verification
```bash
# Memory should be below 80%
redis-cli -h [redis-host] INFO memory | grep used_memory_human
```

## Long-Term Fix
- [ ] Review TTL policies
- [ ] Implement cache warming strategy
- [ ] Consider Redis Cluster for horizontal scaling
- [ ] Audit large keys
```
