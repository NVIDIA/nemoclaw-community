<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Build-a-Claw Tutorial

| Catalog field | Value |
| --- | --- |
| Description | Guides DGX Spark users through serving local multimodal models with vLLM or llama.cpp, connecting an agent harness, and trying coding, vision, browser, messaging, and speech workflows. |
| Industry | 🎓 Academia/Education |
| Requirements | NVIDIA DGX Spark · Ubuntu with sudo, CUDA build tools, Node.js 24.16.0, Python 3.13, internet, and storage for large NVFP4 or GGUF downloads · optional external accounts and device permissions |
| NemoClaw | N/A |
| Harness | OpenClaw 2026.9.4 |
| OpenShell | N/A |
| Collection | Build-a-Claw |

This documentation-only field tutorial walks an instructor and participants
through a Build-a-Claw experience on NVIDIA DGX Spark. OpenClaw is the primary
documented harness. An alternative section explains how to connect Hermes to
the same local model server.

## Tutorial Source

[`tutorial.md`](tutorial.md) is the single source for the tutorial content. Its
exact filename activates the catalog's tutorial renderer, which compiles the
file directly so its maintainer never has to update a second copy.

## Published Tutorial

The GitHub Pages build turns each authored `# Part` heading into a page with
progress, Previous, and Next navigation. It highlights explicitly typed code,
adds copy controls, and presents the guide in the community catalog theme.
Remote images become outbound links instead of loading automatically. Without
JavaScript, the same content remains available as one continuous document.
The renderer does not execute or validate tutorial commands. Build the page
from the repository root with:

```bash
python3 scripts/build_catalog.py --write
```

## Current Status

Repository checks verify the tutorial presentation and public release
identities. A DGX Spark check verified that OpenClaw `2026.9.4` installs and
starts its CLI with Node.js `24.16.0`. A further check verified the
pinned Hermes installer, exact checkout, `0.21.1` CLI identity, and
`hermes doctor`. The complete DGX Spark, model-serving, daemon, device, and
external-service workflow has not completed a live end-to-end check in this
repository. Read the safety boundary in
[`tutorial.md`](tutorial.md#before-you-begin) before you run any command.
