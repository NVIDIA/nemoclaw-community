<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Deployment topology

GitHub is the review control plane, not the durable advisor computer. It
dispatches an exact review request, supplies a step-scoped read token, queues
work, and retains the resulting artifact. Hermes memory, OpenShell state, and
the prepared runtime live on operator-controlled compute.

The recommended version-0.1 deployment is one dedicated self-hosted Linux
runner on a controlled existing VM, on-premises host, or dedicated VPS. A VPS
works but is not required. Prefer a private repository. Put the runner in the
repo-specific organization runner group named by the generated workflow, limit
that group to the intended repository, and restrict its workflow access to:

```text
OWNER/REPOSITORY/.github/workflows/nemoclaw-review-advisor.yml@refs/heads/DEFAULT_BRANCH
```

Use the fully qualified `refs/heads/...` form. This GitHub-side runner-group
policy is the authorization boundary that prevents a copy of the workflow
dispatched from another branch from claiming the sensitive runner. The
workflow's own default-branch `if` is defense in depth because branch-owned
workflow code cannot authorize itself. The one-command repository installer
derives the group name but cannot create or configure this organization
setting. Install the runner application as a service after the group policy is
in place. The host supplies:

- Docker and exact OpenShell `0.0.85`;
- a dedicated OpenShell gateway, inference provider/route, and advisor sandbox;
- the `self-hosted`, `linux`, and `nemoclaw` runner labels;
- private advisor lifecycle state and memory snapshots outside the checkout;
- host- or pipeline-side provider credentials that never enter review inputs or
  artifacts.

For host sizing, Docker same-account access, loopback exposure, and headless
setup, follow the tagged NemoClaw
[headless deployment guide](https://github.com/NVIDIA/NemoClaw/blob/v0.0.92/docs/deployment/deploy-to-headless-server.mdx).
Its recommended baseline is 4 or more vCPUs, 16 GB RAM, and 40 GB disk
(minimum 4 vCPUs, 8 GB RAM, and 20 GB disk). Treat
`runtime/scripts/verify.sh` success as advisor readiness; process presence alone
is not a readiness signal.

```text
GitHub workflow dispatch, token, queue, artifacts
                         │
                         ▼
dedicated private self-hosted Linux runner service
  ├── trusted workflow checkout
  ├── per-run temporary PR Git object store
  ├── OpenShell dedicated gateway + provider route
  │     └── repository-specific Hermes sandbox + Nemotron Ultra
  └── private install-scoped state/snapshots outside checkout
```

Keep the installed workflow manual and artifact-only, as generated. An
automatic trusted-event variant is appropriate only where the repository and
event policy guarantee trusted callers, normally in a private repository. Do
not attach a privileged persistent runner to a workflow that checks out or
executes code from untrusted public-fork pull requests. The generated workflow
does neither: it checks out trusted default-branch runtime code, treats the PR
as bounded data in a temporary repository, and removes that repository after
the artifact-upload attempt.

A public repository is not categorically unsupported, but it needs the same
dedicated runner group restricted to the exact default-branch workflow ref.
Audit every workflow and the effective runner-group policy to ensure no
fork-triggered or branch-owned job can target that runner. The generated
workflow is manual, carries no provider credential, and never executes PR
code. Its in-file branch check is not a substitute for the GitHub-side group
restriction. Another workflow that can target the same persistent runner could
still execute untrusted code, access Docker or host state, and invalidate all
of those guarantees.

## Reboot and liveness

Register the Actions runner as an operating-system service. Bring up the
advisor separately after Docker and the dedicated OpenShell gateway are
available by invoking the idempotent `bring-up.sh` during trusted machine
provisioning. After a reboot, a trusted operator or provisioning system runs
`bring-up.sh`, then `scripts/verify.sh`, before dispatching reviews.

Do not install an unofficial NemoClaw, OpenShell, Hermes, or advisor service
unit as a substitute for this recovery step. The NemoClaw `v0.0.92`
[headless deployment guide](https://github.com/NVIDIA/NemoClaw/blob/v0.0.92/docs/deployment/deploy-to-headless-server.mdx)
documents post-reboot recovery as manual. The generated review workflow
intentionally assumes the appliance is already healthy and carries no provider
credential. Do not turn a workflow that processes untrusted review data into a
credentialed infrastructure provisioner. The installer does not register the
Actions runner, configure reboot persistence, or mutate host service
management.

GitHub-hosted runners are ephemeral cold-start machines. They can run a
stateless variant, but each job must install Docker/OpenShell/runtime state and
cannot retain Hermes memory locally. Durable memory would require an external
protected snapshot store plus restoration of the same bound install,
repository, and sandbox identity. That store also needs trusted
signature/MAC/KMS-backed authenticity and concurrency control; the snapshot's
plain SHA-256 manifest detects corruption and mixups but is not an authenticity
signature. Actions artifacts and caches remain review-output or backup
transport, not the canonical mutable memory store. That operational cost makes
a dedicated self-hosted runner the simpler version-0.1 appliance.

Actions Runner Controller (ARC) is a later scale-out option, not the default
topology. Before scaling replicas, define provider-route ownership, per-repo
serialization, authenticated external snapshot custody, optimistic locking or
another concurrency protocol, and memory consistency. Likewise, a future
GitHub App or webhook can authenticate and schedule reviews, but it is
control-plane integration; it does not host Hermes, OpenShell, or durable
memory.

GitHub's official runner documentation covers
[GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[self-hosted runner concepts](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners),
[adding a self-hosted runner](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners),
[installing the runner as a service](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application),
[self-hosted runner security and operations](https://docs.github.com/en/actions/reference/runners/self-hosted-runners),
[runner-group workflow access](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access),
and
[deploying ARC runner scale sets](https://docs.github.com/en/actions/how-tos/manage-runners/use-actions-runner-controller/deploy-runner-scale-sets).
