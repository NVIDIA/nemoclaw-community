#!/bin/zsh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Hard-restart the FreeCAD GUI (macOS). FreeCAD's transient document folders are
# moved, not deleted, to a backup so the relaunch does not stop on the
# document-recovery dialog. The caller waits for FreeCAD's RPC server afterwards.
pkill -9 -f "/Applications/FreeCAD.app/Contents/Resources/bin/freecad" 2>/dev/null
pkill -9 -f "freecadcmd" 2>/dev/null
sleep 3
C="$HOME/Library/Caches/FreeCAD/v1-1/Cache"
BK="$HOME/.cache/freecad-recovery-backup/$(date +%Y%m%d-%H%M%S)"
if ls "$C"/FreeCAD_* >/dev/null 2>&1; then mkdir -p "$BK" && mv "$C"/FreeCAD_* "$BK"/; fi
open -a FreeCAD
