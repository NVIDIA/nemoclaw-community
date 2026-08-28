<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Assets

`offline-self-test.svg` is the source and the checked file.
`tests/test_selftest_end_to_end.py` runs the offline self-test and requires every
result line the SVG claims to appear in the output, so the picture cannot drift
from the run it depicts.

`offline-self-test.png` is exported from it, because `scripts/build_catalog.py`
accepts only raster formats in a README and the catalog renders that image. A
raster cannot be read back and compared, so **edit the SVG and re-export the
PNG** -- never the PNG alone.
