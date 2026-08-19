---
title:
  page: "Policy-Scoped Public Web Search"
  nav: "Public Web Search"
description:
  main: "Enable optional Tavily search for Hermes while keeping the API key outside the sandbox and blocking page extraction, direct URL fetching, browser automation, and unrestricted egress."
  agent: "Setup, security-boundary, verification, failure, rotation, and teardown guidance for the developer-community-chief-of-staff recipe's optional Tavily web_search integration. Use when enabling or diagnosing policy-scoped public-web discovery."
keywords: ["nemoclaw web search", "tavily search", "openshell policy", "hermes web_search"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "tavily", "security", "web-search"]
content:
  type: how_to
  difficulty: intermediate
  audience: ["developer", "engineer"]
status: published
---

<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

![NVIDIA](../assets/nvidia_header.png)

# Policy-Scoped Public Web Search

This recipe can add current public-web discovery through Tavily. The feature is
optional and disabled by default. It exposes Hermes's native `web_search` tool,
not a browser or general HTTP client.

| Configuration | Provider attachment | Tavily network policy | Slack tool surface |
| --- | --- | --- | --- |
| `TAVILY_API_KEY` empty or absent | none | none | `search` toolset omitted |
| `TAVILY_API_KEY` configured | `<sandbox>-tavily-search` | `POST api.tavily.com/search` from Hermes Python only | `web_search` available |

## Security Boundary

The host `.env` holds the raw Tavily API key. During bring-up, OpenShell stores
the key in the gateway provider record. Hermes receives the placeholder
`openshell:resolve:env:TAVILY_API_KEY`. The OpenShell proxy rewrites that
placeholder in the JSON `api_key` field only after the request passes the
provider and sandbox policy checks.

The allowed request is exact:

```text
binary: /opt/hermes/.venv/bin/python
method: POST
host:   api.tavily.com
path:   /search
```

The integration does not allow:

- `POST /extract` or any other Tavily route;
- `web_extract`, `web_fetch`, browser automation, or direct page reads;
- arbitrary URLs or hosts;
- `curl`, `wget`, system Python, or a custom HTTP helper for Tavily egress;
- the raw API key in sandbox files, logs, tool results, or agent responses.

Search results can include titles, URLs, snippets, scores, and provider
metadata. They do not prove the full contents of a result page. The
`public-web-search` skill requires a source URL next to each result-derived
claim and forbids fetching that URL.

## Enable Search

1. Create a Tavily API key at <https://app.tavily.com>.
2. Add it to the recipe's host `.env`:

   ```env
   TAVILY_API_KEY=<your-tavily-api-key>
   ```

3. Keep the file owner-only:

   ```console
   $ chmod 600 .env
   ```

4. Run the read-only checks. External mode sends one bounded search request
   with `max_results=1`; it does not print the API key or the response body.

   ```console
   $ python3 scripts/preflight.py
   $ python3 scripts/preflight.py --external
   ```

5. Recreate an existing sandbox so the provider, policy, immutable Hermes
   configuration, and tool disclosure agree:

   ```console
   $ bash scripts/tear-down.sh
   $ bash scripts/bring-up.sh
   ```

For a first deployment, run `bash scripts/bring-up.sh` after preflight. If you
must preserve Hermes sessions, memories, or learned skills, run
`bash scripts/snapshot.sh` before tear-down and `bash scripts/restore.sh` after
bring-up.

Provider setup stops before sandbox creation if Tavily rejects the key or the
bounded request cannot reach the service. The error reports only a category or
HTTP status. It does not include the key or Tavily response body.

## Verify Enabled Search

First confirm that OpenShell attached the expected provider and policy:

```console
$ set -a; . ./.env; set +a
$ openshell provider get "${SANDBOX_NAME:-hermes-direct}-tavily-search"
$ openshell policy get "${SANDBOX_NAME:-hermes-direct}" | \
    grep -E 'api\.tavily\.com|path: /search|/opt/hermes/\.venv/bin/python'
```

Confirm that the sandbox sees a placeholder or no environment value. This
command prints only a classification and never the value:

```console
$ openshell sandbox exec --name "${SANDBOX_NAME:-hermes-direct}" -- sh -c '
  case "${TAVILY_API_KEY:-}" in
    openshell:resolve:env:*) echo placeholder ;;
    "") echo absent ;;
    *) echo raw-value-present >&2; exit 1 ;;
  esac'
```

Send this request to the agent through a configured messaging channel:

> Search the public web for the latest official NVIDIA NemoClaw announcement.
> Return the top three titles, source URLs, snippets, and search metadata. Do
> not open or extract any result page.

A successful response uses `public-web-search`, calls `web_search`, cites each
returned URL, and does not claim that it read the pages.

## Verify Blocked Paths

These checks use the same Hermes Python binary as `web_search`. They should
report `403` or a proxy denial.

An arbitrary host remains blocked:

```console
$ openshell sandbox exec --name "${SANDBOX_NAME:-hermes-direct}" -- \
    /opt/hermes/.venv/bin/python -c \
    'import urllib.request; urllib.request.urlopen("https://example.com", timeout=5)'
```

Tavily extraction remains blocked even with a resolver placeholder:

```console
$ openshell sandbox exec --name "${SANDBOX_NAME:-hermes-direct}" -- \
    /opt/hermes/.venv/bin/python -c '
import json, urllib.request
request = urllib.request.Request(
    "https://api.tavily.com/extract",
    data=json.dumps({"api_key": "openshell:resolve:env:TAVILY_API_KEY", "urls": ["https://example.com"]}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
urllib.request.urlopen(request, timeout=5)
'
```

Do not replace these probes with a raw API key. The placeholder is enough to
test the route decision, and the request must fail before credential rewriting.

## Verify Disabled Search

To disable the feature, remove or empty `TAVILY_API_KEY`, then recreate the
sandbox. Local preflight must report:

```text
[SKIP] [optional] public web search: disabled; no Tavily provider or network policy will be attached
```

These commands must not find an attached provider or Tavily policy:

```console
$ openshell provider get "${SANDBOX_NAME:-hermes-direct}-tavily-search"
$ openshell policy get "${SANDBOX_NAME:-hermes-direct}" | grep api.tavily.com
```

Ask the agent for a public-web search. It must say that public web search is
disabled and give the host configuration and sandbox-recreation action. It
must not try another tool, binary, host, or route.

## Rotate or Remove the API Key

Provider selection and Hermes configuration are sandbox-creation inputs. To
rotate or remove the key, update `.env`, then run:

```console
$ bash scripts/tear-down.sh
$ bash scripts/bring-up.sh
```

`tear-down.sh` deletes `<sandbox>-tavily-search` with the other per-sandbox
providers. It does not delete the key from the host `.env`; remove that line
separately when you no longer need it.
