# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Draw assets/results-rounds.png: checks passed, best IoU per part and tokens per run, by round.

    uv run --with matplotlib python results/rounds_chart.py assets/results-rounds.png
"""
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

SURFACE, INK, INK2, MUTED, GRID, AXIS = '#fcfcfb', '#0b0b0b', '#52514e', '#898781', '#e1e0d9', '#c3c2b7'
BLUE, ORANGE = '#2a78d6', '#eb6834'

labels = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'conf.']
x = list(range(len(labels)))
# Share of the eval's checks passed over the round's runs (the eval had 7, then 8, then 9 checks);
# round 8 ran smoke tests only.
checks = [0, 22/28, 18/28, 1, 28/32, 3/32, 30/32, 1, None, 1, 1, 1]
# Best run per part; None where no run saved a valid solid.
iou1 = [None, .92, None, .97, .97, None, .92, .93, None, .95, .95, .952]
iou2 = [None, .78, .85, .94, .94, None, .80, .95, None, .93, .93, .924]
tokens = [1.9, .04, .08, .02, .03, 1.0, .24, .25, None, .16, .13, .12]  # median M tokens per run

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'text.color': INK,
                     'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': MUTED})
fig, axes = plt.subplots(3, 1, figsize=(9, 8.2), sharex=True, facecolor=SURFACE,
                         gridspec_kw={'hspace': 0.42})


def style(ax, title):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc='left', fontsize=11, color=INK, pad=8)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(AXIS)
    ax.grid(axis='y', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    # The Ethos revision, between rounds 3 and 4.
    ax.axvline(3.5, color=MUTED, linewidth=1, linestyle=(0, (3, 3)))


def line(ax, ys, color, label=None):
    pts = [(i, y) for i, y in zip(x, ys) if y is not None]
    # Break the line where a round has no value, rather than bridging the gap.
    ax.plot(x, [float('nan') if y is None else y for y in ys], color=color, linewidth=2, zorder=3)
    ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=42, color=color, zorder=4,
               edgecolors=SURFACE, linewidths=2, label=label)


ax = axes[0]
style(ax, 'Checks passed (share of the eval\'s checks, all runs of the round)')
line(ax, checks, BLUE)
ax.set_ylim(-0.05, 1.12)
ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:.0%}'))
ax.text(3.6, 1.04, 'Ethos revised', color=INK2, fontsize=9, va='bottom')
for xi, txt in ((1, '+ compact-model'), (3.5, ''), (9, '+ no-missing-feature')):
    if txt:
        ax.annotate(txt, (xi, checks[int(xi)]), xytext=(0, -26), textcoords='offset points',
                    ha='left', color=INK2, fontsize=8.5)
ax.annotate('+ independent-dimensions', (4, checks[4]), xytext=(10, -4), textcoords='offset points',
            ha='left', color=INK2, fontsize=8.5)

ax = axes[1]
style(ax, 'Best IoU per part (overlap with the mesh; the check needs 0.9)')
ax.axhline(0.9, color=INK2, linewidth=1, linestyle=(0, (1, 2)))
ax.text(-0.3, 0.905, 'target 0.9', color=INK2, fontsize=8.5, va='bottom')
line(ax, iou1, BLUE, 'Part 1')
line(ax, iou2, ORANGE, 'Part 2')
ax.set_ylim(0.7, 1.0)
ax.text(11.3, iou1[-1], 'Part 1', color=INK, fontsize=9, va='center')
ax.text(11.3, iou2[-1] - 0.004, 'Part 2', color=INK, fontsize=9, va='top')
ax.legend(loc='lower right', frameon=False, fontsize=9, bbox_to_anchor=(1.0, 0.0), ncol=2,
          labelcolor=INK)

ax = axes[2]
style(ax, 'Tokens per run (median, millions, log scale)')
line(ax, tokens, BLUE)
ax.set_yscale('log')
ax.set_ylim(0.012, 4)
ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'))
ax.set_xticks(x, labels)
ax.set_xlim(-0.5, 12.1)
ax.set_xlabel('Round (conf. = the final agent\'s 10-run confirmation)', color=INK2)
for i, t in ((0, 'learning FreeCAD by trial'), (5, 'raw API scripts'), (3, 'one-command script')):
    ax.annotate(t, (i, tokens[i]), xytext=(-8, -14) if i == 3 else (8, 4), ha='right' if i == 3 else 'left', textcoords='offset points', color=INK2, fontsize=8.5)

fig.text(0.125, 0.015, 'Gaps: no run saved a valid solid (rounds 0 and 5; part 1 in round 2); round 8 ran smoke tests only.',
         color=MUTED, fontsize=8.5)
fig.savefig(sys.argv[1], dpi=160, facecolor=SURFACE, bbox_inches='tight')
