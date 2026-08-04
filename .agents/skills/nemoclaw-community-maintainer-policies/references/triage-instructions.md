<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Community Triage Instructions

Read `label-taxonomy.md` and `label-taxonomy.json` before suggesting labels.
Use evidence from the title, body, linked issue, changed files, CI, and public
catalog. Prefer no label over a guess, and use the smallest set that changes
routing, action, or reporting.

## Issues

1. Set native Issue Type.
2. Add zero to two routing labels when the affected surface is clear.
3. Add platform, provider, or integration labels only from direct evidence.
4. Add `needs:*` only when a blocking action queue is required.
5. For a new example, add one `example:*` label. Add one `provenance:*` label only for recipes with explicit provenance.
6. Ask for missing actionable details without inventing metadata.

Do not add `bug`, `enhancement`, or `documentation`; use native Issue Type.
`needs: triage` is an intake signal and should be removed after classification.

## Pull Requests

1. Identify whether the pull request is draft, conflicted, blocked, or review-ready.
2. Apply one PR type label when evidence supports it: `bug-fix`, `feature`, `refactor`, or `chore`.
3. Add routing labels based on the primary review surface.
4. Apply example-kind and recipe-provenance labels to new-example or publication pull requests.
5. Add `needs: rebase`, `needs: info`, `needs: design`, or `needs: unblock` only when that action blocks review.

Map `fix` to `bug-fix`, `feat` to `feature`, and `refactor` to `refactor`.
Map `chore`, docs-only, CI-only, dependency, packaging, and policy-maintenance
changes to `chore`.

## Security Handling

Use `area: security` when security controls, permissions, credentials, or
hardening are the primary review surface. Do not add a public `security` label.
Do not confirm exploitability in public. Route potential vulnerabilities to
the private process in `SECURITY.md`.

## Write Safety

Show a dry run before changing Issue Type, labels, titles, or other metadata
unless the user has explicitly authorized the exact operation. Never create or
delete labels as an incidental side effect of triage.
