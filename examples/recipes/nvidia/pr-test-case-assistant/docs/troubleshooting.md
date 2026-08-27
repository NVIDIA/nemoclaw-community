<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Troubleshooting

Use the current
[NemoClaw troubleshooting guide](https://docs.nvidia.com/nemoclaw/latest/reference/troubleshooting.html)
for installation and runtime failures. This page covers behavior specific to
this recipe.

## Slack

| Symptom | Check |
| --- | --- |
| `check-slack-tokens.sh` rejects a token | The bot token must begin with `xoxb-`; the app-level Socket Mode token must begin with `xapp-`. |
| The app is installed but does not receive messages | Confirm Socket Mode and event subscriptions are enabled, then run `bash scripts/start.sh` and wait for the Slack readiness result. |
| A direct message returns a pairing code | Run `bash scripts/slack-pair.sh approve <code>` on the host, or set `SLACK_ALLOWED_USERS` before onboarding. |
| A shared Slack app stops responding elsewhere | One app-level token supports one active Socket Mode connection. Use a dedicated Slack app for this recipe. |

## GitHub

| Symptom | Check |
| --- | --- |
| GitHub is denied by policy | Reapply the recipe policy with `bash scripts/install.sh`, then inspect denials with `openshell term`. |
| GitHub returns a rate-limit error | Wait for the public quota to reset. The sandbox intentionally has no GitHub token. |
| A file has no patch text | GitHub can omit patches for binary files or large changes. The assistant must report that limitation. |
| The assistant cites an unfamiliar identifier | Run the host-side `verify-grounding.py` command from the README against the cited names. |

## Inference

| Symptom | Check |
| --- | --- |
| Onboarding asks for an NVIDIA key | Set `NVIDIA_INFERENCE_API_KEY` in `.env`. `NVIDIA_API_KEY` is also accepted by supported NemoClaw releases as a legacy alias. |
| The selected model or provider is unavailable | Set `NEMOCLAW_PROVIDER` and `NEMOCLAW_MODEL` in `.env` to values supported by your NemoClaw installation, then onboard again. |

Do not disable TLS verification, broaden the GitHub policy to all methods, or
copy a personal GitHub token into the sandbox as a shortcut.
