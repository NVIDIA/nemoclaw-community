#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Question 1 helper: table inventory, reconciliation checks and 20-session median return by sector, as JSON.

  python3 utilities/accelerate.py run utilities/q1_inventory.py

Plain pandas, so it runs under accelerate.py (CUDA-X on a GPU sandbox). Copy the numbers from the JSON. It also asks Auto Ontology
the sector question (`auto_ontology`: `blocked` with the message when the service is not installed; it can take minutes
when it is) so rule 10 is applied whether or not the agent remembers it; `--no-ontology` skips the call for offline tests. Rows after
the as-of date are counted by full timestamp: prices after 2026-08-31, news published after the 2026-08-31 close
(trading_sessions.close_at, 21:00 UTC), sessions after 2026-08-31.
"""
import json
import os
import subprocess
import sys
import time
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


# Count question only: the deployment tested for this recipe answers it but not the median question (README, Auto Ontology),
# so the sector medians below are always computed from the CSVs.
MAX_ATTEMPTS = 3
TOTAL_BUDGET_SECONDS = 1200
MIN_RETRY_SECONDS = 240
ONTOLOGY_QUESTION = "How many issuers are in each sector as of 2026-08-31?"


def ask_ontology_once(timeout):
    script = Path(__file__).with_name("ontology_qa.py")
    try:
        done = subprocess.run([sys.executable, "-S", "-I", str(script), "--question", ONTOLOGY_QUESTION],  # -S: the cuML .pth hook must not start in this stdlib-only child
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "blocked", "message": "blocked: the Auto Ontology call timed out after %d seconds" % timeout}
    if done.returncode != 0:
        return {"status": "blocked", "message": (done.stderr.strip().splitlines() or ["blocked: no message"])[-1]}
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        return {"status": "blocked", "message": "blocked: Auto Ontology returned output that is not JSON"}
    status = "answered" if answer.get("answered_with_sql") else ("no_rows" if answer.get("sql") else "no_sql")
    return {"status": status, "answer": answer,
            "check": "Quote the sql, say it is an Auto Ontology answer, and compare it with the issuers count per sector in sector_median_20_session_return below. The medians are computed from the CSVs, not by Auto Ontology."}


def ask_ontology():
    """Always asks Auto Ontology (utilities/ontology_qa.py), so the question cannot be skipped. Never raises: an
    unavailable service is a `blocked` entry, quoted as is, and the numbers below come from the CSVs either way.
    The deployment writes its SQL fresh each time and sometimes emits table names SQLite rejects, so an answer with no SQL
    (`no_sql`) or with SQL but no result rows (`no_rows`) is retried, at most MAX_ATTEMPTS calls within one 1,200 second
    budget; `blocked` is not retried."""
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    result, attempts = None, 0
    while attempts < MAX_ATTEMPTS:
        remaining = int(deadline - time.monotonic())
        if attempts and remaining < MIN_RETRY_SECONDS:
            break
        attempts += 1
        result = ask_ontology_once(remaining)
        if result["status"] not in ("no_sql", "no_rows"):
            break
    result["attempts"] = attempts
    answer = result.get("answer") or {}
    note = "" if attempts == 1 else " (%d attempts)" % attempts
    result["trace_markdown"] = (answer.get("trace_markdown") or "**Auto Ontology SQL:** none. %s"
                                % result.get("message", "")) + note
    return result


def main():
    if not os.environ.get("ACCELERATE_ENGINE"):
        sys.exit("blocked: run this helper with `python3 utilities/accelerate.py run utilities/%s` so the engine receipt exists. "
                 "Do not run it with plain python3 or install packages; report the analysis as blocked if accelerate.py cannot run." % Path(__file__).name)
    assets = pd.read_csv(DATA / "assets.csv")
    prices = pd.read_csv(DATA / "daily_prices.csv")
    sessions = pd.read_csv(DATA / "trading_sessions.csv")
    news = pd.read_csv(DATA / "company_news.csv")
    rel = pd.read_csv(DATA / "asset_relationships.csv")
    cutoff = pd.Timestamp(sessions.loc[sessions.trading_date == AS_OF, "close_at"].iloc[0])
    published = pd.to_datetime(news.published_at, utc=True)
    per_issuer = prices.groupby("asset_id").size()
    ids = set(assets.asset_id)
    rows = {}
    for sector, group in assets.groupby("sector"):
        rets = []
        for asset in group.asset_id:
            s = prices[prices.asset_id == asset].sort_values("trading_date").adjusted_close.to_numpy()
            rets.append(s[-1] / s[-21] - 1)
        rows[sector] = {"issuers": len(group), "median_20_session_return": round(float(np.median(rets)), 4)}
    emit({
        "auto_ontology": None if "--no-ontology" in sys.argv else ask_ontology(),
        "as_of": AS_OF,
        "tables": {"assets": len(assets), "daily_prices": len(prices), "trading_sessions": len(sessions),
                   "company_news": len(news), "asset_relationships": len(rel)},
        "issuer_count": int(len(assets)),
        "checks": {
            "duplicate_price_keys": int(prices.duplicated(["asset_id", "trading_date"]).sum()),
            "orphan_price_rows": int((~prices.asset_id.isin(ids)).sum()),
            "orphan_news_rows": int((~news.primary_asset_id.isin(ids)).sum()),
            "orphan_relationship_rows": int((~rel.source_asset_id.isin(ids) | ~rel.target_asset_id.isin(ids)).sum()),
            "issuers_missing_sessions": sorted(per_issuer[per_issuer != len(sessions)].index.tolist()),
            "price_rows_after_as_of": int((prices.trading_date > AS_OF).sum()),
            "sessions_after_as_of": int((sessions.trading_date > AS_OF).sum()),
            "news_after_as_of_close": int((published > cutoff).sum()),
            "as_of_close": str(cutoff),
            "latest_news_published_at": news.published_at.max(),
            "latest_price_date": prices.trading_date.max(),
        },
        "sector_median_20_session_return": rows,
    })


if __name__ == "__main__":
    main()
