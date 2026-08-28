<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Catalog Deployment

The [Pages workflow](../.github/workflows/pages.yml) exposes a separate check
for the standardized metadata block in every example README, then validates
generated Markdown, the static site, local resources, and dependency-free
interaction tests. It builds `_site/` from the discovered root READMEs and the
sources under `site/`.

See [Example Catalog Architecture](catalog-architecture.md) for the metadata,
generation, README detail-page, URL filter, public JSON, and `llms.txt`
contracts.

Matching pull requests attach the generated `_site/` directory as an
`example-catalog-preview` artifact and do not deploy. A matching push to
`main`, or a manual run from `main`, uploads that generated directory and
deploys it with the `github-pages` environment.

## Build Locally

After changing an example's opening catalog block or a category or collection
index title or description, validate its format, regenerate the committed
Markdown indexes, and build the site:

```bash
python3 scripts/build_catalog.py --validate-metadata
python3 -m pip install --require-hashes -r scripts/catalog-requirements.txt
python3 scripts/fetch_catalog_assets.py
python3 scripts/build_catalog.py --write
```

Validate without changing files and rebuild the ignored `_site/` directory:

```bash
python3 scripts/build_catalog.py --check
python3 scripts/build_catalog.py
```

Serve the same directory that Pages receives:

```bash
python3 -m http.server --directory _site 8000
```

Open `http://localhost:8000/`. Do not edit `_site/` directly; it is disposable
build output.

## Enable GitHub Pages

Before the first deployment, a repository administrator must complete these
GitHub settings:

1. In **Settings > Pages**, select **GitHub Actions** as the source.
2. Create or open the **github-pages** environment in **Settings > Environments**.
3. Restrict its deployment branches and tags to `main`.

Do not add a personal access token to enable Pages.

## Deploy The Catalog

After the settings are in place, merge the catalog change or run **Example
catalog Pages** from `main` in the Actions tab. If an earlier deployment failed
because Pages was disabled, rerun that workflow from `main`.

## Verify The Deployment

After deployment, verify the HTTPS page, the stylesheet, script, logo,
`catalog.json`, and `llms.txt` under the `/nemoclaw-community/` project path.
Confirm that the five canonical category tiles and the Hackathon and
Build-a-Claw collection tiles show their README-derived descriptions, and that
the NemoClaw Brev link opens the external launchable. Exercise text search,
both browse views, at least one category, collection, and industry filter,
reset, browser Back, a copied filtered URL, category fragments, and
representative compiled README detail pages, including local images, source
links, and an upstream-project link when present. Verify at least one Mermaid
detail page renders its diagrams without remote requests, retains expandable
source, and shows source when JavaScript is disabled. Then set the repository
website field to
`https://nvidia.github.io/nemoclaw-community/`.
