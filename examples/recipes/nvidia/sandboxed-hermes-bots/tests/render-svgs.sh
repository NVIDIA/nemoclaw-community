#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Render every SVG under docs/img to PNG at its declared size with headless
# Chrome, so you can eyeball diagrams before committing. macOS path shown;
# set CHROME for another platform. Usage: tests/render-svgs.sh [outdir]
set -euo pipefail
cd "$(dirname "$0")/../docs/img"
out="${1:-/tmp/svg-render}"; mkdir -p "$out"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
for f in *.svg; do
  w=$(grep -oE 'width="[0-9]+"' "$f" | head -1 | tr -dc 0-9)
  h=$(grep -oE 'height="[0-9]+"' "$f" | head -1 | tr -dc 0-9)
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --window-size="$w,$h" --screenshot="$out/${f%.svg}.png" "file://$PWD/$f" >/dev/null 2>&1
  echo "$out/${f%.svg}.png"
done
