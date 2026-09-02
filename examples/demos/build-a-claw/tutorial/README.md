<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Build-a-Claw Tutorial

| Catalog field | Value |
| --- | --- |
| Description | Presents an author-maintained Build-a-Claw guide as a five-part tutorial with progress tracking, responsive media, and copyable highlighted code. |
| Industry | 🎓 Academia/Education |
| Requirements | Modern web browser · documentation-only tutorial · commands are not validated by this repository |
| NemoClaw | N/A |
| Harness | N/A |
| OpenShell | N/A |

This directory is the home for the first Build-a-Claw tutorial. The tutorial
will teach participants how to move through the Build-a-Claw experience in a
guided, web-friendly format.

## Tutorial Source

[`tutorial.md`](tutorial.md) is the single source for the tutorial content. Its
exact filename activates the catalog's tutorial renderer, which compiles the
file directly so its maintainer never has to update a second copy.

## Published Tutorial

The GitHub Pages build turns each authored `# Part` heading into a page with
progress, Previous, and Next navigation. It highlights explicitly typed code,
adds copy controls, and presents media in the community catalog theme. Without
JavaScript, the same content remains available as one continuous document. The
renderer does not execute or validate tutorial commands. Build the page from
the repository root with:

```bash
python3 scripts/build_catalog.py --write
```

## Current Status

The tutorial page verifies presentation only. The guide remains author-owned,
and its commands and technical claims are outside the catalog build's checks.
