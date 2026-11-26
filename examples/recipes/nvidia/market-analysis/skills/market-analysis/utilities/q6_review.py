#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Question 6 helper: a review-first table for the 12 most liquid issuers, built from the Q2, Q3 and Q4 helpers, as JSON.

  python3 utilities/accelerate.py run utilities/q6_review.py

The table is computed, not written by the agent: each issuer's 20-session return and rank (Q2), the unusual sessions it
appears in (Q3), its declared-peer PageRank rank and its strongest peer pair (Q4), and the reasons to look that follow from
those facts. Copy the `review_first` rows and their `reasons` as they are; do not add facts of your own. A reason to look is
not a recommendation to buy or sell and says nothing about any filing or incident. Kumo is separate (`kumo_predict.py`).
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOP_N = 5


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_helper(name):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        load(name).main()
    return json.loads(buffer.getvalue())


def main():
    if not os.environ.get("ACCELERATE_ENGINE"):
        sys.exit("blocked: run this helper with `python3 utilities/accelerate.py run utilities/%s` so the engine receipt exists. "
                 "Do not run it with plain python3 or install packages; report the analysis as blocked if accelerate.py cannot run." % Path(__file__).name)
    q2, q3, q4 = run_helper("q2_leaders"), run_helper("q3_unusual"), run_helper("q4_peers")
    ranking = q2["ranking_strongest_first"]
    nodes = q4["pagerank_nodes"]
    pagerank = {r["asset_id"]: r for r in q4["pagerank"]}
    strongest = {}
    for pair in q4["pairs_by_abs_correlation"]:  # sorted strongest first: the first pair seen is the issuer's strongest
        for asset in pair["pair"].split("-"):
            strongest.setdefault(asset, pair)
    anomalies = {}
    for row in q3["top_ten"]:
        anomalies.setdefault(row["asset_id"], []).append(row)
    table, n = [], len(ranking)
    for r in ranking:
        a = r["asset_id"]
        reasons = []
        if r["rank"] <= 3:
            reasons.append(f"top 3 of the 12 by 20-session return: {r['return_20_sessions']:+.4f} (rank {r['rank']} of {n})")
        if r["rank"] > n - 3:
            reasons.append(f"bottom 3 of the 12 by 20-session return: {r['return_20_sessions']:+.4f} (rank {r['rank']} of {n})")
        for s in anomalies.get(a, []):
            news = "with a same-day news item (an association)" if s["same_day_news"] else "with no same-day news item"
            reasons.append(f"in the ten most unusual issuer sessions: {s['trading_date']}, rank {s['rank']}, score {s['score']}, "
                           f"dominant feature {s['dominant_feature']}, {news}")
        pr = pagerank.get(a)
        if pr and pr["rank"] <= 10:
            reasons.append(f"PageRank rank {pr['rank']} of {nodes} in the declared-peer graph ({pr['pagerank']}); centrality is not influence")
        pair = strongest.get(a)
        if pair and pair["abs_correlation"] >= 0.4:
            reasons.append(f"in a strongly co-moving declared pair {pair['pair']} (correlation {pair['correlation']})")
        table.append({"asset_id": a, "liquidity_rank": r["liquidity_rank"], "sector": r["sector"],
                      "return_20_sessions": r["return_20_sessions"], "return_rank_of_12": r["rank"],
                      "daily_volatility": r["daily_volatility"],
                      "unusual_sessions_in_top_ten": [{"trading_date": s["trading_date"], "rank": s["rank"], "score": s["score"]}
                                                      for s in anomalies.get(a, [])],
                      "pagerank_rank": pr["rank"] if pr else None, "pagerank_nodes": nodes,
                      "pagerank": pr["pagerank"] if pr else None,
                      "strongest_peer_pair": pair["pair"] if pair else None,
                      "strongest_peer_abs_correlation": pair["abs_correlation"] if pair else None,
                      "reasons_to_look": reasons})
    ordered = sorted(table, key=lambda t: (-len(t["reasons_to_look"]), t["liquidity_rank"]))
    review_first = [{"order": i, "asset_id": t["asset_id"], "reasons_to_look": t["reasons_to_look"]}
                    for i, t in enumerate([t for t in ordered if t["reasons_to_look"]][:TOP_N], 1)]
    lines = ["PROPOSED_FOR_REVIEW. Human confirmations are pending. Reasons to look only; not investment advice, and no issuer filed anything.", ""]
    for r in review_first:
        lines.append(f"{r['order']}. **{r['asset_id']}**")
        lines += [f"   - {reason}" for reason in r["reasons_to_look"]]
    block = "\n".join(lines)
    work = Path.cwd() / "work"
    work.mkdir(exist_ok=True)
    (work / "q6_answer.md").write_text(block + "\n")  # the same block as a file, in case a long-running exec result is lost
    print(json.dumps({"engine_receipt": json.loads(os.environ["ACCELERATE_ENGINE"]), "as_of": q2["as_of"],
                      "universe": "12 most liquid issuers (liquidity_rank 1..12)", "status": "PROPOSED_FOR_REVIEW",
                      "review_first": review_first, "answer_block_markdown": block, "answer_block_file": "work/q6_answer.md",
                      "table_12_issuers": table,
                      "note": "Reasons to look only, from data analysed here; the order is the number of reasons, then liquidity. "
                              "Human confirmations are pending. Not investment advice, and no issuer filed anything."},
                     indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


if __name__ == "__main__":
    main()
