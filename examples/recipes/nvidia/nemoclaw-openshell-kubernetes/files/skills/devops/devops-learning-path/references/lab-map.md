# Lab Routing Map

Use one resource per milestone. The URLs below were selected from the source
catalog recorded in [`../SOURCE.md`](../SOURCE.md) and were checked on
2026-07-28. Confirm current requirements before beginning.

| Goal | Direct resource | Agent follow-up | Boundary |
| --- | --- | --- | --- |
| Linux administration baseline | [Linux Upskill Challenge](https://linuxupskillchallenge.org/) | Create an evidence checklist; do not access a host for the learner. | Use an owned sandbox host. |
| Linux, Docker, Kubernetes, CI/CD, or IaC diagnosis | [SadServers scenarios](https://sadservers.com/scenarios) or [iximiuz challenges](https://labs.iximiuz.com/challenges) | Use `devops-troubleshooter` to explain diagnosis and `runbook-creator` for evidence. | Work only inside the provider's scenario. |
| Infrastructure as code | [HashiCorp Terraform tutorials](https://developer.hashicorp.com/terraform/tutorials) | Use `cloud-devops` to review the proposed sandbox architecture. | Separate cloud account, budget alert, and destroy plan. |
| Cloud and CI/CD capstone | [Cloud Resume Challenge](https://cloudresumechallenge.dev/docs/the-challenge/) | Use `deployment-patterns` or `production-readiness` to review the design. | Review provider costs and delete all resources after validation. |
| Kubernetes internals | [Kubernetes The Hard Way](https://github.com/kelseyhightower/kubernetes-the-hard-way) | Use `kubernetes-deployment` only after the learner has a disposable lab. | It is a learning tutorial, not a production deployment recipe. |
| Interactive container or Kubernetes practice | [Killercoda](https://killercoda.com/) | Use `docker-patterns` or `kubernetes-troubleshooting` to explain the result. | Keep the exercise in the hosted training environment. |
| SRE practice | [SRE Bootcamp exercises](https://one2n.io/sre-bootcamp/sre-bootcamp-exercises) | Turn a completed scenario into a concise runbook with `runbook-creator`. | Do not reproduce injected failures in production. |
| CI/CD pipeline basics | [Jenkins Maven tutorial](https://www.jenkins.io/doc/tutorials/build-a-java-app-with-maven/) | Use `docker-patterns` for a containerized practice application. | Use a disposable repository and credentials. |
| Git branching baseline | [Learn Git Branching](https://learngitbranching.js.org/) | Have the learner explain the resulting history and add a small local exercise. | No production repository changes. |
| Web security practice | [OWASP Juice Shop](https://owasp.org/www-project-juice-shop/) | Document findings and remediation ideas; never target a real service. | Run only in an isolated, explicitly authorized environment. |

## Agent Decision Rules

- Prefer the lowest-cost, lowest-privilege resource that teaches the required
  outcome.
- Route real infrastructure requests to the applicable operations skill, not
  to an external training lab.
- Stop and request confirmation before creating cloud resources, accepting an
  external site's terms, or using any user credential.
- If a source URL is unavailable or its requirements have changed, report the
  blocker and offer the source catalog rather than inventing a replacement.
