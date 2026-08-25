---
name: public-web-search
description: "Search the current public web through the recipe's optional, policy-scoped Tavily integration and return cited titles, URLs, snippets, and search metadata. Use for current public information that is not available from the configured Slack, Outlook, GitHub, or source-ETL skills. Do not use for opening a result page, extracting a URL, browser automation, or arbitrary HTTP requests."
license: "Apache-2.0"
---

# Public Web Search

Use Hermes's native `web_search` tool for current public-web discovery. Treat
each result as search-provider evidence, not as verified page text.

## Enforced boundary

- Use `web_search` only. Do not use `web_extract`, a browser tool, `web_fetch`,
  `curl`, `wget`, Python HTTP code, or a user-supplied URL as a fetch target.
- The OpenShell provider and sandbox policy permit only `POST /search` on
  `api.tavily.com` from Hermes's pinned Python runtime.
- Do not inspect, print, transform, or troubleshoot `TAVILY_API_KEY`. The
  sandbox receives an OpenShell placeholder, not the raw API key.
- Do not claim that a snippet proves facts beyond the returned title, URL,
  snippet, score, or other search metadata.

## Search procedure

1. Convert the request into one focused search query. Add a date, product name,
   or official-domain qualifier when it improves precision.
2. Call `web_search`. Do not follow result URLs with another tool.
3. Prefer primary and authoritative sources in the returned results.
4. Cite the returned URL next to every claim that depends on a result. Label a
   statement as a search-result snippet when the page itself was not read.
5. If the tool is absent or reports that Tavily is unavailable, stop. Say:
   `Public web search is disabled for this sandbox. Configure TAVILY_API_KEY on
   the host, then recreate the sandbox.` Do not try another network path.

## Output

Return a compact result list with the title, source URL, snippet, and useful
provider metadata. Separate direct result metadata from your inference.
