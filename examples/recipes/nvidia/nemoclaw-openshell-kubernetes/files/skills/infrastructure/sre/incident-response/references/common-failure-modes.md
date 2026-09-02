<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# Common Failure Modes

Quick reference for common incident patterns and their typical causes.

## Deployment-Related

### Bad Deploy

**Symptoms**:

- Errors started exactly at deploy time
- New error messages in logs
- Specific endpoint or feature broken

**Investigation**:

```bash
# Check recent deploys
git log --oneline -10
# Compare configs
diff old-config.yaml new-config.yaml
```

**Mitigation**: Rollback to previous version

---

### Configuration Error

**Symptoms**:

- Service starts but behaves incorrectly
- Connection failures to dependencies
- Feature flags not working as expected

**Investigation**:

- Check config diff between working/broken
- Verify environment variables
- Check secrets/credentials validity

**Mitigation**: Revert config change, restart pods

---

## Resource Exhaustion

### Memory Exhaustion

**Symptoms**:

- OOMKilled pods/containers
- Increasing memory usage over time
- Service becoming unresponsive before crash

**Investigation**:

```bash
# Check memory pressure
kubectl top pods -n <namespace>
docker stats --no-stream
free -m
```

**Mitigation**: Restart services, increase limits, identify leak

---

### CPU Saturation

**Symptoms**:

- High latency across all endpoints
- Request queuing
- Timeouts but no errors

**Investigation**:

```bash
kubectl top pods -n <namespace>
top -bn1 | head -20
```

**Mitigation**: Scale up, identify hot path, add caching

---

### Disk Full

**Symptoms**:

- Write failures
- Database errors
- Log rotation failures

**Investigation**:

```bash
df -h
du -sh /var/log/*
lsof | grep deleted
```

**Mitigation**: Clear space, expand volume, fix log rotation

---

### Connection Pool Exhaustion

**Symptoms**:

- "Too many connections" errors
- Timeout acquiring connection
- Some requests work, others fail

**Investigation**:

```bash
# Database connections
SELECT count(*) FROM pg_stat_activity;
# Show connection states
SHOW PROCESSLIST; # MySQL
```

**Mitigation**: Restart to release connections, increase pool size, fix leaks

---

## Dependency Failures

### Database Unavailable

**Symptoms**:

- All database operations failing
- Connection refused/timeout
- Replication lag alerts

**Investigation**:

- Check database cluster health
- Verify network connectivity
- Check for locks/deadlocks

**Mitigation**: Failover to replica, restart primary, clear locks

---

### Cache Failure (Redis/Memcached)

**Symptoms**:

- Increased latency
- Database overload (cache miss stampede)
- Partial functionality broken

**Investigation**:

```bash
redis-cli ping
redis-cli info | grep connected_clients
```

**Mitigation**: Restart cache, failover, enable circuit breaker

---

### Third-Party API Down

**Symptoms**:

- Specific feature broken
- Timeout errors to external service
- Error responses from vendor

**Investigation**:

- Check vendor status page
- Test API manually
- Check rate limit headers

**Mitigation**: Enable fallback, circuit breaker, queue requests

---

## Network Issues

### DNS Resolution Failure

**Symptoms**:

- Intermittent connection failures
- "Name resolution failed" errors
- Works from some pods, not others

**Investigation**:

```bash
nslookup <hostname>
dig <hostname>
cat /etc/resolv.conf
```

**Mitigation**: Use IP directly (temp), fix DNS config, restart CoreDNS

---

### TLS/Certificate Issues

**Symptoms**:

- SSL handshake failures
- Certificate expired errors
- Mixed content warnings

**Investigation**:

```bash
openssl s_client -connect host:443
echo | openssl s_client -connect host:443 2>/dev/null | openssl x509 -noout -dates
```

**Mitigation**: Renew certificate, update trust store

---

### Network Partition

**Symptoms**:

- Some services can't reach others
- Partial failures
- Split-brain scenarios

**Investigation**:

```bash
ping <host>
traceroute <host>
nc -zv <host> <port>
```

**Mitigation**: Identify affected network path, failover AZ/region

---

## Application Issues

### Deadlock

**Symptoms**:

- Requests hang indefinitely
- No errors, just timeouts
- Thread/connection count climbing

**Investigation**:

- Check for lock contention in DB
- Review thread dumps
- Check for circular dependencies

**Mitigation**: Restart service, kill blocking query

---

### Infinite Loop / Recursion

**Symptoms**:

- CPU at 100%
- Single request never completes
- Memory growing rapidly

**Investigation**:

- Thread dump / profiler
- Check recent code changes
- Review retry logic

**Mitigation**: Restart, rollback, kill runaway process

---

### Queue Backup

**Symptoms**:

- Increasing queue depth
- Processing delay growing
- Consumer falling behind

**Investigation**:

```bash
# Check queue depth (varies by system)
rabbitmqctl list_queues
aws sqs get-queue-attributes --queue-url <url> --attribute-names ApproximateNumberOfMessages
```

**Mitigation**: Scale consumers, increase throughput, pause producers

---

## Data Issues

### Data Corruption

**Symptoms**:

- Invalid data in responses
- Constraint violations
- Inconsistent state

**Investigation**:

- Identify affected records
- Check for concurrent writes
- Review recent data migrations

**Mitigation**: Restore from backup, manual correction, stop writes

---

### Replication Lag

**Symptoms**:

- Stale reads
- Read-after-write inconsistency
- Replica falling behind

**Investigation**:

```sql
-- PostgreSQL
SELECT pg_last_xlog_receive_location() - pg_last_xlog_replay_location() AS lag;
-- MySQL
SHOW SLAVE STATUS\G
```

**Mitigation**: Direct reads to primary, wait for catch-up, investigate bottleneck

---

## Quick Diagnosis Checklist

When you don't know where to start:

```
Quick Check:
- [ ] Any recent deploys? → Rollback
- [ ] Single service or widespread? → Dependency vs service issue
- [ ] Started gradually or suddenly? → Resource vs event
- [ ] Errors or timeouts? → Code bug vs resource exhaustion
- [ ] All requests or subset? → Data vs code issue
```
