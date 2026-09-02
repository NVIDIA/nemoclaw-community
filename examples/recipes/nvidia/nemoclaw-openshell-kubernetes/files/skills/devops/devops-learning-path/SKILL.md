---
name: devops-learning-path
description: Build a scoped, hands-on DevOps learning plan using safe Linux, cloud, Kubernetes, SRE, CI/CD, Git, and security labs. Use when someone wants a practice roadmap, lab sequence, or project-based DevOps learning plan rather than production changes.
category: operations
risk: safe
source: original
date_added: "2026-07-27"
---

# DevOps Learning Path

Create a practical, evidence-based learning plan for the user's DevOps goal.
This skill plans learning work; it does not run labs, provision cloud resources,
or change a cluster unless the user explicitly requests a separate action.

Use [`references/lab-map.md`](references/lab-map.md) to select a verified,
direct resource for a goal. The map is a bounded routing aid, not an attempt
to reproduce the upstream catalog.

## When To Use

Use this skill when the user wants to:

- learn DevOps through hands-on work;
- create a Linux, cloud, Kubernetes, SRE, CI/CD, Git, or DevSecOps study plan;
- choose practice labs or projects for a specific job goal;
- turn available weekly time into measurable operational practice; or
- assess which foundations to learn before attempting a production task.

Do not use it as a substitute for `openshift-llm-deploy`, incident-response,
or a production runbook when the user wants an actual environment change.

## Guardrails

- Use only personal, sandbox, training, or explicitly authorized environments.
- Keep vulnerable applications, CTFs, and Kubernetes security exercises off
  corporate production networks and clusters.
- Never paste credentials, API tokens, kubeconfigs, or SSH private keys into a
  lab worksheet, repository, or chat transcript.
- For cloud exercises, start with a separate sandbox account or subscription,
  a low budget alert, a resource tag, and a deletion check at the end.
- Treat a lab as complete only when the user can show its evidence and explain
  its rollback or cleanup path.

## Intake

Gather these inputs before proposing a schedule. Infer only what is safe and
obvious; ask for the remaining values when they materially affect the plan.

| Input | Why it matters |
| --- | --- |
| Goal role or capability | Selects the right path: platform, cloud, SRE, CI/CD, or security. |
| Current baseline | Avoids starting Kubernetes before Linux, networking, and Git are usable. |
| Weekly time and target date | Determines whether the plan is a focused sprint or a multi-week sequence. |
| Available lab environment | Keeps exercises within approved local, cloud, or training boundaries. |
| Budget constraint | Prevents a cloud project from becoming an unexpected cost. |

When no answers are available, use the **four-week general foundation** below
and label the plan as an assumption-based starter.

## Select A Track

Choose one primary track and at most one supporting track. The source catalog
includes broader categories, but a focused sequence has a much higher chance
of producing reusable evidence.

| Track | Primary outcomes | Suggested lab category |
| --- | --- | --- |
| Linux foundations | CLI fluency, services, logs, networking, permissions | Linux and troubleshooting challenges |
| Cloud and IaC | IAM boundaries, networking, repeatable infrastructure, cleanup | Cloud, Terraform, and a small end-to-end project |
| Kubernetes platform | Containers, workload lifecycle, services, storage, debugging | Kubernetes and disposable lab environments |
| SRE and operations | Alert triage, incident diagnosis, runbooks, reliability thinking | SRE and troubleshooting challenges |
| CI/CD and Git | Branching, tests, artifact flow, deploy and rollback design | Git and CI/CD exercises |
| DevSecOps | Secrets hygiene, image and manifest risk, controlled vulnerability practice | Security labs in a disposable environment |

### Dependency Order

Use this order unless the user's baseline proves a prerequisite is already
solid:

1. Linux shell, files, processes, logs, networking, and Git.
2. Containers and a small service lifecycle.
3. CI/CD, infrastructure-as-code, and cloud cost/identity basics.
4. Kubernetes workload, service, storage, and troubleshooting practice.
5. SRE, security, and end-to-end capstone work.

For a Kubernetes or SRE target, keep Linux and Git as short verification
exercises rather than skipping them outright.

