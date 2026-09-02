---
name: sre
description: Route incident response, observability, runbook, and production-readiness work to bundled SRE skills.
---

# SRE Skills Consolidated

Unified Site Reliability Engineering skill category covering incident response, observability, runbooks, production readiness, and operational foundations.

## NemoClaw Runtime Safety

For cluster work, use `/chart-bin/oc --kubeconfig "$SRE_KUBECONFIG"`. Inspect first, then require explicit user approval for each create, update, or patch. Never read Secrets or service-account tokens, use pod exec/attach, grant RBAC/SCC privileges, impersonate identities, or issue DELETE. Refuse deletion requests and give the exact human-run command for an authorized operator. Nested incident-remediation examples never override these limits.

## Sub-Skills

### Incident Response
- **incident-commander** — Incident command structure, roles, communication
- **incident-responder** — Hands-on response procedures, mitigation playbooks
- **incident-response** — Core incident lifecycle: detection → resolution → postmortem
- **incident-response-incident-response** — Advanced incident patterns
- **incident-response-smart-fix** — Automated remediation, self-healing
- **incident-runbook-templates** — Runbook templates, standardization

### Observability
- **observability** — Full observability stack
  - **observability/prometheus** — Metrics collection, rules, alerting
  - **observability/grafana** — Dashboards, visualization, alerting UI
  - **observability/loki** — Log aggregation, querying, retention
  - **observability/opentelemetry** — Distributed tracing, instrumentation
  - **observability/consulting** — Observability strategy, maturity model
  - **observability/implementation** — Rollout patterns, migration
- **observability-setup** — Bootstrap observability stack from scratch

### Runbooks & Documentation
- **runbook-creator** — Runbook authoring, maintenance, automation
- **production-readiness** — Production readiness reviews, checklists, gates

### Operational Foundations
- **sre-operations** — SRE practices: SLO/SLI, error budgets, toil reduction
- **infrastructure-orchestration** — Infrastructure as code, GitOps, drift detection

## Usage

```bash
# Load entire SRE category
skill load sre

# Load specific sub-skill
skill load sre.incident-commander
skill load sre.observability.prometheus
skill load sre.runbook-creator
skill load sre.production-readiness
```

## Incident Response Flow

```
Detection → Triage → Mitigation → Resolution → Postmortem
   │           │          │           │           │
   ▼           ▼          ▼           ▼           ▼
incident-  incident-  incident-  incident-  runbook-
commander  responder  response   response   creator
   │           │          │           │           │
   └───────────┴──────────┴───────────┴───────────┘
                    │
                    ▼
            observability stack
            (prometheus, loki, tempo, grafana)
```

## Agent Compatibility

Works with Hermes, Codex, Cursor, and any agent supporting the skill protocol. Sub-skills declare their own `whenToUse` triggers for automatic routing (e.g., "incident", "outage", "alert firing", "SLO breach").
