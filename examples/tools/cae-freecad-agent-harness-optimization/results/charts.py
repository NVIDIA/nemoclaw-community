# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The README's round charts, from results/rounds.json (every agent the loop measured): for the
base agent and each kept agent, on each split, runs passing, checks passed and mean IoU
(assets/rounds-<split>.png), and median tokens per run (assets/tokens-<split>.png).
Run from the example root:

    uv run --with plotly==7.1.0 --with kaleido==1.5.0 python results/charts.py
"""
import json
import statistics
from pathlib import Path

import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'results' / 'rounds.json').read_text())
INK, INK2, MUTED, GRID = '#1b1b1a', '#52514e', '#8a8983', '#e6e5df'
GREY, BLUE, ORANGE = '#c9c7bd', '#2a78d6', '#eb6834'
FONT = 'Helvetica Neue, Helvetica, Arial, sans-serif'


def label(agent: dict) -> str:
    return 'Base agent<br>start' if agent['status'] == 'base' else f"{agent['change']}<br>round {agent['round']}"


def layout(fig, title: str, subtitle: str, height: int) -> None:
    fig.update_layout(width=1000, height=height, template='simple_white', paper_bgcolor='white', plot_bgcolor='white',
                      font=dict(family=FONT, size=12.5, color=INK2), margin=dict(l=50, r=40, t=120, b=40),
                      title=dict(text=f'<b>{title}</b>  ·  {subtitle}', x=0.05, xanchor='left', y=0.96,
                                 font=dict(size=14.5, color=INK)),
                      legend=dict(orientation='h', x=0, y=1.02, yanchor='bottom', font=dict(size=12)))
    fig.update_yaxes(showline=False, ticks='', gridcolor=GRID, showgrid=True, zeroline=False, tickfont=dict(color=MUTED))
    fig.update_xaxes(showline=True, linecolor=GRID, ticks='', tickfont=dict(color=INK2, size=12.5))


def rounds(split: str, agents: list) -> go.Figure:
    xs, ms = [label(a) for a in agents], [a[split] for a in agents]
    runs = [100 * m['passed'] / m['runs'] for m in ms]
    checks = [100 * m['checks'] / m['of'] for m in ms]
    iou = [100 * statistics.mean(m['ious']) if m['ious'] else 0 for m in ms]
    fig = go.Figure()
    for name, ys, color, text in (
            ('Runs passing all 9 checks', runs, GREY, [f"{v:.0f}%<br>{m['passed']}/{m['runs']}" for v, m in zip(runs, ms)]),
            ('Checks passed', checks, BLUE, [f'{v:.0f}%' for v in checks]),
            ('Mean IoU', iou, ORANGE, [f'{v:.0f}%' if m['ious'] else 'no<br>model' for v, m in zip(iou, ms)])):
        fig.add_bar(x=xs, y=ys, name=name, marker_color=color, marker_line_width=0, text=text,
                    textposition='outside', cliponaxis=False, textfont=dict(color=INK, size=11.5))
    layout(fig, f'Kept agent per round, {split}', DATA['splits'][split] + ', in %', 560)
    fig.update_layout(barmode='group', bargap=0.28, bargroupgap=0.06)
    fig.update_yaxes(range=[0, 118], tickvals=[0, 25, 50, 75, 100], ticksuffix='%')
    return fig


def tokens(split: str, agents: list) -> go.Figure:
    meds = [statistics.median(a[split]['tokens']) / 1e6 for a in agents]
    fig = go.Figure(go.Bar(x=[label(a) for a in agents], y=meds, marker_color=BLUE, marker_line_width=0, width=0.45,
                           text=[f'{t:.2f} M' for t in meds], textposition='outside', cliponaxis=False,
                           textfont=dict(color=INK, size=12)))
    layout(fig, f'Tokens per run, {split}', 'median, millions', 380)
    fig.update_layout(margin=dict(t=80))
    fig.update_yaxes(range=[0, max(meds) * 1.25])
    return fig


def main() -> None:
    agents = [a for a in DATA['agents'] if a['status'] in ('base', 'kept')]
    for split in DATA['splits']:
        rounds(split, agents).write_image(str(ROOT / 'assets' / f'rounds-{split}.png'), scale=2)
        tokens(split, agents).write_image(str(ROOT / 'assets' / f'tokens-{split}.png'), scale=2)


if __name__ == '__main__':
    main()
