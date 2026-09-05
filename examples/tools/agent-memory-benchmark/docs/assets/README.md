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

There is no way to attach a digest to an existing file: a stamp-in-place path
would let one vouch for pixels nobody re-rendered. The digest records provenance;
reading the image with `tesseract` proves the export shows what the SVG says, and
that check is required rather than conditional. Install it with
`brew install tesseract` or `apt-get install tesseract-ocr`.
