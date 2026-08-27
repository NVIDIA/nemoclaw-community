<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Example Catalog Architecture

The NemoClaw Community catalog is a generated static site hosted by GitHub
Pages. It has no application server, database, remote JavaScript, or package
installation step.

## Source And Outputs

```text
examples/catalog.json ─┬─> examples/README.md
                       ├─> _site/index.html
site/index.template.html│
site/styles.css ────────┼─> _site/styles.css
site/catalog.mjs ───────┼─> _site/catalog.mjs
                       └─> _site/catalog.json
```

[`examples/catalog.json`](../examples/catalog.json) is the canonical metadata
source. [`scripts/build_catalog.py`](../scripts/build_catalog.py) validates it,
derives artifact kind and recipe provenance from the example path, and renders
the human and web outputs. The ignored `_site/` directory is disposable; do
not edit it directly.

The generated HTML contains every example card. The local JavaScript module
filters those cards in the browser, so the full category-organized catalog
remains readable when JavaScript is unavailable. GitHub Pages only serves the
generated files.

## Independent Discovery Dimensions

The catalog keeps these concepts separate:

- `kind` is `recipe`, `demo`, `launchable`, or `tool` and comes from the
  canonical path.
- `provenance` is `nvidia`, `partner`, or `community`, applies only to recipes,
  and also comes from the canonical path.
- `industry` is one required controlled value on every example, independent of
  kind and provenance.
- `collections` is an optional cross-cutting discovery field. `hackathon` is a
  collection; it does not replace kind, provenance, or contributor attribution.

The build rejects a manifest path that disagrees with the repository taxonomy,
an unlisted top-level example, a listed example without a README, and metadata
outside the controlled schema.

## Browser Search Contract

Catalog state is encoded in the URL so a filtered view can be copied,
bookmarked, or created by another program:

| Parameter | Values | Behavior |
| --- | --- | --- |
| `q` | Plain text | Case-insensitive whitespace-token AND search across title, description, fit, contributor, category, and industry. |
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
- every allowed industry ID, label, and current count;
- collection IDs and counts;
- each example's title, description, category, kind, recipe provenance,
  industry, contributor or environment when applicable, collections, fit,
  source path, and guide URL.

This is a static index rather than a server-side query API. A program can fetch
it once and apply its own filters, or construct a browser URL using the query
contract above.

## Update And Verify

After adding or changing a manifest entry, regenerate the committed Markdown
catalog and local site:

```bash
python3 scripts/build_catalog.py --write
```

Run the same dependency-free checks used by the Pages workflow:

```bash
python3 scripts/build_catalog.py --check
python3 -m unittest discover -s scripts/tests -p 'test_build_catalog.py'
node --test scripts/tests/catalog.test.mjs
```

For local browser verification, follow the
[`catalog-deployment.md`](catalog-deployment.md#build-locally) instructions.
