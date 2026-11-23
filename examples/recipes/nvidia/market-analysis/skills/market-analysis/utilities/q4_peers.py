#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Question 4 helper: declared-peer correlations and PageRank centrality, as JSON.

  python3 utilities/accelerate.py run utilities/q4_peers.py

Window 2026-06-01..2026-08-31. For each declared peer pair (one row per unordered pair) the correlation of
total_return_1d on shared sessions; the list is sorted by absolute correlation. PageRank (damping 0.85) over the
declared-peer graph with weight = |corr|.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
AS_OF = "2026-08-31"


def receipt():
    raw = os.environ.get("ACCELERATE_ENGINE")
    return json.loads(raw) if raw else None


def emit(result):
    out = {"engine_receipt": receipt(), **result}
    print(json.dumps(out, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))

import networkx as nx


def main():
    if not os.environ.get("ACCELERATE_ENGINE"):
        sys.exit("blocked: run this helper with `python3 utilities/accelerate.py run utilities/%s` so the engine receipt exists. "
                 "Do not run it with plain python3 or install packages; report the analysis as blocked if accelerate.py cannot run." % Path(__file__).name)
    prices = pd.read_csv(DATA / "daily_prices.csv")
    rel = pd.read_csv(DATA / "asset_relationships.csv")
    win = prices[(prices.trading_date >= "2026-06-01") & (prices.trading_date <= AS_OF)]
    wide = win.pivot(index="trading_date", columns="asset_id", values="total_return_1d")
    pairs = sorted({tuple(sorted(p)) for p in zip(rel.source_asset_id, rel.target_asset_id)})
    rows = []
    G = nx.Graph()
    for a, b in pairs:
        both = wide[[a, b]].dropna()
        c = float(both[a].corr(both[b]))
        rows.append({"pair": f"{a}-{b}", "correlation": round(c, 4), "abs_correlation": round(abs(c), 4), "shared_sessions": int(len(both))})
        G.add_edge(a, b, weight=abs(c))
    rows.sort(key=lambda r: -r["abs_correlation"])
    pr = nx.pagerank(G, alpha=0.85, weight="weight")
    ranked = sorted(pr.items(), key=lambda kv: -kv[1])
    pairs_md = ["| # | pair | correlation | shared sessions |", "| --- | --- | --- | --- |"]
    pairs_md += [f"| {i} | {r['pair']} | {r['correlation']:+.4f} | {r['shared_sessions']} |" for i, r in enumerate(rows, 1)]
    rank_md = ["| rank | issuer | PageRank |", "| --- | --- | --- |"]
    rank_md += [f"| {i} | {k} | {v:.4f} |" for i, (k, v) in enumerate(ranked[:10], 1)]
    emit({"window": f"2026-06-01..{AS_OF}", "pair_count": len(rows),
          "pairs_table_markdown": "\n".join(pairs_md), "pagerank_top10_table_markdown": "\n".join(rank_md), "pairs_by_abs_correlation": rows,
          "pagerank_damping": 0.85, "pagerank_nodes": G.number_of_nodes(),
          "pagerank": [{"rank": i, "asset_id": k, "pagerank": round(v, 4)} for i, (k, v) in enumerate(ranked, 1)],
          "note": "Declared peer links only. Centrality is not proof of influence; correlation is not cause."})


if __name__ == "__main__":
    main()
