<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Assets

`offline-self-test.svg` is the source and the checked file.
`tests/test_selftest_end_to_end.py` runs the offline self-test and requires every
result line the SVG claims to appear in the output, so the picture cannot drift
from the run it depicts.

`offline-self-test.png` is exported from it, because `scripts/build_catalog.py`
accepts only raster formats in a README and that is the image a reader sees. The
export records the SVG's SHA-256 in a PNG `tEXt` chunk, so a test can prove the
two describe the same run without OCR and without file timestamps, which git
does not preserve.

**Edit the SVG, then re-export:**

```bash
python3 tools/export_selftest_image.py
```

Never edit the PNG alone, and do not re-export with a tool that drops the `tEXt`
chunk — the test will say the raster records no source digest.
