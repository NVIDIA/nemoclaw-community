<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Catalog Deployment

The [Pages workflow](../.github/workflows/pages.yml) validates the static catalog
and local links when a watched catalog path changes. Matching pull requests
attach an `example-catalog-preview` artifact and do not deploy. A matching push
to `main`, or a manual run from `main`, packages `site/` and deploys it with the
`github-pages` environment.

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

After deployment, verify the HTTPS page, the stylesheet and logo under the
`/nemoclaw-community/` project path, the category links, and the example README
links. Then set the repository website field to
`https://nvidia.github.io/nemoclaw-community/`.
