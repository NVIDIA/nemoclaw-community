# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Worked example on a MADE-UP part (a watering can, not your mesh): the decisions are the
# point, not the numbers. Measured: elliptical tub z 0..30 centred (50, 20), 40 x 30 at the
# bottom, 44 x 33 at the top, wall 1.5, floor 2; a round handle (diameter 4) arching over
# the -x side from (28,20,8) to (28,20,26); a straight spout (diameter 6) leaving +x along
# (2,0,1) whose end face is vertical at x = 110; a drain hole of diameter 3 in the floor.
import sys; sys.path.insert(0, '/agent/skills/build-features'); from cadkit import *
m = Model()
m.param('Height', 30); m.param('Wall', 1.5); m.param('Floor', 2)          # design intent:
m.param('HandleDiameter', 4); m.param('SpoutReach', 40); m.param('DrainDiameter', 3)
# 1. main body first, alone: save it, verify it, then add one feature per run
tub = [m.ellipse('Bottom', (50, 20, 0), 40, 30), m.ellipse('Top', (50, 20, 'Height'), 44, 33)]
m.loft('Tub', tub)
# 2. branches next, each its own feature reaching into the body wall
m.tube('Handle', [(31, 20, 8), (24, 20, 12), (22, 20, 18), (24, 20, 24), (31, 20, 26)], 'HandleDiameter')
spout = m.circle('SpoutEnd', (110, 20, 40), 6, normal=(1, 0, 0))             # in its end-face plane
m.pad('Spout', spout, 'SpoutReach', direction=(-2, 0, -1))                    # back toward the tub, slanted
# 3. cavities last, from the floor to above the rim: inner = outer - 2 x Wall
cav = [m.ellipse('CavBottom', (50, 20, 'Floor'), '40 - 2*Wall', '30 - 2*Wall'),
       m.ellipse('CavTop', (50, 20, 'Height + 1'), '44 - 2*Wall', '33 - 2*Wall')]
m.loft('Cavity', cav, cut=True)
m.hole('Drain', (50, 20, 'Floor'), (0, 0, 1), 'DrainDiameter')
m.save('/app/model.FCStd')
