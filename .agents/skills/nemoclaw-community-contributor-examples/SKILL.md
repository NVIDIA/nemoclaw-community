---
name: nemoclaw-community-contributor-examples
description: Guide NemoClaw Community contributors through classifying, naming, adding, moving, renaming, and reviewing repository examples. Use when work affects examples, recipes, partner contributions, field demos, launchables, developer tools, the example catalog, or example paths.
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Community Contributor Examples

Use this skill to keep the example catalog navigable as it grows without
changing an example's runtime or security boundaries accidentally.

## Workflow

1. Read [references/example-taxonomy.md](references/example-taxonomy.md).
   For issue and pull request metadata, also read the canonical
   [maintainer taxonomy](../nemoclaw-community-maintainer-policies/references/label-taxonomy.md).
2. Before drafting or reviewing a new top-level example README, follow the
   canonical [Example README Template](../../../CONTRIBUTING.md#example-readme-template).
   Treat it as the required information contract instead of copying the
   template into this skill.
3. Read the target example's README and nearby deployment documentation before
   classifying or naming it.
4. Select the artifact type first. For recipes, select contributor provenance
   second. Use an outcome-oriented leaf name.
5. When moving or renaming an existing example, also read
   [references/restructure-checklist.md](references/restructure-checklist.md)
   and inventory every repository reference before editing.
6. Preserve contributor attribution, deployment behavior, security policy,
   credential handling, teardown behavior, and Compose/Helm parity.
7. Update the public catalog, repository links, contribution commands, notices,
   submodule configuration, and external-document follow-ups in the same
   change.
8. Run the smallest relevant example checks, then the repository-wide checks
   required by `CONTRIBUTING.md`.

## Boundaries

- Treat directory placement as navigation, not a support or maturity promise.
- Do not classify provenance from technology usage alone. Require explicit
  attribution or repository history.
- Do not broaden egress, permissions, credential exposure, host access, or
  agent authority as part of a catalog change.
- Do not retain duplicate compatibility directories. Document path migrations
  and update callers.
- Base README commands, results, compatibility, support, security, and
  performance claims on repository evidence. Do not draft from an issue alone.
- Keep public drafts sanitized. Do not include secrets, internal links, tenant
  details, private paths, or nonpublic environment names. Use obvious
  placeholders for private values.
- Require a human contributor to review and correct coding-agent drafts before
  submission.
- Ask maintainers when ownership or artifact type remains ambiguous after
  inspecting the example.
