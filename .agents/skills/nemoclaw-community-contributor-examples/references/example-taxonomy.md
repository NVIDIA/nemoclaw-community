<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Example Taxonomy And Naming

This is the canonical placement and naming policy for content under
`examples/`.

## Principles

- Classify first by artifact type: recipe, demo, launchable, or tool.
- For recipes, classify second by contributor provenance.
- Encode stable navigation in paths. Keep mutable attributes such as maturity,
  supported versions, integrations, deployment status, industry, and program
  collections in documentation and catalog metadata.
- Use directory placement for discovery, not as a support-level claim.
- Keep each example independently deployable.

## Directory Structure

```text
examples/
├── recipes/
│   ├── nvidia/
│   ├── partners/<organization>/
│   └── community/
├── demos/
│   └── field/
├── launchables/<environment>/
└── tools/
```

Git does not preserve empty directories. Create a category when its first
example lands; document reserved categories in `examples/README.md`.

## Classification

| Type | Use when | Do not use when |
| --- | --- | --- |
| `recipes` | The example is a complete, reusable agent workflow intended for adaptation. | It is primarily a presentation script, environment bootstrap, or development utility. |
| `demos/field` | The artifact is optimized for a bounded field demonstration on named hardware or software. | It is intended as a reusable enterprise workflow. |
| `launchables` | The artifact's primary purpose is provisioning or onboarding in a specific environment. | The environment is only one deployment option for a broader recipe. |
| `tools` | The artifact is a standalone developer or evaluation utility rather than a deployed agent blueprint. | It produces the end-user agent workflow itself. |

## Recipe Provenance

| Path | Requirement |
| --- | --- |
| `recipes/nvidia/` | Authored or maintained by NVIDIA and allowed to include documented NVIDIA-specific assumptions. |
| `recipes/partners/<organization>/` | Explicitly contributed by the named external organization. Preserve its attribution. |
| `recipes/community/` | Contributed independently without formal organizational provenance. |

Using an NVIDIA model, GPU, SDK, or service does not by itself make a recipe an
NVIDIA recipe. Determine provenance from explicit README attribution or
repository history.

## Discovery Metadata

Directory placement answers what an artifact is and, for a recipe, where its
contribution came from. It does not encode every way a reader may discover the
example.

Record the one primary industry and any accepted cross-cutting collection in
[`examples/catalog.json`](../../../../examples/catalog.json). Use the exact
industry values documented in
[`CONTRIBUTING.md`](../../../../CONTRIBUTING.md#catalog-metadata). Industry
does not change kind, provenance, support, or maturity.

`hackathon` is a collection, not an artifact kind or provenance. A hackathon
entry that is a reusable workflow remains a recipe under its NVIDIA, partner,
or community provenance path. Do not create a `hackathon` path or use the
collection to erase contributor attribution.

## Naming

- Use lowercase kebab-case.
- Name the outcome, operational role, or scenario.
- Do not repeat `recipe`, `demo`, `nemoclaw`, or the contributor when the parent
  path already supplies that context.
- Include a platform, harness, or hardware name only when it materially defines
  portability or the established example identity.
- Do not put versions, lifecycle states, or temporary initiatives in paths.
- Avoid narrow task labels when an example performs a broader workflow.

Prefer `developer-community-chief-of-staff` over
`personal-community-sentiment-triage`: the former describes the workflow's
coordination and intelligence outcome rather than one analysis technique.

## Current Catalog

Use the generated [`examples/README.md`](../../../../examples/README.md) for
the current example-to-path mapping. Do not duplicate that inventory in policy
documentation; [`examples/catalog.json`](../../../../examples/catalog.json) is
the structured source of truth.

## Public Repository Boundary

NVIDIA-authored does not mean NVIDIA-internal. Public examples must use
placeholders, omit private tenant and workspace details, and contain no
internal-only links. Document private deployment overlays outside this public
repository.
