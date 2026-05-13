---
name: tavily-web-research
description: Search the live web and extract page content through Tavily when mirrored data is missing, stale, or too narrow.
---

# tavily-web-research

Use this skill when the user needs current external web information that is not
available through the mirrored GitHub/forum ETLs or the Slack/Outlook channels.

## When to use

- Live web research
- News checks
- Domain-filtered web lookups
- Extracting clean content from one or more URLs

## Access model

- Use the helper script in this skill.
- Do not hand-write Tavily requests unless the user explicitly asks for raw API calls.
- The API key is provided via the OpenShell provider pipeline as `TAVILY_API_KEY`.

## Required Environment

- `TAVILY_API_KEY`
- optional `TAVILY_API_BASE_URL` (defaults to `https://api.tavily.com`)

## Procedure

Always run these commands via the terminal tool.

### 1. Search the web

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/tavily-web-research/scripts/query_tavily.py \
  search --query "OpenShell gateway docs" --max-results 5 --include-answer basic
```

Useful variants:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/tavily-web-research/scripts/query_tavily.py \
  search --query "latest OpenShell release" --topic news --time-range week --max-results 5

/usr/bin/python3 /sandbox/.hermes-data/skills/tavily-web-research/scripts/query_tavily.py \
  search --query "Tavily OpenClaw integration" --include-domain docs.tavily.com --include-answer advanced
```

### 2. Extract page content

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/tavily-web-research/scripts/query_tavily.py \
  extract --url https://docs.nvidia.com/openshell/get-started/quickstart
```

Useful variants:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/tavily-web-research/scripts/query_tavily.py \
  extract --url https://docs.nvidia.com/openshell/get-started/quickstart \
  --query "gateway install" --chunks-per-source 3
```

## Pitfalls

- Prefer the mirrored ETL skills for repo/forum history when they contain the needed data.
- Tavily is live web access, so results can drift over time.
- Domain filters and advanced options cost more latency and may consume more credits.
