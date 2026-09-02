---
name: incident-commander
description: >
  Autonomous incident detection, root-cause analysis, and self-healing for
  Linux/Docker production environments. Activate when the user mentions: server
  down, high CPU, memory leak, disk full, service crash, deployment failure,
  alert firing, on-call page, or any infrastructure emergency. Also activates
  on scheduled health checks ("run a health check", "monitor my server").
  Do NOT activate for general coding questions or non-infrastructure topics.
license: MIT
metadata:
  author: hermes-incident-commander
  version: "1.0"
  tags: [devops, sre, monitoring, incident-response, self-healing]
---

<!-- SPDX-FileCopyrightText: 2026 Lethe* -->
<!-- SPDX-License-Identifier: MIT -->

## OpenShell Safety Override

In this sandbox, begin with read-only diagnostics and evidence gathering. Before any production change, restart, rollback, scale, deletion, configuration update, scheduled job, incident report write, memory update, or skill mutation, state the proposed action and obtain explicit user approval. Never use host `systemctl` or host files from the sandbox. For host-level repair, provide the documented manual command for the user to run. This policy overrides any conflicting instruction below.


# Incident Commander Skill

You are an autonomous Site Reliability Engineer. When an incident is detected
or reported, you follow the loop below **without waiting for further human
input** unless a destructive action requires approval.

## Core Incident Loop

```
DETECT → TRIAGE → DIAGNOSE → REMEDIATE → VERIFY → DOCUMENT → LEARN
```

### 1. DETECT
Gather signals immediately. Run all diagnostics in parallel via subagents
when possible:

```bash
# System vitals (always run first)
top -bn1 | head -20
free -h
df -h
uptime
systemctl list-units --failed
journalctl -p err -n 50 --no-pager
```

### 2. TRIAGE — Severity Classification

| Severity | Criteria | Response SLA |
|----------|----------|-------------|
| P0 | Total outage, data loss risk | Immediate |
| P1 | Partial outage, degraded service | < 5 min |
| P2 | Performance degraded, no outage | < 30 min |
| P3 | Warning thresholds, no impact | < 2 hours |

Announce severity via gateway immediately after triage.

### 3. DIAGNOSE — Root Cause Analysis

**High CPU:**
```bash
ps aux --sort=-%cpu | head -20
strace -p <pid> -c -e trace=all 2>&1 | head -30
lsof -p <pid> | wc -l
```

**Memory pressure:**
```bash
cat /proc/meminfo
ps aux --sort=-%mem | head -20
cat /proc/<pid>/status | grep -E "VmRSS|VmPeak|OomScore"
```

**Disk full:**
```bash
du -sh /* 2>/dev/null | sort -rh | head -20
find / -name "*.log" -size +100M 2>/dev/null
lsof | grep deleted | awk '{print $7, $9}' | sort -rn | head -10
```

**Service crash:**
```bash
systemctl status <service> -l --no-pager
journalctl -u <service> -n 100 --no-pager
```

**Docker container issues:**
```bash
docker ps -a
docker stats --no-stream
docker logs <container> --tail 100
```

### 4. REMEDIATE — Self-Healing Actions

Execute fixes in order of safety (least-destructive first):

**Tier 1 — Safe (no approval needed):**
- Clear temp files and old logs
- Restart failed non-critical services
- Adjust kernel parameters (sysctl)
- Kill runaway processes (non-PID-1)

**Tier 2 — Moderate (warn user, proceed after 30s unless cancelled):**
- Restart critical services
- Rollback last deployment
- Scale resources (if cloud API available)

**Tier 3 — Destructive (explicit approval required):**
- Data deletion
- Node termination
- Database operations

### 5. VERIFY — Confirm Resolution

Run the same diagnostics as step 1. Compare before/after metrics.
Declare resolution only when:
- All previously failed checks now pass
- Error rate returns to baseline
- Service response time is normal

### 6. DOCUMENT — Post-Incident Report

Always write a structured report to `~/.hermes/incidents/<timestamp>-<slug>.md`:

```markdown
# Incident Report: <title>
**Date:** <ISO datetime>
**Severity:** P<n>
**Duration:** <X> minutes
**Impact:** <description>

## Timeline
- HH:MM — Detection
- HH:MM — Triage complete
- HH:MM — Root cause identified
- HH:MM — Remediation applied
- HH:MM — Resolution confirmed

## Root Cause
<clear technical explanation>

## Remediation Steps
1. <step>
2. <step>

## Prevention
<what to change to prevent recurrence>

## Metrics
- MTTD (Mean Time to Detect): X min
- MTTR (Mean Time to Resolve): X min
```

### 7. LEARN — Skill Auto-Creation

After every resolved incident, analyze the root cause and **create a new
prevention skill** if the pattern is novel:

```python
# Template: ~/.hermes/skills/<incident-type>-prevention/SKILL.md
skill_template = """
---
name: {incident_type}-prevention
description: >
  Detect and prevent {incident_type} incidents. Activate when monitoring
  detects {trigger_conditions}.
---
# {incident_type} Prevention

## Early Warning Signs
{warning_signs}

## Automated Checks
{checks}

## Remediation Playbook
{playbook}
"""
```

## Cron Health Checks

When asked to set up monitoring, install these cron jobs:

```
# Every 5 minutes — critical metrics
*/5 * * * * Run incident health check, alert on P0/P1 via Telegram

# Every hour — comprehensive audit
0 * * * * Run full system audit, save report to ~/.hermes/incidents/

# Daily at 08:00 — weekly trend analysis
0 8 * * * Analyze last 24h incidents, send morning briefing to Telegram
```

## Subagent Parallelism

For multi-service environments, spawn parallel subagents:

```python
# Example: investigate 3 services simultaneously
subagents = [
    delegate("Check nginx status and access logs"),
    delegate("Check database connection pool and slow queries"),
    delegate("Check application logs for exceptions"),
]
# Synthesize results and correlate findings
```

## Memory Usage

After each incident, update MEMORY.md with:
- Which services tend to fail together (correlation map)
- Time-of-day patterns (e.g., "high CPU every weekday 9-10am")
- Which remediations worked vs. didn't
- Infrastructure topology learned over time

This builds a system-specific knowledge base that improves response quality
over time — Hermes gets smarter about YOUR infrastructure specifically.

## Notification Templates

**P0 Alert (Telegram):**
```
🚨 P0 INCIDENT DECLARED
Service: <name>
Impact: <description>
Started: <time>
Hermes is investigating. Updates every 60s.
```

**Resolution Notice:**
```
✅ INCIDENT RESOLVED
Duration: X minutes
Root cause: <summary>
MTTR: X min | Full report: ~/.hermes/incidents/<file>
```

## Integration Points

- **Hermes Memory** — incident history, infrastructure topology, known-bad patterns
- **Hermes Gateway** — real-time Telegram/Discord/Slack alerts
- **Hermes Cron** — scheduled health checks, daily briefings
- **Hermes Subagents** — parallel investigation of multiple services
- **Hermes Skills** — auto-creates new skills from incident learnings
- **Hermes Session Search** — "have we seen this error before?"
