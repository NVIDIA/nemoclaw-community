<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Catalog Deployment

The [Pages workflow](../.github/workflows/pages.yml) validates structured
catalog metadata, generated Markdown, the static site, local resources, and
dependency-free interaction tests when a watched catalog path changes. It then
builds `_site/` from [`examples/catalog.json`](../examples/catalog.json) and
the sources under `site/`.

See [Example Catalog Architecture](catalog-architecture.md) for the metadata,
generation, README-detail, URL-filter, and public JSON contracts.

Matching pull requests attach the generated `_site/` directory as an
`example-catalog-preview` artifact and do not deploy. A matching push to
`main`, or a manual run from `main`, uploads that generated directory and
deploys it with the `github-pages` environment.

## Build Locally

After changing catalog metadata, regenerate the committed Markdown catalog and
build the site:

```bash
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

After deployment, verify the HTTPS page, the stylesheet, script, logo, and
`catalog.json` under the `/nemoclaw-community/` project path. Exercise text
search, both browse views, at least one category and industry filter, reset,
browser Back, a copied filtered URL, category fragments, and representative
compiled README detail pages, including local images and source links. Verify
at least one Mermaid detail page renders its diagrams without remote requests,
retains expandable source, and shows source when JavaScript is disabled. Then
set the repository website field to
`https://nvidia.github.io/nemoclaw-community/`.
