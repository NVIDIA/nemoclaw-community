# GPU portfolio fixture

`datacenter_gpu_portfolio.csv` is a demo fixture transcribed from the supplied portfolio table. It is not a verified or current NVIDIA specification sheet. The task uses only the supplied numbers, without external research.

The CSV keeps the unambiguous TDP, form factor, memory and connectivity fields. Throughput columns were omitted because the pasted source merges some numbers with footnote markers. The trailing footnote `1` was removed from `Vera Rubin NVL721` and `HGX Rubin NVL81`; no TDP values were changed. Missing connectivity is labeled `None listed`, rather than interpreted as a verified hardware limitation.

`max_single_gpu_tdp_w` is a numeric, configurable upper limit in watts per GPU. Do not multiply it by rack or module GPU counts, interpret it as measured power, or sort its text representation. For equal values, retain source row order. The expected five rows are:

| Product | Maximum single-GPU TDP (W) |
| --- | ---: |
| Vera Rubin NVL72 | 2300 |
| HGX Rubin NVL8 | 2300 |
| GB300 NVL72 | 1400 |
| GB200 NVL72 | 1200 |
| GB200 NVL4 | 1200 |

Suggested skills: **Data interpretation + Coding**. The analyst saves a brief and the top-five CSV; the programmer consumes that handoff and builds a self-contained HTML dashboard with a TDP chart, portfolio comparison table and three findings. Suitable hires can fill both steps in Hired only; **Ada + Cody** can fill them in Hired + Standby. Web research is unnecessary.

Useful checks for the analysis and webpage:

- Preserve the ranking above in the chart and saved five-row CSV. The full portfolio comparison has 11 products.
- Normalize bandwidth: 800 GB/s = 0.8 TB/s; 300 GB/s = 0.3 TB/s (decimal units). Retain memory capacity and TDP upper-limit qualifiers.
- At the same maximum 600 W, RTX PRO 6000 BSE lists 96 GB and 1.6 TB/s; H200 NVL lists 141 GB and 4.8 TB/s. These are memory differences, not proof of workload performance or energy efficiency.
- The supplied TDP range is 72-2300 W per GPU; four products are at or below 600 W. Findings can vary, but every number and comparison must trace to the CSV.
- Verify actual attachment reading, both specialists being called in order, the analyst's saved handoff being used by the programmer, and final page/CSV consistency. Analyst-only completion is not full success for this scenario; missing Coding must not be bypassed by the analyst. A completion label is insufficient. Missing Data interpretation must likewise not be bypassed by a Coding-only hire.
