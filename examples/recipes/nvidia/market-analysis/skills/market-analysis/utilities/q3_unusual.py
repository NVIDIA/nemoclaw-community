#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Question 3 helper: the ten most unusual issuer sessions by per-issuer baseline z-scores, as JSON.

  python3 utilities/accelerate.py run utilities/q3_unusual.py

Baseline 2026-01-02..2026-06-30: mean and sample std (ddof=1) of each feature per issuer. Score sessions
2026-07-01..2026-08-31 on total_return_1d, intraday_range ((high - low) / open) and volume. Session score = max abs z of
the three; dominant feature = the one with the largest abs z. All 36 issuers, the ten largest (issuer, session) rows
(not one per issuer). A news item published the same UTC date is listed as an association, not a cause.
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


def main():
    if not os.environ.get("ACCELERATE_ENGINE"):
        sys.exit("blocked: run this helper with `python3 utilities/accelerate.py run utilities/%s` so the engine receipt exists. "
                 "Do not run it with plain python3 or install packages; report the analysis as blocked if accelerate.py cannot run." % Path(__file__).name)
    prices = pd.read_csv(DATA / "daily_prices.csv")
    news = pd.read_csv(DATA / "company_news.csv")
    prices["intraday_range"] = (prices.high - prices.low) / prices.open
    feats = {"return": "total_return_1d", "intraday_range": "intraday_range", "volume": "volume"}
    base = prices[(prices.trading_date >= "2026-01-02") & (prices.trading_date <= "2026-06-30")]
    score = prices[(prices.trading_date >= "2026-07-01") & (prices.trading_date <= AS_OF)].copy()
    stats = base.groupby("asset_id")[list(feats.values())].agg(["mean", "std"])
    for name, col in feats.items():
        score[f"z_{name}"] = (score[col] - score.asset_id.map(stats[(col, "mean")])) / score.asset_id.map(stats[(col, "std")])
    z = score[[f"z_{n}" for n in feats]]
    score["score"] = z.abs().max(axis=1)
    score["dominant_feature"] = z.abs().idxmax(axis=1).str[2:]
    top = score.sort_values("score", ascending=False).head(10)
    news["date"] = news.published_at.str[:10]
    rows = []
    for rank, r in enumerate(top.itertuples(), 1):
        same = news[(news.primary_asset_id == r.asset_id) & (news.date == r.trading_date)]
        rows.append({"rank": rank, "asset_id": r.asset_id, "trading_date": r.trading_date, "score": round(float(r.score), 2),
                     "dominant_feature": r.dominant_feature, "z_return": round(float(r.z_return), 2),
                     "z_intraday_range": round(float(r.z_intraday_range), 2), "z_volume": round(float(r.z_volume), 2),
                     "same_day_news": [{"news_id": n.news_id, "published_at": n.published_at, "headline": n.headline,
                                        "event_type": n.event_type, "sentiment_label": n.sentiment_label} for n in same.itertuples()]})
    emit({"baseline": "2026-01-02..2026-06-30", "scored": f"2026-07-01..{AS_OF}", "issuers": int(score.asset_id.nunique()),
          "sessions_scored": int(len(score)), "top_ten": rows,
          "note": "z-scores against each issuer's own baseline; an anomaly score is neither a forecast nor an explanation."})


if __name__ == "__main__":
    main()