## Agent Routing

When a user selects a practice goal:

1. Read [`references/lab-map.md`](references/lab-map.md) and select one
   matching resource, not several competing courses.
2. State the source URL, the expected effort, and the isolation or cost
   boundary before the learner starts.
3. Use an existing local skill only for the complementary task below. Do not
   claim that it can sign in to, provision, or submit work to an external lab.
4. Require the learner's own evidence and cleanup record before moving to the
   next milestone.

| Learning work | Complementary local skill |
| --- | --- |
| Containerize or inspect a practice service | `docker-patterns` |
| Deploy a practice workload to an authorized disposable cluster | `kubernetes-deployment` |
| Diagnose a practice Kubernetes failure | `kubernetes-troubleshooting` |
| Work through an operational failure scenario | `devops-troubleshooter` |
| Turn an exercise outcome into an operational record | `runbook-creator` |

The external sites are learner-operated and often interactive. Do not create
accounts, accept terms, spend money, or run an external exercise on the
user's behalf without an explicit request and an authorized environment.

## Build The Plan

For every week or milestone, specify one outcome, one hands-on exercise, a
proof artifact, and an explicit cleanup step. Prefer exercises that use the
user's existing platform stack when it is authorized and disposable.

| Week | Outcome | Practice | Evidence | Cleanup or rollback |
| --- | --- | --- | --- | --- |
| 1 | Establish baseline | Linux and Git troubleshooting exercises | Command notes and a short diagnosis | Remove test files and revoke temporary access |
| 2 | Make delivery repeatable | Containerize a small service and add CI checks | Dockerfile, pipeline, test result | Delete local image and test artifacts |
| 3 | Operate a workload | Deploy to a disposable Kubernetes or cloud lab | Manifest/IaC, health check, rollback record | Destroy resources and confirm billing is zeroed |
| 4 | Demonstrate operational judgment | Diagnose a failure and write a short runbook | Incident timeline, fix, prevention | Revert fault injection and archive evidence |

Adapt rather than expand this table. For example, a CI/CD learner can spend
weeks 3 and 4 on pipeline promotion and rollback; a platform learner can split
Kubernetes into two weeks and add an SRE capstone.

## Resource Selection

The direct selection map is intentionally separate so an agent loads it only
when a learner asks for a resource. It maps the source catalog's links to
specific use cases and local companion skills without copying the catalog.

Do not claim that an external lab is free, supported, or currently available
without checking its current site. Each linked lab has its own terms, account,
and cost model.

## Evidence Standard

Ask the learner to retain a concise record for each completed exercise:

```text
Exercise:
Goal:
Environment and authorization boundary:
What changed:
Validation command or observable result:
Rollback or cleanup performed:
What I learned / next gap:
```

Evidence should demonstrate understanding, not merely that a tutorial command
ran. For incident practice, include the observed symptom, the diagnosis, the
reason the remediation worked, and one prevention or detection improvement.

## Completion Review

At the end of a plan, report:

1. Completed outcomes and evidence.
2. Remaining prerequisite gaps.
3. Labs blocked by access, budget, or authorization.
4. The next capstone, with its environment boundary and teardown criteria.

Use these status labels precisely:

- **Planned:** selected but not started.
- **In progress:** environment and exercise are active.
- **Validated:** expected behavior was demonstrated with evidence.
- **Cleaned up:** temporary resources and access were removed or recorded as
  intentionally retained.
- **Blocked:** the reason and required owner/action are known.

## Output Template

```markdown
## DevOps Learning Plan

**Goal:**
**Baseline:**
**Time available:**
**Environment boundary:**
**Budget limit:**

| Milestone | Hands-on task | Evidence | Safety and cleanup |
| --- | --- | --- | --- |
| 1 |  |  |  |
| 2 |  |  |  |
| 3 |  |  |  |
| 4 |  |  |  |

### Review gates
- [ ] Prerequisites demonstrated
- [ ] No credentials or production assets used
- [ ] Cleanup completed for every disposable resource
- [ ] Capstone evidence reviewed
```
