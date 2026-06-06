---
name: sec-company-facts
description: Resolve public-company tickers to CIKs and summarize selected SEC company facts from data.sec.gov.
---

# sec-company-facts

Use this skill when a user asks for SEC filing context, company-facts data, or
basic financial statement metrics for a US public company.

This skill is for research context only. Do not treat it as audited analysis by
itself, and do not give investment advice.

## Access Model

Use the helper script in this skill. It calls SEC public JSON endpoints with a
descriptive User-Agent and returns structured JSON.

Set `SEC_USER_AGENT` in the sandbox when using this seriously:

```bash
export SEC_USER_AGENT="Your Name your.email@example.com"
```

## Procedure

### 1. Resolve a ticker

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/sec-company-facts/scripts/sec_company_facts.py lookup NVDA
```

### 2. Pull a compact facts summary

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/sec-company-facts/scripts/sec_company_facts.py facts NVDA
```

### 3. Explain the result carefully

Use concise accounting language:

- identify the company and CIK
- list the metric, unit, form, fiscal period, filing date, and value
- separate reported facts from your own interpretation
- say when a metric is unavailable

## Pitfalls

- Company facts can contain multiple units and forms. Prefer the latest filed
  10-K or 10-Q fact for simple summaries.
- SEC data is not a substitute for reading the full filing.
- Do not invent missing values or fiscal periods.
