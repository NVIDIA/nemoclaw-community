<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Bundled Skill Source Notices

These skill trees were imported from the legacy `hermes-webui-openshell`
chart's local `files/skills/{devops,infrastructure}` directories. Files that
were unavailable as OneDrive placeholders were restored byte-for-byte from
the corresponding tracked paths in `agudanv/hermes-nemo-skills` main commit
`8d660af`.

The curated source repository organizes material by function and records these
origins:

- DevOps, automation, and technical documentation material includes requested
  `flight505-*`, `rohit-toolkit`, and `smartem-devops` sources.
- Docker and Kubernetes fundamentals include `clouddrove/claude-skills` at
  revision `77a73aa60287564bd259c72c8940ab42350bc763`.
- Kubernetes platform automation includes `HermeticOrmus/hermetic-academy` at
  revision `e9be3161c2ce89d1f916fdc66f7a5c29e05cf7d7`.
- Argo CD and observability helpers include
  `julianobarbosa/claude-code-skills` at revision
  `ac701ada10169dc2a7008cb3f8279acdfb3846f5`.
- Kubernetes failure-analysis guidance includes
  `LukasNiessen/kubernetes-skill` at revision
  `a34b06ac7df4e372149554af9d107acdef1d91e8`.

Accompanying license files remain beside their source material. Skills are
instructions and optional helpers; the chart does not execute them during
installation. OpenShell policy and the chart's authenticated API proxies remain
the runtime capability boundaries.

The release bundle includes every reviewed skill entrypoint and its executable
scripts, templates, tools, workflows, and runtime resources. It excludes
auxiliary documentation/examples, the host-level `manage-skills` prompt,
SkillSpector, and dynamic installers. During deterministic packaging, the
builder injects a uniform NemoClaw safety contract after each skill's YAML
frontmatter; this does not rewrite the reviewable source files.
