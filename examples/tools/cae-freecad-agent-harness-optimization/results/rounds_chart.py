# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Draw assets/results-rounds.png: for the base agent and each kept agent, the share of checks
passed and the mean IoU per part, then the tokens per run.

    uv run --with matplotlib python results/rounds_chart.py assets/results-rounds.png
"""
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

SURFACE, INK, INK2, MUTED, GRID, AXIS = '#fcfcfb', '#0b0b0b', '#52514e', '#898781', '#e1e0d9', '#c3c2b7'
BLUE, ORANGE, GREY = '#2a78d6', '#eb6834', '#b4b2a8'

# The base agent, each kept agent (by the round that kept it) and the final agent's 10-run
# confirmation, from the round table in README.md.
labels = ['Base\n(round 0)', 'Round 1', 'Round 3', 'Round 6', 'Round 7', 'Round 10', 'Final\n10 runs']
passed = ['0/4', '0/4', '4/4', '2/4', '4/4', '4/4', '10/10']
# Checks passed over the agent's runs, out of the checks the eval had at the time.
checks = [0 / 28, 22 / 28, 28 / 28, 30 / 32, 32 / 32, 36 / 36, 90 / 90]
# Mean IoU per part over the runs; 0 where no run saved a valid solid.
iou1 = [0, .915, .97, .91, .93, .95, .950]
iou2 = [0, .78, .94, .535, .935, .925, .915]
tokens = [1.9, .04, .02, .24, .25, .13, .12]  # median M tokens per run
x = range(len(labels))

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'text.color': INK,
                     'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': MUTED})
fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 7.4), facecolor=SURFACE,
                                  gridspec_kw={'hspace': 0.55, 'height_ratios': [1.35, 1]})


def style(ax, title):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc='left', fontsize=11, color=INK, pad=10)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(AXIS)
    ax.grid(axis='y', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xticks(list(x), labels)
    ax.set_xlim(-0.6, 6.9)
    # The Ethos revision, between rounds 3 and 6: the round-3 agent falls to 0/10.
    ax.axvline(2.5, color=MUTED, linewidth=1, linestyle=(0, (3, 3)))


w = 0.26
style(top, 'Checks passed and mean IoU per part (runs passed above each agent)')
for dx, ys, color, name in ((-w, checks, GREY, 'Checks passed (share)'), (0, iou1, BLUE, 'Part 1 IoU'),
                            (w, iou2, ORANGE, 'Part 2 IoU')):
    top.bar([i + dx for i in x], ys, w * 0.92, color=color, label=name, zorder=3)
top.axhline(0.9, color=INK2, linewidth=1, linestyle=(0, (1, 2)), zorder=4)
top.text(6.55, 0.9, 'IoU\ntarget', color=INK2, fontsize=8.5, va='center', ha='left')
for i, p in zip(x, passed):
    top.text(i, 1.04, p, ha='center', va='bottom', color=INK, fontsize=9.5, fontweight='bold')
top.text(2.55, 1.17, 'Ethos revised', color=INK2, fontsize=9, va='bottom')
top.text(0, 0.03, 'no model\nsaved', ha='center', va='bottom', color=MUTED, fontsize=8.5)
top.set_ylim(0, 1.25)
top.set_yticks([0, .25, .5, .75, 1])
top.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'))
top.legend(loc='upper left', bbox_to_anchor=(0, -0.2), ncol=3, frameon=False, fontsize=9,
           labelcolor=INK)

style(bottom, 'Tokens per run (median, millions)')
bottom.bar(list(x), tokens, 0.5, color=BLUE, zorder=3)
for i, t in zip(x, tokens):
    bottom.text(i, t + 0.04, f'{t:g} M', ha='center', va='bottom', color=INK, fontsize=9)
bottom.text(0.32, 1.9, 'learning FreeCAD\nby trial and error', color=INK2, fontsize=8.5, va='top')
bottom.set_ylim(0, 2.2)

fig.savefig(sys.argv[1], dpi=160, facecolor=SURFACE, bbox_inches='tight')
