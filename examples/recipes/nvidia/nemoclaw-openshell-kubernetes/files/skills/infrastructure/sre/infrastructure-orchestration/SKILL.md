---
name: sre-infrastructure-orchestration
description: Coordinate infrastructure, platform, SRE, deployment, and workflow work without assuming privileges or making unapproved production changes.
---

# Infrastructure Orchestration

Use this skill when a request spans infrastructure operations, delivery, and
multiple engineering roles.

1. Split the work into observable outcomes: architecture, deployment,
   security, reliability, networking, data, and verification.
2. Assign a clear owner and acceptance check to each outcome. Keep a single
   change owner for production actions.
3. Prefer small, reversible changes. Require an explicit rollout and rollback
   plan before a production change.
4. Coordinate through artifacts: a brief plan, evidence links, a change record,
   and a final verification result.
5. Escalate uncertainty rather than inventing status, permissions, or command
   output.

This is original Hermes guidance informed by the requested infrastructure and
orchestration role directories from `rohitg00/awesome-claude-code-toolkit`.
