# Third-party components

## Bundled renderer

- Project: Three.js
- Version/tag: r180 (0.180.0)
- Source: https://github.com/mrdoob/three.js/blob/r180/build/three.cjs
- Local source: `three-r180.cjs`, upstream build with one indentation-only whitespace fix
- License: MIT, retained in `three-LICENSE.txt`

The build script embeds the renderer and the full MIT notice in the standalone page.

## OpenShell policy reference

`scripts/security_lab.py` adapts the policy fields from NVIDIA/OpenShell's Apache-2.0 sandbox-policy-quickstart example at commit `fa0bfa490e42c87a74a70be6ebb40faee7fb8faa`. Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. The upstream license is retained in `OpenShell-LICENSE.txt`. Multi-Agent Studio provides its own probe controller. The Docker build downloads the OpenShell CLI using the version and checksum in [the runtime lockfile](../../docker/runtime-lock.json).

## Installed during the local build

The [Dockerfile](../../Dockerfile) installs [NeMo Switchyard](https://github.com/NVIDIA-NeMo/Switchyard) and [OpenClaw](https://github.com/openclaw/openclaw) with its OpenShell and Parallel plugins. The exact npm dependencies are recorded in the [package lockfile](../../docker/runtime/package-lock.json). Each dependency retains its upstream license.

## Weather data

The studio bundles a reduced GeoNames city list and retrieves forecasts from MET Norway. Both datasets use CC BY 4.0. [Weather sources and adaptations](../../runtime/research-guard/weather/README.md)
