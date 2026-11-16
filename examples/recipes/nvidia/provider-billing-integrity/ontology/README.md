<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Auto Ontology deployment notes (stage 4)

The sandbox side of stage 4 is in the skill (`utilities/ontology_qa.py`) and
`providers/auto-ontology.yaml`. This file records what the host-side deployment
has to look like and what was learned while verifying it (2026-11-13 to 2026-11-16).
Nothing here is installed.

## What the deployment needs

- A running Auto Ontology with the provider-billing database loaded and the
  semantic layer compiled (`GET /api/semantic-compilation/status` returns
  `calculated: true` and `running: false`).
- An API token minted for it. The recipe sends it as `x-api-key`.
- The deployment's **web port** reachable from the sandbox as
  `host.openshell.internal:<port>`. The `/api/*` routes are served on the web
  port; the backend port answers only a health check.
- Hosted model access for its own text-to-SQL pipeline. That traffic is the
  deployment's, not the sandbox's.

## Timeout problem and local patch

Two builds were tried.

- The deployed build `cdaf61e1`: coverage and chat timed out. The deployment log
  showed `unknown field guided_json` (HTTP 400). That error is only the last of
  three request shapes the `langchain-nvidia-ai-endpoints` client tries, and
  the client reports only the final failure. The first two shapes failed on a
  120-second read timeout from the reasoning model `nemotron-3-ultra-550b-a55b`,
  which thinks for a long time before answering a structured-output request.
  An earlier note here attributed the failure to a request shape the hosted API
  rejects; that was incomplete.
- Upstream `main` (`22e22c89`), run as a separate compose project: coverage
  returned HTTP 500 after 224 to 300 seconds; chat returned 200 in 159 seconds
  with the right rows.
- Upstream plus a local patch to `auto_ontology/utils/llm_invoke.py`: coverage 200
  in 5.8 seconds, chat 200 in about 53 seconds, no `guided_json` errors in the log.

The patch has two changes: the client's timeout follows `LLM_INVOKE_TIMEOUT_S`,
and the reasoning pass is switched off for structured-output calls. Which one
matters was not tested separately, and the patch is not included here.

## Result against the patched build

Question "Which providers share a bank account with provider P001?": coverage
1.0, a self-join on `providers.bank_account_id` excluding P001, rows P002 to
P006, matching the SQLite file (B901 is shared by P001 to P006). From the
sandbox the call took about 45 seconds. An OpenClaw agent run with the skill's
rules reported the same five providers and quoted the SQL.

## Not yet done

- A build that does not need the local patch.
- Questions the semantic layer should decline, and measuring whether the agent
  catches wrong SQL.
