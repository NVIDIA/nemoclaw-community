---
name: financial-analyst-brief
description: Produce concise analyst briefs by combining market snapshots, SEC company facts, and user-provided assumptions.
---

# financial-analyst-brief

Use this skill when a user asks for a concise financial analyst brief, watchlist
memo, earnings prep note, or "what should I look at next?" summary.

This skill is not for personalized investment advice. Do not recommend that the
user buy, sell, short, hold, or trade securities.

## Inputs

Use the source skills that match the question:

- `financial-market-snapshot` for public quote context
- `sec-company-facts` for SEC company facts
- user-provided assumptions, watchlist, catalysts, or portfolio context

## Procedure

### 1. Clarify the scope only when needed

If the user gives tickers and an ask, proceed. If the request is vague, ask for
the ticker list or time horizon.

### 2. Gather the smallest useful evidence

For a simple ticker brief:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/financial-market-snapshot/scripts/finance_snapshot.py quote NVDA
/usr/bin/python3 /sandbox/.hermes-data/skills/sec-company-facts/scripts/sec_company_facts.py facts NVDA
```

### 3. Separate facts from interpretation

Use this structure by default:

- **Snapshot:** price/volume/day range context and data timestamp
- **Fundamentals:** selected SEC facts with fiscal period and filing date
- **Why It Matters:** two or three implications framed as hypotheses
- **Checks Before Acting:** filings, guidance, valuation, peer comparison,
  macro/sector catalyst, and data freshness
- **Caveat:** not investment advice; delayed/public data only

### 4. Keep it brief

Aim for one screen unless the user asks for a fuller memo.

## Pitfalls

- Do not pretend public quote snapshots are live.
- Do not present a valuation conclusion without the required assumptions.
- Do not hallucinate earnings dates, guidance, consensus estimates, ratings, or
  target prices unless a source was checked.
- Do not provide personalized financial advice.
