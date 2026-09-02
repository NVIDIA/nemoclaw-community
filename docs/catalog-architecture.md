<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Example Catalog Architecture

The NemoClaw Community catalog is a generated static site hosted by GitHub
Pages. It has no application server, database, remote JavaScript, or package
runtime. One pinned, pure-Python Markdown package compiles example READMEs into
static detail pages. A pinned, hash-verified Mermaid Tiny browser asset is
downloaded at build time and served locally only on pages that contain diagrams.

## Source And Outputs

```text
example root READMEs ──┬─> examples/README.md
                       ├─> category and collection README inventories
                       ├─> _site/index.html
                       ├─> _site/examples/<canonical-path>/index.html
                       ├─> _site/catalog.json
                       └─> _site/llms.txt
category and collection
index README titles ───┬─> browse labels and information tooltips
and descriptions       └─> category and collection data in catalog.json
site/*.template.html ──┬─> generated HTML
site/styles.css ───────┼─> _site/styles.css
site/catalog.mjs ──────┼─> _site/catalog.mjs
site/diagrams.mjs ─────┼─> _site/diagrams.mjs
Mermaid Tiny cache ────┴─> _site/assets/vendor/mermaid.tiny.js
README stack rows plus
standard runtime Dockerfiles ─> stack values and verification in HTML, JSON,
                               and llms.txt
Git history, Lifecycle,
and Reviewed ──────────────> computed maintenance status
```

The standardized catalog block immediately after the level-one title in each
example's root `README.md` is the canonical metadata source. A final
`Catalog Metadata` section remains supported as a legacy placement.
[`scripts/build_catalog.py`](../scripts/build_catalog.py) discovers those
READMEs from the repository taxonomy, validates their title, required
`Description` table row, industry emoji and title, requirements, and
conditional fields, then derives artifact kind and recipe provenance from each
path. Optional `Lifecycle` and `Reviewed` fields inform maintenance status; an
optional `Upstream` field identifies a separate canonical public project that
the example adapts. The required NemoClaw, harness, and OpenShell rows provide
a readable fallback while standard runtime files provide confirmation.

Each of the five canonical categories and two collection views has an index
README. Its H1 and opening description are the authored source for the browse
label and information tooltip. The build retains those values while rewriting
each index into its standardized shape and regenerating the inventory inside
the `## Examples` section. No other index sections are permitted. Collection
directories are indexes only; they never contain examples. The ignored
`_site/` directory is disposable; do not edit it directly.

The generated HTML contains every example card. The local JavaScript module
filters those cards in the browser, so the full category-organized catalog
remains readable when JavaScript is unavailable. GitHub Pages only serves the
generated files.

Each card links to a static detail page. The build extracts the source README
title, compiles headings, tables, lists, links, code, and images, and renders
the result inside the shared site theme. Detail pages without Mermaid remain
script-free. Pages with supported Mermaid fences load the pinned local Tiny
runtime and progressively replace each fence with a themed diagram. The
original source stays in an expandable disclosure and is the no-JavaScript or
render-error fallback.

The README compiler sanitizes its HTML output. Same-page heading fragments stay
local, links to another catalog README use its local detail route, and other
repository files or directories link to GitHub. Only referenced local images
in GIF, JPEG, PNG, or WebP format are copied into `_site/`, with type, size,
path, and symlink checks. SVG images are rejected because Pages would otherwise
serve contributed active documents from the site origin. Remote README images
become outbound links instead of third-party page resources.

Mermaid publication uses a deliberately narrow subset: flowcharts, graphs,
sequence diagrams, and state diagrams. The build caps source size and diagram
count and rejects configuration, click handlers, active HTML, image/icon
shapes, CSS imports, and CSS resource URLs. Rendering uses Mermaid's
sandbox security level. The catalog then validates the generated SVG,
places it in a permissionless `srcdoc` iframe, and applies parent and iframe
Content Security Policies. The parent policy blocks outbound connections and
nonlocal resources. The iframe policy blocks scripts and network-loaded
resources. The runtime bundle is version pinned, SHA-256 verified before
publication, and never loaded from a CDN by a reader's browser.

## Independent Discovery Dimensions

The catalog keeps these concepts separate:

- `kind` is `recipe`, `demo`, or `tool` and comes from the canonical path.
- `provenance` is `nvidia`, `partner`, or `community`, applies only to recipes,
  and also comes from the canonical path.
- `industry` is one required controlled emoji-and-title value on every example,
  independent of kind and provenance.
- `lifecycle` is an optional authored value: `Active` or `Deprecated`.
  Omission means `Active`; it never belongs in an example path.
- `reviewed` is an optional focused maintenance-review date, not runtime
  verification evidence.
- `stack` merges required README declarations with a small static check of
  standardized runtime files.
- `collection` is an optional cross-cutting recipe discovery field.
  `Hackathon` and `Build-a-Claw` are collections; neither replaces kind,
  provenance, canonical path, or contributor attribution.

The build rejects unknown taxonomy roots, unsafe or invalid example paths,
canonical example directories without a root README, malformed metadata
blocks, duplicate titles, and values outside the controlled vocabulary.

## Static Stack Discovery

Every README declares `NemoClaw`, `Harness`, and `OpenShell`. The builder then
looks for matching values only in root `Dockerfile*` or
`agents/*/Dockerfile*` files. It recognizes a short list of conventional
variables documented in `CONTRIBUTING.md`; nested and custom layouts use the
README fallback until standardized.

