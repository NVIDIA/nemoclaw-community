#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Question 2 helper: the 12 most liquid issuers ranked by 20-session return, daily volatility and news-label table.

  python3 utilities/accelerate.py run utilities/q2_leaders.py

Return = adjusted_close[-1] / adjusted_close[-21] - 1 over the 20 sessions ending 2026-08-31. Volatility = sample
standard deviation (ddof=1) of total_return_1d over exactly those 20 sessions. A news item belongs to the first
session whose close_at is at or after published_at; its 5-session forward return is that session's adjusted close
5 sessions later divided by its own, minus 1; items without 5 later sessions are excluded from the means.
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
    assets = pd.read_csv(DATA / "assets.csv")
    prices = pd.read_csv(DATA / "daily_prices.csv")
    sessions = pd.read_csv(DATA / "trading_sessions.csv").sort_values("trading_date").reset_index(drop=True)
    news = pd.read_csv(DATA / "company_news.csv")
    top = assets[assets.liquidity_rank <= 12].sort_values("liquidity_rank")
    ranking = []
    for _, a in top.iterrows():
        p = prices[(prices.asset_id == a.asset_id) & (prices.trading_date <= AS_OF)].sort_values("trading_date")
        window = p.tail(20)
        ranking.append({"asset_id": a.asset_id, "liquidity_rank": int(a.liquidity_rank), "sector": a.sector,
                        "return_20_sessions": round(float(p.adjusted_close.iloc[-1] / p.adjusted_close.iloc[-21] - 1), 4),
                        "daily_volatility": round(float(window.total_return_1d.std(ddof=1)), 4),
                        "window_first": window.trading_date.iloc[0], "window_last": window.trading_date.iloc[-1],
                        "window_sessions": int(len(window))})
    ranking.sort(key=lambda r: -r["return_20_sessions"])
    for i, r in enumerate(ranking, 1):
        r["rank"] = i

    close_at = pd.to_datetime(sessions.close_at, utc=True)
    news = news.assign(published=pd.to_datetime(news.published_at, utc=True))
    news = news[news.published <= close_at.iloc[-1]]
    idx = np.searchsorted(close_at.to_numpy(), news.published.to_numpy(), side="left")
    news = news.assign(session_idx=idx)
    adj = {a: g.sort_values("trading_date").set_index("trading_date").adjusted_close for a, g in prices.groupby("asset_id")}
    dates = sessions.trading_date.tolist()
    fwd = []
    for row in news.itertuples():
        i = row.session_idx
        if i + 5 >= len(dates) or row.primary_asset_id not in adj:
            fwd.append(np.nan)
            continue
        s = adj[row.primary_asset_id]
        fwd.append(s[dates[i + 5]] / s[dates[i]] - 1)
    news = news.assign(fwd5=fwd)

    def table(frame):
        out = {}
        for label in ("positive", "neutral", "negative"):
            vals = frame[(frame.sentiment_label == label)].fwd5.dropna()
            out[label] = {"items_with_forward_return": int(len(vals)),
                          "mean_5_session_forward_return": round(float(vals.mean()), 4) if len(vals) else None,
                          "items_total": int((frame.sentiment_label == label).sum())}
        return out

    in_top = news.primary_asset_id.isin(top.asset_id)
    emit({"as_of": AS_OF, "universe": "12 most liquid issuers (liquidity_rank 1..12)",
          "ranking_strongest_first": ranking,
          "news_label_table_top12_issuers": table(news[in_top]),
          "news_label_table_all_36_issuers": table(news),
          "note": "Forward-return means exclude items without 5 later sessions. Association, not cause; small sample."})


if __name__ == "__main__":
    main()
