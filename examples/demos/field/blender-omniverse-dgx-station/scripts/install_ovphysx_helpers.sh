#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

GUIDE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OV_REPO="${OV_REPO:-$HOME/work/ov-blender-hermes-demo/omniverse-labs/projects/ov-blender-example}"
OV_RUNTIME_ROOT="${OV_RUNTIME_ROOT:-}"
DEMO_ROOT="${DEMO_ROOT:-$HOME/work/ov-blender-hermes-demo}"
INSTALL_ROOT="${OVPHYSX_HELPER_ROOT:-$HOME/.local/share/nemoclaw-blender}"
CONFIG_ROOT="${OVPHYSX_HELPER_CONFIG_ROOT:-$HOME/.config/nemoclaw-blender}"

if [ -z "$OV_RUNTIME_ROOT" ]; then
  echo "OV_RUNTIME_ROOT must point to the installed platform runtime root." >&2
  exit 2
fi

fixture_root="$OV_REPO/tests/fixtures/data/demo_stair_drop_1280x720"
fixture="$fixture_root/fixture/stair_drop_ovrtx_ovphysx.usda"
prepare_script="$OV_REPO/tests/fixtures/demo_stair_drop_1280x720/prepare.py"
output_dir="${OVPHYSX_OUTPUT_DIR:-$DEMO_ROOT/out/stair-drop}"

mkdir -p "$INSTALL_ROOT" "$CONFIG_ROOT" "$output_dir"
install -m 0755 "$GUIDE_ROOT/scripts/run_ovphysx_timeline.py" "$INSTALL_ROOT/run_ovphysx_timeline.py"
install -m 0755 "$GUIDE_ROOT/scripts/ovphysx_host_helper.py" "$INSTALL_ROOT/ovphysx_host_helper.py"

python3 - \
  "$CONFIG_ROOT/ovphysx-helper.json" \
  "$OV_REPO" \
  "$OV_RUNTIME_ROOT" \
  "$fixture" \
  "$prepare_script" \
  "$INSTALL_ROOT/run_ovphysx_timeline.py" \
  "$output_dir" <<'PY'
import json
from pathlib import Path
import sys

config = {
    "ov_repo": sys.argv[2],
    "runtime_root": sys.argv[3],
    "fixture": sys.argv[4],
    "prepare_script": sys.argv[5],
    "timeline_runner": sys.argv[6],
    "output_dir": sys.argv[7],
    "body_prims": [
        f"/World/PhysicsIsland/DynamicBodies/Cube_{index:02d}"
        for index in range(12)
    ],
    "address": "127.0.0.1:50095",
    "device": "cpu",
    "steps": 240,
    "sample_every": 10,
    "fps": 60.0,
    "render_engine": "BLENDER_WORKBENCH",
    "resolution": [640, 360],
    "gif_fps": 12,
    "replace_scene": True,
    "ffmpeg": "/usr/bin/ffmpeg",
}
path = Path(sys.argv[1])
path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(path)
PY

echo "installed OVPhysX helpers under $INSTALL_ROOT"
echo "wrote helper configuration to $CONFIG_ROOT/ovphysx-helper.json"
