<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Example Restructure Checklist

Use this checklist for every example move or rename.

## Before Moving

- Read the example README and its verification guide.
- Confirm artifact type and, for recipes, contributor provenance.
- Inventory tracked files, nested repositories, Git submodules, generated
  artifacts, and deployment variants.
- Search the entire repository for the old path, display name, and persistent
  runtime identifiers.
- Separate user-facing names from compatibility-sensitive identifiers such as
  telemetry project names, service names, image tags, and storage prefixes.

## Apply The Move

- Use Git-aware moves so history remains discoverable.
- Preserve the internal layout of an independently deployable example.
- Update `.gitmodules` when a moved tree contains a submodule.
- Update relative links, clone and `cd` commands, environment examples,
  catalog entries, contribution instructions, ownership rules, and
  `THIRD-PARTY-NOTICES`.
- Preserve explicit contributor attribution.
- Do not mix runtime, permission, or dependency changes into a path-only
  migration.

## Compatibility

- Document old-to-new paths in the pull request.
- Do not leave duplicate example directories as redirects.
- State which persistent identifiers may retain the old name.
- Identify external documentation and downstream automation that must be
  updated after merge.
- Call out migration commands for existing clones when submodules move.

## Verification

- Search for obsolete paths after the move.
- Check relative documentation links from their new locations.
- Run repository-wide license and whitespace checks.
- Run the smallest relevant syntax, unit, and configuration checks for every
  moved example.
- For submodules, verify both a fresh recursive clone and synchronization from
  an existing clone.
- Do not start live services or contact external systems unless the task
  explicitly requires it and suitable credentials are available.
