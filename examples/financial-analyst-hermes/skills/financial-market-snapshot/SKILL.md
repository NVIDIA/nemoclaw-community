---
name: financial-market-snapshot
description: Pull public market snapshots for a small ticker list and summarize price, volume, and day range context.
---

# financial-market-snapshot

Use this skill when a user asks for a lightweight market snapshot, watchlist
check, ticker context, or a starting point for an analyst brief.

This skill is for research context only. Do not present the output as real-time
market data, investment advice, or a trading recommendation.

## Access Model

Use the helper script in this skill. It queries a public chart endpoint and
returns structured JSON. Prefer the helper over ad hoc web scraping.

## Procedure

### 1. Pull a snapshot

Run the helper from inside the sandbox:

```bash
/usr/bin/python3 /sandbox/.hermes/skills/financial-market-snapshot/scripts/finance_snapshot.py quote NVDA MSFT AAPL
```

For a saved watchlist:

```bash
/usr/bin/python3 /sandbox/.hermes/skills/financial-market-snapshot/scripts/finance_snapshot.py watchlist --file /sandbox/workspace/watchlist.txt
```

### 2. Interpret the JSON

Focus on:

- last price
- absolute and percent change, when available
- volume
- open, high, low, close
- timestamp and source

If a field is missing, say it is missing instead of estimating.

### 3. Present the result

Use a compact analyst format:

- scope and source
- ticker table or bullets
- notable moves
- caveats and next checks

## Pitfalls

- The data source can be delayed. Say "public quote snapshot" unless
  the source metadata proves otherwise.
- Do not infer a buy, sell, or hold action from price movement alone.
- Do not use this skill for account balances, orders, or holdings.
