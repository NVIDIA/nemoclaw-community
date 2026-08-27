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
                       ├─> _site/index.html
                       ├─> _site/examples/<canonical-path>/index.html
                       └─> _site/catalog.json
site/*.template.html ──┬─> generated HTML
site/styles.css ───────┼─> _site/styles.css
site/catalog.mjs ──────┼─> _site/catalog.mjs
site/diagrams.mjs ─────┼─> _site/diagrams.mjs
Mermaid Tiny cache ────┴─> _site/assets/vendor/mermaid.tiny.js
```

The standardized catalog block at the top of each example's root `README.md` is
the canonical metadata source. [`scripts/build_catalog.py`](../scripts/build_catalog.py)
discovers those READMEs from the repository taxonomy, validates their title,
description, industry emoji and title, requirements, and conditional fields,
then derives artifact kind and recipe provenance from each path. The ignored
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

- `kind` is `recipe`, `demo`, `launchable`, or `tool` and comes from the
  canonical path.
- `provenance` is `nvidia`, `partner`, or `community`, applies only to recipes,
  and also comes from the canonical path.
- `industry` is one required controlled emoji-and-title value on every example,
  independent of kind and provenance.
- `collection` is an optional cross-cutting discovery field. `Hackathon` is a
  collection; it does not replace kind, provenance, or contributor attribution.

The build rejects unknown taxonomy roots, unsafe or invalid example paths,
canonical example directories without a root README, malformed metadata
blocks, duplicate titles, and values outside the controlled vocabulary.

## Browser Search Contract

Catalog state is encoded in the URL so a filtered view can be copied,
bookmarked, or created by another program:

| Parameter | Values | Behavior |
| --- | --- | --- |
| `q` | Plain text | Case-insensitive whitespace-token AND search across title, description, requirements, category and provenance display text, industry, contributor, environment, and collections. |
| `view` | `category` or `industry` | Selects which discovery dimension is active. The default is `category`. |
| `category` | `all`, `nvidia-recipes`, `partner-recipes`, `community-recipes`, `hackathon-recipes`, `nvidia-field-demos`, `launchables`, or `developer-tools` | Applies in category view. `hackathon-recipes` selects recipes carrying the `hackathon` collection. |
| `industry` | `all` or an industry ID published in `catalog.json` | Applies in industry view. |

Examples:

```text
https://nvidia.github.io/nemoclaw-community/?q=payment&view=industry&industry=financial-services
https://nvidia.github.io/nemoclaw-community/?q=slack&category=nvidia-recipes
```

Unknown values are removed and replaced with defaults. Search typing updates
the current history entry; deliberate view and filter changes create history
entries, so browser Back and Forward restore prior views. Existing category
and example fragments remain valid.

## Machine-Readable Catalog

[`https://nvidia.github.io/nemoclaw-community/catalog.json`](https://nvidia.github.io/nemoclaw-community/catalog.json)
publishes a deterministic JSON index containing:

- category IDs, labels, kinds, provenance, and counts;
- every allowed industry ID, label, emoji, and current count;
- collection IDs and counts;
- each example's title, description, category, kind, recipe provenance,
  industry, contributor or environment when applicable, collections,
  requirements, source path, source guide URL, and local detail URL.

This is a static index rather than a server-side query API. A program can fetch
it once and apply its own filters, or construct a browser URL using the query
contract above.

## Update And Verify

After adding or changing an example README catalog block, validate its format,
then regenerate the committed Markdown catalog and local site:

```bash
python3 scripts/build_catalog.py --validate-metadata
python3 -m pip install --require-hashes -r scripts/catalog-requirements.txt
python3 scripts/fetch_catalog_assets.py
python3 scripts/build_catalog.py --write
```

Run the same checks used by the Pages workflow:

```bash
python3 scripts/build_catalog.py --check
python3 -m unittest discover -s scripts/tests -p 'test_build_catalog.py'
node --test scripts/tests/catalog.test.mjs
```

For local browser verification, follow the
[`catalog-deployment.md`](catalog-deployment.md#build-locally) instructions.
