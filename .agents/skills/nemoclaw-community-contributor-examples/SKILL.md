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
2. Read the target example's README and nearby deployment documentation before
   classifying or naming it.
3. Select the artifact type first. For recipes, select contributor provenance
   second. Use an outcome-oriented leaf name.
4. When moving or renaming an existing example, also read
   [references/restructure-checklist.md](references/restructure-checklist.md)
   and inventory every repository reference before editing.
5. Preserve contributor attribution, deployment behavior, security policy,
   credential handling, teardown behavior, and Compose/Helm parity.
6. Update the public catalog, repository links, contribution commands, notices,
   submodule configuration, and external-document follow-ups in the same
   change.
7. Run the smallest relevant example checks, then the repository-wide checks
   required by `CONTRIBUTING.md`.

## Boundaries

- Treat directory placement as navigation, not a support or maturity promise.
- Do not classify provenance from technology usage alone. Require explicit
  attribution or repository history.
- Do not broaden egress, permissions, credential exposure, host access, or
  agent authority as part of a catalog change.
- Do not retain duplicate compatibility directories. Document path migrations
  and update callers.
- Ask maintainers when ownership or artifact type remains ambiguous after
  inspecting the example.
