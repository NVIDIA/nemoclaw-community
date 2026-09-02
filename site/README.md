<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Catalog Website Source

This directory contains the authored presentation layer for the generated
NemoClaw Community catalog. Example READMEs remain the content and metadata
source of truth. `python3 scripts/build_catalog.py` combines those READMEs with
these files and writes the disposable `_site/` directory used by GitHub Pages.

Do not edit `_site/` directly and do not add a package manager or application
server for this site. The browser scripts are native ES modules: the `.mjs`
extension makes their `import` and `export` behavior explicit to browsers and
Node.js without a bundling step.

## Source Map

```text
templates/   Authored HTML shells with builder replacement markers
styles/      Shared and page-specific presentation
scripts/     Browser behavior and pure catalog state helpers
assets/      Images and notices copied into the generated site
```

The Python implementation that discovers, renders, validates, and publishes
the catalog lives under `scripts/catalog/`. The stable command-line entry point
is `scripts/build_catalog.py`.

## Page Assets

| Page | Styles | Scripts |
| --- | --- | --- |
| Catalog index | `shared.css`, `catalog.css` | `catalog.mjs`, which imports `catalog-state.mjs` |
| Example detail | `shared.css`, `detail.css` | None unless the README contains Mermaid |
| Tutorial detail | `shared.css`, `detail.css`, `tutorial.css` | `tutorial.mjs`, plus Mermaid scripts when needed |

`diagrams.mjs` and the pinned Mermaid runtime load only on pages with validated
Mermaid fences. Regular detail pages otherwise remain script-free.

## Local Build

```bash
python3 -m pip install --require-hashes -r scripts/catalog-requirements.txt
python3 scripts/fetch_catalog_assets.py
python3 scripts/build_catalog.py --check
python3 scripts/build_catalog.py
python3 -m http.server --directory _site 8000
```

Open `http://localhost:8000/`. See
[`docs/catalog-architecture.md`](../docs/catalog-architecture.md) for the full
generation, validation, security, and metadata contracts.
