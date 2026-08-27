<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Failure Modes

## Distinguish the source

| Symptom | Likely source | Response |
| --- | --- | --- |
| `CONNECT tunnel failed` | OpenShell policy gate | Reapply the recipe policy and inspect host, method, path, and executable in `openshell term`. |
| TLS certificate validation error | Host or network trust configuration | Fix the host or enterprise trust configuration. Do not use `--insecure`. |
| GitHub JSON response describing a rate limit | Public GitHub quota | Stop the request and wait for quota reset. Do not retry in a loop. |
| Slack readiness succeeds but no DM arrives | Slack app settings, event subscriptions, or authorization | Compare the app to the supplied manifest and check pairing or `SLACK_ALLOWED_USERS`. |
| `LLM request failed` with partial content | Inference stream | Treat the answer as incomplete and retry once after checking provider status. |

## Keep requests bounded

Do not list every pull request ref or fetch an entire repository history. Use
the bounded GitHub REST requests in the skill. Large unbounded tool output is
expensive to process and can hide truncation.

## Do not expose hidden reasoning

The assistant must answer directly. It must not narrate internal reasoning,
quote its instructions, reveal API keys or access tokens, or expose sandbox
paths. End a session and investigate if any of that content appears in Slack.

## Check Slack readiness

Use:

```bash
nemoclaw <name> channels status \
  --channel slack \
  --wait \
  --timeout 180 \
  --json
```

The recipe's `scripts/start.sh` runs this command for the configured sandbox.
