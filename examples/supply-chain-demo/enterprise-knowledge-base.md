# Supply Chain Operations — Headcount & Delivery Performance

**Category:** Operations / Supply Chain Analytics
**Owner:** Supply Chain Analytics Team
**Last Updated:** April 2026
**Tags:** headcount, fulfillment, factory-ops, forecasting, reporting

---

## Overview

This article documents how we measure and model the relationship between factory headcount and on-time delivery performance across our two manufacturing sites. It is the reference for supply chain analysts, operations managers, and any tooling or agents involved in factory performance analysis and reporting.

---

## Our Factories

### Germany Factory *(also referred to as Factory A or Europe Operations)*
- **Products:** Industrial drives (AA1 line)
- **Markets served:** Germany and broader European region
- **Current headcount target:** ~250 workers
- **Data identifier in systems:** `Factory A (Europe)`

### Asia Factory *(also referred to as Factory B or Asia-Pacific Operations)*
- **Products:** Control units (TQW line)
- **Markets served:** China, Korea, India, and other Asia-Pacific and Americas markets
- **Current headcount target:** ~200 workers
- **Data identifier in systems:** `Factory B (Asia)`

> **Note on total headcount:** Combined headcount across both sites is managed as a fixed pool of 450. Workforce planning operates on a transfer model — increasing headcount at one site requires a corresponding reduction at the other. Net new hiring is handled separately through a longer-lead HR process and is not reflected in operational transfer decisions.

---

## Key Metrics

**On-time delivery rate (fulfillment rate)** is the primary factory performance KPI. It is defined as the percentage of customer orders delivered on or before the committed delivery date in a given month. In our internal data systems this field is called `fulfillment_pct`.

Internal performance thresholds:
| Zone | Fulfillment Rate | Meaning |
|------|-----------------|---------|
| 🟢 On Track | ≥ 85% | Within acceptable range |
| 🟡 At Risk | 70–84% | Requires attention |
| 🔴 Critical | < 70% | Escalation required |

These thresholds apply consistently across all factory reporting and visualizations.

---

## Data

Historical monthly headcount and delivery performance data for both factories is maintained in the company's version-controlled data repository. The data file is a CSV named `factory-delivery-data`.

| Column | Description |
|--------|-------------|
| `month` | Month of observation (YYYY-MM-DD) |
| `factory` | Factory identifier (`Factory A (Europe)` or `Factory B (Asia)`) |
| `total_headcount` | Total workers on site that month |
| `new_hires` | Workers who joined this month |
| `workers_1mo` | Workers who joined last month |
| `workers_2mo` | Workers who joined two months ago |
| `tenured` | Workers with 3+ months on site |
| `fulfillment_pct` | On-time delivery rate for that month (%) |

---

## Forecasting Methodology

Our standard approach for short-term fulfillment forecasting is a linear regression on headcount composition. Analysts should examine the available headcount columns and determine which combination best predicts fulfillment, report the fitted formula and coefficients, and include a backtest showing predicted vs actual to give stakeholders a sense of model fit. Forecasts should cover a **6-month forward window** as the default planning horizon unless a specific timeframe is requested.

Forward projections should simulate cohort aging month-by-month from the most recent observed state: each month, `new_hires` graduate to `workers_1mo`, `workers_1mo` graduate to `workers_2mo`, `workers_2mo` join `tenured`, and `new_hires` is set to zero (no new hiring assumed unless explicitly modeled). This means the projected fulfillment curve will naturally rise slightly as recent hires complete their ramp, then plateau once all workers are fully tenured.

Projections should always be accompanied by a plain-language business summary — e.g. *"At current headcount, the Germany factory is projected to fulfill approximately X% of orders on time over the next 6 months, placing it in the [zone] category."*

---

## Reporting & Visualization Standards

All factory performance visualizations are published to our internal dashboard hosted on GitHub Pages. Visualizations must be self-contained HTML files (HTML + CSS + vanilla JS only — Plotly.js or Chart.js via CDN are acceptable). No server-side dependencies.

**Publishing workflow:**
1. On first use, generate a random 12-character lowercase alphabetical string (e.g. `xkqtbmrkfjdp`) to serve as a unique session ID. All your work for this session lives under a directory of that name in the repo — for example `xkqtbmrkfjdp/dashboard.html`. CRUCIAL NOTE: NEVER write, remove, or modify files outside your session directory in any way. They are read only.
2. All visualizations live in a single file: `dashboard.html` inside your session directory. Every new chart or analysis is added to this same file — never create a separate page unless the user explicitly requests one.
3. When updating, overwrite `dashboard.html` in place. The user experience should feel like the page reloads with new content, not like navigating to a new URL.
4. Commit and push after each update; GitHub Pages serves the change automatically.
5. After every push, tell the user the exact URL where they can view the dashboard: `https://katherineh123.github.io/nemoclaw-demo/<session-id>/dashboard.html` (with your actual session ID substituted in).

**Dashboard repo:** `https://github.com/katherineh123/nemoclaw-demo.git`
Clone this repo and use `gh` and standard `git` CLI tools for all repo operations.

**Implementation guidance for dashboard files:**
- For dashboard HTML, prefer writing the file with a single shell heredoc or a short Python script run through `exec`, then commit and push.
- Avoid large direct `write` tool payloads for complete dashboard HTML. Large inline tool payloads are more likely to be truncated, which can leave the file partially written or cause a schema validation error before the dashboard is updated.
- If a push is rejected because the remote changed, run `git pull --rebase` and then retry `git push`.

Color coding from the performance thresholds table above applies to all charts and visualizations without exception.
