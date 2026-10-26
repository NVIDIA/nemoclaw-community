# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Draw assets/results-rounds.png: the base agent and each kept agent graded on the final eval
(nine checks), with the checks Eval Author added along the way, then the tokens per run.

    uv run --with plotly==7.1.0 --with kaleido==1.5.0 python results/rounds_chart.py assets/results-rounds.png
"""
import sys

import plotly.graph_objects as go
from plotly.subplots import make_subplots

INK, INK2, MUTED, GRID = '#1b1b1a', '#52514e', '#8a8983', '#e6e5df'
GREY, BLUE, ORANGE = '#c9c7bd', '#2a78d6', '#eb6834'
FONT = 'Helvetica Neue, Helvetica, Arial, sans-serif'

labels = ['Base<br>round 0', 'Round 1', 'Round 3', 'Round 6', 'Round 7', 'Round 10']
# Every agent's saved runs re-graded with the final verifier: nine checks per run.
passing = [0 / 4, 0 / 4, 0 / 4, 2 / 4, 4 / 4, 4 / 4]  # runs passing all nine checks: what the keep rule ranks first
iou1 = [0, .916, .970, .911, .933, .949]  # mean per part; 0 where no model was saved
iou2 = [0, .780, .943, .537, .936, .925]
tokens = [1.9, .04, .02, .24, .25, .13]  # median M tokens per run, from the traces
# Where the eval changed, between two groups: the check Eval Author added.
events = [(1.5, '+ compact-model'), (2.5, 'Ethos revised<br>+ independent-dimensions'),
          (4.5, '+ no-missing-feature')]

fig = make_subplots(rows=2, cols=1, row_heights=[0.68, 0.32], vertical_spacing=0.14,
                    subplot_titles=('<b>Each kept agent on the final eval</b>  ·  runs passing all checks and mean IoU per part.'
                                    '<br><span style="font-size:11px;color:#8a8983">Dotted lines: where Eval Author added a check; it reviewed the eval after every round.</span>',
                                    '<b>Tokens per run</b>  ·  median, millions'))
for name, ys, color in (('Runs passing all 9 checks', passing, GREY), ('Part 1 IoU', iou1, BLUE),
                        ('Part 2 IoU', iou2, ORANGE)):
    fig.add_bar(x=labels, y=ys, name=name, marker_color=color, marker_line_width=0, row=1, col=1,
                hovertemplate='%{x}: %{y:.2f}<extra>' + name + '</extra>')
fig.add_bar(x=labels, y=tokens, marker_color=BLUE, showlegend=False, row=2, col=1, width=0.45,
            text=[f'{t:g} M' for t in tokens], textposition='outside', cliponaxis=False,
            textfont=dict(color=INK, size=12))
# What the checks cannot show: why round 10 was still kept over round 7.
fig.add_annotation(x=labels[5], y=1.0, text='ties round 7 on every check;<br>kept for cleaner renders and<br>a branch never left out',
                   showarrow=False, row=1, col=1, font=dict(size=10, color=MUTED), yanchor='bottom', yshift=4)
for x, text in events:
    fig.add_vline(x=x, line=dict(color=MUTED, width=1, dash='dot'), row=1, col=1)
    fig.add_annotation(x=x, y=1.17, text=text, showarrow=False, row=1, col=1, xanchor='left', xshift=4,
                       font=dict(size=10.5, color=INK2), yanchor='bottom', align='left')
fig.add_hline(y=0.9, line=dict(color=INK2, width=1, dash='dot'), row=1, col=1)
fig.add_annotation(x=1.0, xref='paper', y=0.9, yref='y', text='IoU 0.9', showarrow=False,
                   xanchor='left', font=dict(size=10, color=INK2))
fig.add_annotation(x=labels[0], y=0.03, text='no model<br>saved', showarrow=False, row=1, col=1,
                   font=dict(size=10, color=MUTED), yanchor='bottom')

fig.update_layout(barmode='group', bargap=0.28, bargroupgap=0.06, width=1000, height=820,
                  template='simple_white', paper_bgcolor='white', plot_bgcolor='white',
                  font=dict(family=FONT, size=12.5, color=INK2), margin=dict(l=50, r=70, t=130, b=40),
                  legend=dict(orientation='h', x=0, y=1.0, yanchor='bottom', font=dict(size=12)))
for a in fig.layout.annotations[:2]:  # the two panel titles, left-aligned
    a.update(x=0, xanchor='left', align='left', font=dict(size=14.5, color=INK))
fig.layout.annotations[0].update(y=1.1, yanchor='bottom')
fig.update_yaxes(showline=False, ticks='', gridcolor=GRID, showgrid=True, zeroline=False,
                 tickfont=dict(color=MUTED))
fig.update_yaxes(range=[0, 1.3], tickvals=[0, .25, .5, .75, 1], ticktext=['0', '0.25', '0.5', '0.75', '1'], row=1, col=1)
fig.update_yaxes(range=[0, 2.3], tickvals=[0, 1, 2], row=2, col=1)
fig.update_xaxes(showline=True, linecolor=GRID, ticks='', tickfont=dict(color=INK2, size=12.5))
fig.write_image(sys.argv[1], scale=2)