The checked-in `scripts/nemoclaw-release-contracts.json` maps reviewed exact
NemoClaw tags and commits to their stock harness matrix and OpenShell version.
The builder can infer those values once it finds an exact release and selected
harness. Contract harness values use installed CLI/package versions. Explicit
implementation pins take precedence and must agree with the README.

The final state is `Confirmed`, `Unconfirmed`, `Unpinned`, `Unknown`,
`Conflict`, or `N/A`. This is a version-evidence statement, not a support,
quality, or runtime-health claim. Catalog builds never fetch release metadata,
and model discovery is out of scope.

## Computed Maintenance Status

Contributors may author `Lifecycle` and a focused `Reviewed` date, but not the
public status. The effective activity date is the latest committed change
anywhere under the example or a later review. This is deliberately a
repository-activity heuristic: documentation and asset changes count as well
as runtime changes. The age-only bands are `Current` through
day 29, `Review soon` through day 59, `Review due` through day 119, `Review
overdue` through day 239, and `Review critical` from day 240. An authored
`Deprecated` lifecycle applies immediately and is the only status hidden by
the default catalog view. Computed maintenance never edits the README.
Thresholds are maintained in `scripts/catalog-maintenance.json`, and the
scheduled Pages workflow refreshes them daily. The build requires full Git
history; a newly added, uncommitted example temporarily uses the build date for
local preview. Maintenance status is independent of stack verification and is
not a support or runtime-health claim.

## Browser Search Contract

Catalog state is encoded in the URL so a filtered view can be copied,
bookmarked, or created by another program:

| Parameter | Values | Behavior |
| --- | --- | --- |
| `q` | Plain text | Case-insensitive whitespace-token AND search across title, description, requirements, category and provenance display text, industry, lifecycle, maintenance status, stack values and verification, contributor, and collections. |
| `view` | `category` or `industry` | Selects which discovery dimension is active. The default is `category`. |
| `category` | `all`, `nvidia-recipes`, `partner-recipes`, `community-recipes`, `nvidia-field-demos`, `developer-tools`, `hackathon-recipes`, or `build-a-claw-recipes` | Applies in category view. The final two values select recipes carrying the matching collection. |
| `industry` | `all` or an industry ID published in `catalog.json` | Applies in industry view. |
| `maintenance` | `maintained`, `all`, `current`, `review-soon`, `review-due`, `review-overdue`, `review-critical`, or `deprecated` | Applies independently of the active browse view. `maintained` includes every status except explicit deprecation. |

Examples:

```text
https://nvidia.github.io/nemoclaw-community/?q=payment&view=industry&industry=financial-services
https://nvidia.github.io/nemoclaw-community/?q=slack&category=nvidia-recipes
```

Unknown values are removed and replaced with defaults. Search typing updates
the current history entry; deliberate view and filter changes create history
entries, so browser Back and Forward restore prior views. Existing category
and example fragments for the supported taxonomy remain valid.

## Machine-Readable Catalog

[`https://nvidia.github.io/nemoclaw-community/catalog.json`](https://nvidia.github.io/nemoclaw-community/catalog.json)
publishes a deterministic JSON index containing:

- category IDs, labels, descriptions, kinds, provenance, and counts;
- every allowed industry ID, label, emoji, and current count;
- collection IDs, labels, descriptions, and counts;
- each example's title, description, category, kind, recipe provenance,
  industry, lifecycle, optional reviewed date, NemoClaw, harness, and OpenShell
  facts, stack verification and evidence paths, computed maintenance status,
  contributor when applicable, collections, requirements, optional upstream
  project URL, source path, source guide URL, and local detail URL.

This is a static index rather than a server-side query API. A program can fetch
it once and apply its own filters, or construct a browser URL using the query
contract above.

## Agent-Oriented Text Index

[`https://nvidia.github.io/nemoclaw-community/llms.txt`](https://nvidia.github.io/nemoclaw-community/llms.txt)
publishes the catalog overview, filter guidance, category and collection
fields, and one concise record for every example. Each record includes the
example's category, industry, requirements, lifecycle, NemoClaw, harness, and
OpenShell facts, stack verification, maintenance status, detail page, source
guide, collections, and optional upstream project.

The build creates `llms.txt` directly from the same validated README data used
for `catalog.json`; it is a second generated representation, not a metadata
source or a file contributors edit. Programs that need typed fields and counts
should continue to use `catalog.json`.

## Update And Verify

After changing an example README catalog block or a consumed runtime stack
source, validate the inputs, then regenerate the committed Markdown catalog
and local site:

```bash
python3 scripts/build_catalog.py --validate-metadata
python3 -m pip install --require-hashes -r scripts/catalog-requirements.txt
python3 scripts/fetch_catalog_assets.py
python3 scripts/build_catalog.py --write
```

Run the same checks used by the Pages workflow:

```bash
python3 scripts/build_catalog.py --check
python3 -m unittest \
  scripts.tests.test_build_catalog \
  scripts.tests.test_catalog_maintenance \
  scripts.tests.test_example_stack_facts
node --test scripts/tests/catalog.test.mjs
```

For local browser verification, follow the
[`catalog-deployment.md`](catalog-deployment.md#build-locally) instructions.
