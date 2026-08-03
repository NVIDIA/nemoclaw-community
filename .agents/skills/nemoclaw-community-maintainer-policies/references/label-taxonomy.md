<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Community Label Taxonomy

Status: canonical maintainer policy.

Use a label only when it changes an action, route, or report. The adjacent JSON
file is the machine-readable registry of names, descriptions, colors, and
compatibility rules.

## Native Fields Before Labels

Use native GitHub Issue Type for issue classification:

- `Bug`
- `Enhancement`
- `Task`
- `Documentation`
- `Epic`
- `Initiative`

Do not apply `bug`, `enhancement`, or `documentation` as issue-type labels.

## Pull Request Type

Apply exactly one type label to a review-ready pull request:

| Label | Use when |
| --- | --- |
| `bug-fix` | The pull request primarily fixes broken behavior. |
| `feature` | The pull request adds or expands user-visible capability. |
| `refactor` | The pull request restructures code without intended behavior change. |
| `chore` | The pull request changes docs, CI, dependencies, packaging, policy, or maintenance. |

Conventional title evidence maps `fix` to `bug-fix`, `feat` to `feature`, and
`refactor` to `refactor`. Treat title prefixes as evidence, not proof.

## Workflow Queues

`needs:*` labels identify an immediate action. Remove them when the action is
complete. They do not represent lifecycle status.

| Label | Use when |
| --- | --- |
| `needs: triage` | An issue or pull request has not received initial classification. |
| `needs: info` | Missing author information blocks progress. |
| `needs: design` | Product or architecture direction is required. |
| `needs: rebase` | Conflicts or stale base block review. |
| `needs: unblock` | A dependency or decision blocks progress. |
| `needs: cleanup-review` | Stale, superseded, competing, or cleanup-candidate work needs maintainer judgment. |

Do not create `needs: review`; use the repository's Project status when one is
configured.

## Community Contribution Signals

| Label | Use when |
| --- | --- |
| `good first issue` | The work is small, clear, safe, and suitable for a new contributor. |
| `help wanted` | Maintainers welcome an external contribution. |

## Routing Areas

Use the smallest set that routes the next action. Prefer the primary review
surface instead of labeling every concept mentioned by an item.

| Label | Description |
| --- | --- |
| `area: architecture` | Architecture, design debt, major refactors, or maintainability. |
| `area: ci` | CI workflows, checks, automation, or GitHub Actions. |
| `area: cli` | Command-line interfaces, flags, terminal UX, or output. |
| `area: docs` | Documentation, examples, guides, or docs build. |
| `area: e2e` | End-to-end tests or validation infrastructure. |
| `area: inference` | Model execution, serving, selection, or generated output. |
| `area: install` | Install, setup, prerequisites, teardown, or uninstall. |
| `area: integrations` | External apps, tools, bridges, APIs, or source ETLs. |
| `area: local-models` | Local model runtimes, downloads, launch, or connectivity. |
| `area: messaging` | Message delivery, channels, manifests, or channel lifecycle. |
| `area: networking` | DNS, proxy, TLS, ports, host aliases, or connectivity. |
| `area: observability` | Logging, metrics, tracing, telemetry, or diagnostics. |
| `area: onboarding` | First-run flow, provider setup, or sandbox launch. |
| `area: packaging` | Packages, images, registries, installers, or distribution. |
| `area: performance` | Latency, throughput, resource use, benchmarks, or scaling. |
| `area: policy` | Network policy, egress, permissions, or sandbox policy. |
| `area: project-management` | Taxonomy, triage, workflow, roadmap, or project process. |
| `area: providers` | Inference-provider integration, configuration, or selection. |
| `area: routing` | Request routing, fallback, or model selection. |
| `area: sandbox` | OpenShell sandbox lifecycle, runtime, configuration, or recovery. |
| `area: security` | Security controls, permissions, secrets, or hardening. |
| `area: skills` | Agent skills, prompts, behaviors, or skill packaging. |
| `area: ui` | Web UI, terminal display, visual layout, or UX behavior. |

Use `area: security`, not a supplemental public `security` label. Potential
vulnerabilities follow `SECURITY.md`.

## Platforms

Apply a platform label only when the platform changes routing or is likely
causal. Do not infer it from a test environment alone.

- `platform: arm64`
- `platform: brev`
- `platform: container`
- `platform: dgx-spark`
- `platform: dgx-station`
- `platform: jetson`
- `platform: k8s`
- `platform: linux`
- `platform: macos`
- `platform: ubuntu`
- `platform: windows`
- `platform: wsl`

## Providers

Use `area: providers` with a provider label when provider-specific routing is
useful.

- `provider: anthropic`
- `provider: nvidia`
- `provider: ollama`
- `provider: openai`
- `provider: vllm`

## Integrations

Use `area: integrations` or a more specific primary area. Add a named
integration label only when the integration itself is the affected subject.

- `integration: dcode`
- `integration: hermes`
- `integration: openclaw`
- `integration: slack`
- `integration: telegram`

Do not create a durable label for every service used by one example. Add a new
integration value only after repeated routing or reporting demand.

## Example Publication

Example labels describe stable catalog placement. They do not claim support or
maturity.

| Label | Use when |
| --- | --- |
| `example: recipe` | A complete reusable agent workflow is proposed or published. |
| `example: demo` | A bounded field demonstration is proposed or published. |
| `example: launchable` | Environment provisioning or onboarding is proposed or published. |
| `example: tool` | A standalone developer or evaluation utility is proposed or published. |

Apply at most one `example:*` label unless a coordinated catalog migration
genuinely spans kinds.

## Recipe Provenance

Apply provenance only to recipes and only from explicit attribution or
repository history.

| Label | Use when |
| --- | --- |
| `provenance: nvidia` | NVIDIA authors or maintains the recipe. |
| `provenance: partner` | A named external organization explicitly contributes the recipe. |
| `provenance: community` | The recipe is contributed independently without formal organizational provenance. |

Technology usage alone does not establish provenance.

## Unknown And Legacy Labels

Do not create or apply a label absent from the machine-readable taxonomy.
Report legacy labels in an audit before cleanup. Migrate open issues to native
Issue Type, then remove legacy type labels. Do not bulk relabel historical
closed items or delete labels without a separately approved operation.
