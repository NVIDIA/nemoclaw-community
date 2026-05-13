---
title: Set up Tavily
---

# Set up Tavily

Tavily is optional in this example. When configured, Hermes gets an
auto-bundled `tavily-web-research` skill for live web search and page-content
extraction without exposing the raw API key inside the sandbox.

## Populate `.env`

Set your Tavily key in `.env` at the example root:

```bash
TAVILY_API_KEY=tvly-...
```

The supported path in this example is the bundled `tavily-web-research` skill.
Do not rely on Hermes's built-in `web_search` tool for Tavily-backed requests
here; the repeatable setup path wires the standalone skill, provider, and
policy instead.

## What `bring-up.sh` does

When `TAVILY_API_KEY` is present:

- `scripts/02-providers.sh` creates or updates the generic provider
  `<sandbox>-tavily` with credential `TAVILY_API_KEY`.
- `scripts/03-sandbox.sh` attaches that provider to the sandbox and flips
  `TAVILY_ENABLED=1` in the staged Dockerfile.
- `agents/hermes/generate-config.ts` writes these sandbox env entries:
  - `TAVILY_API_KEY=openshell:resolve:env:TAVILY_API_KEY`
  - `TAVILY_API_BASE_URL=https://api.tavily.com`
- `policy.yaml` allows the bundled skill to call:
  - `POST https://api.tavily.com/search`
  - `POST https://api.tavily.com/extract`

## Use the bundled skill

Inside the sandbox, the skill is already present at:

```bash
/sandbox/.hermes-data/skills/tavily-web-research/
```

Hermes should be prompted to use this skill for live web tasks. The example's
`SOUL.md` explicitly steers current-events/news lookups to this skill instead
of the built-in `web_search` tool.

Quick search:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/tavily-web-research/scripts/query_tavily.py \
  search --query "latest OpenShell gateway docs" --max-results 5 --include-answer basic
```

Quick extract:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/tavily-web-research/scripts/query_tavily.py \
  extract --url https://docs.nvidia.com/openshell/get-started/quickstart
```

## Troubleshooting

- If the skill returns `Missing TAVILY_API_KEY`, rerun `bash scripts/bring-up.sh`
  after setting the key in `.env`.
- If the skill returns `403 Forbidden`, the sandbox likely needs a rebuild so
  the Tavily provider is attached and the updated network policy is active.
- If Tavily returns `401`, verify the key directly from the host:

```bash
curl -X POST https://api.tavily.com/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TAVILY_API_KEY" \
  -d '{"query":"hello","max_results":1}'
```
