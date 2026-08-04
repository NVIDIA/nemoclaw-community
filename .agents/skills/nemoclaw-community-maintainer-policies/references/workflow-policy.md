<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Community Maintainer Workflow Policy

This package is the canonical source for maintainer metadata policy.

## Source Of Truth

1. Native GitHub Issue Type classifies issues as `Bug`, `Enhancement`, `Task`, `Documentation`, `Epic`, or `Initiative`.
2. `triage-instructions.md` defines how to evaluate issues and pull requests.
3. `label-taxonomy.md` and `label-taxonomy.json` define allowed labels and selection rules.
4. GitHub Project fields, when configured, own priority, effort, dates, and lifecycle status.
5. Labels own routing, immediate action queues, contribution signals, example publication classification, and pull request type.

Do not use labels as a second source of truth for Issue Type, priority,
lifecycle status, sprint, or resolution. Default to recommendation-only.
Metadata writes require explicit authorization for the named operation.

## Community Boundary

This repository does not inherit NemoClaw's Project 199 workflow, daily release
labels, release train, or Product Readiness Review process. Security-sensitive
routing uses `area: security`; potential vulnerabilities must follow
`SECURITY.md` instead of being characterized in public metadata.

## Contributor Eligibility

Contributor pull requests must keep every commit DCO-signed. Maintainers must
not merge a pull request with missing sign-off, unresolved review conversations,
or failed required checks.
