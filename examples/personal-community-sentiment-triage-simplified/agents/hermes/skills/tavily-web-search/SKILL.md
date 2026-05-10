---
name: tavily-web-search
description: Search the live web with Tavily for community sentiment, forum posts, docs, blog posts, and external signals relevant to a developer topic.
---

# tavily-web-search

Use this skill when a user asks for community signals that may live outside
Slack and GitHub, especially forum posts, docs, blog posts, release notes,
questions, tutorials, and broad web discussion.

## Access model

- The Tavily API key is available as `openshell:resolve:env:TAVILY_API_KEY`.
- Requests go to `https://api.tavily.com/search`.
- Use the helper script; it keeps output compact and avoids exposing the API key.

## Procedure

### 1. Search Tavily

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/tavily-web-search/scripts/tavily_search.py \
  --query "NemoClaw developer issues forum" \
  --max-results 8 \
  --search-depth advanced
```

Useful options:

| Flag | Description |
|------|-------------|
| `--query TEXT` | Required search query. |
| `--max-results N` | Number of results, default 8. |
| `--search-depth basic|advanced` | Use `advanced` for research questions. |
| `--topic general|news` | Tavily topic, default `general`. |
| `--time-range day|week|month|year|d|w|m|y` | Recency filter when useful. |
| `--include-domains DOMAIN[,DOMAIN]` | Limit search to domains such as `forums.developer.nvidia.com`. |
| `--exclude-domains DOMAIN[,DOMAIN]` | Exclude domains. |
| `--include-answer` | Ask Tavily for a short answer summary. |
| `--include-raw-content` | Include raw page content snippets when deep evidence is needed. |

### 2. Interpret results

The script returns JSON:

```json
{
  "ok": true,
  "query": "NemoClaw developer issues forum",
  "answer": "...",
  "count": 3,
  "results": [
    {
      "title": "Post title",
      "url": "https://...",
      "content": "Short snippet",
      "score": 0.82
    }
  ]
}
```

Use URLs and snippets as leads, not as proof of everything on a page. If the
user asks for high-confidence findings, search narrowly and corroborate with
GitHub/Slack where possible.

## Common queries

```bash
# NVIDIA forum signal for a project/topic
/usr/bin/python3 .../tavily_search.py \
  --query "NemoClaw issues OR questions site:forums.developer.nvidia.com" \
  --include-domains forums.developer.nvidia.com

# Wider web sentiment
/usr/bin/python3 .../tavily_search.py \
  --query "NemoClaw GitHub issue problem error discussion" \
  --search-depth advanced
```

## Pitfalls

- Tavily is live search, not the old hourly ETL mirror. Results may shift over time.
- Do not claim absence from the web based on one query. Say "not observed in this search."
- Use domain filters for forum-specific research; broad queries can bring in weak matches.
