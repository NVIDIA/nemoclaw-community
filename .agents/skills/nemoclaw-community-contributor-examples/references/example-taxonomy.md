<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Example Taxonomy And Naming

This is the canonical placement and naming policy for content under
`examples/`.

## Principles

- Classify first by artifact type: recipe, demo, or tool.
- For recipes, classify second by contributor provenance.
- Encode stable navigation in paths. Keep mutable attributes such as maturity,
  supported versions, integrations, deployment status, industry, and program
  collections in documentation and catalog metadata.
- Use directory placement for discovery, not as a support-level claim.
- Keep each runnable example independently deployable. A documentation-only
  tutorial must identify its canonical source and state that it has no runtime
  deployment.

## Directory Structure

```text
examples/
├── recipes/
│   ├── nvidia/
│   ├── partners/<organization>/
│   └── community/
├── demos/
│   ├── field/
│   └── build-a-claw/
├── tools/
└── collections/
    ├── hackathon/README.md
    └── build-a-claw/README.md
```

The six category directories have index READMEs at `recipes/nvidia/`,
`recipes/partners/`, `recipes/community/`, `demos/field/`,
`demos/build-a-claw/`, and `tools/`.
Collection directories contain only their index README; examples remain in a
canonical category path. Git does not preserve empty directories, so an empty
category is represented by its index README.

## Classification

| Type | Use when | Do not use when |
| --- | --- | --- |
| `recipes` | The example is a complete, reusable agent workflow intended for adaptation. | It is primarily a presentation script, environment bootstrap, or development utility. |
| `demos/field` | The artifact is optimized for a bounded field demonstration on named hardware or software. | It is intended as a reusable enterprise workflow. |
| `demos/build-a-claw` | The artifact is a guided Build-a-Claw demonstration or tutorial. | It is a reusable workflow that belongs in a provenance-based recipe path. |
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

Record the one primary industry, any accepted cross-cutting collection, and an
optional upstream project in the standardized catalog block in the example's
root `README.md`.
Use the exact emoji-and-title values documented in
[`CONTRIBUTING.md`](../../../../CONTRIBUTING.md#catalog-metadata). Industry does
not change kind, provenance, support, or maturity. `Lifecycle` and `Reviewed`
are optional maintenance metadata; omission means an active example whose age
comes from committed activity.

Every example also declares NemoClaw, harness, and OpenShell values in that
table. They are fallbacks, not proof. The catalog confirms them only from the
small set of root runtime conventions documented in
[`CONTRIBUTING.md`](../../../../CONTRIBUTING.md#runtime-stack-discovery). An
exact reviewed NemoClaw release may supply its stock harness and OpenShell
versions. Custom layouts remain `Unconfirmed`, `Unpinned`, or `Unknown` until
standardized; these labels do not mean unsupported or broken.

`Hackathon` and `Build-a-Claw` are collections, not artifact kinds or
provenance. A collection entry that is a reusable workflow remains a recipe
under its NVIDIA, partner, or community provenance path. The corresponding
`examples/collections/` directories are indexes only; do not place examples
there or use a collection to erase contributor attribution.

Build-a-Claw demos and tutorials use `demos/build-a-claw/` and join the
Build-a-Claw collection automatically. Recipes opt in through their metadata.
The website presents both through one Build-a-Claw browse group without
changing their canonical artifact type, path, or provenance.

Set `Upstream` only when an example wraps, adapts, or extends a separate
canonical public project. Use an absolute HTTPS URL. Do not use it as a second
link to the example itself.

## Category And Collection Indexes

After optional license comments, each canonical category and collection index
README starts with its public H1 title and one concise description paragraph.
Those authored fields supply the catalog tile label and information tooltip.
The entire index must follow this standardized shape; no other sections are
permitted:

```markdown
## Examples

[Generated table or empty-state message.]
```

The build retains the authored title and description values while normalizing
the index and regenerating its inventory. Do not edit that inventory by hand.
Collection indexes group recipes by metadata without changing their canonical
paths.

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
documentation; each example's root README is its structured source of truth.

## Public Repository Boundary

NVIDIA-authored does not mean NVIDIA-internal. Public examples must use
placeholders, omit private tenant and workspace details, and contain no
internal-only links. Document private deployment overlays outside this public
repository.
