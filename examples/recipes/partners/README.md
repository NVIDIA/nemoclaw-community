<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Partner Recipes

Reusable NemoClaw agent workflows contributed by partner organizations, with attribution and implementation guidance preserved from each contributor.

## Examples

| Example | Contributor | Industry | Description |
| --- | --- | --- | --- |
| [x402 Payment Gate](bluetier/x402-payment-gate/README.md) | BlueTier Operations | 💳 Financial Services | Demonstrates a maker-checker gate for x402 payments: a sandboxed agent submits intents, while a host-side Blackwall verdict controls mock signing and settlement before any signature exists. |
| [Retail Assistant](hpe/retail-assistant/README.md) | HPE | 🛍️ Retail/Consumer Packaged Goods | Helps store employees check inventory and sales or request transfers and reorders through role-aware Telegram conversations scoped to their assigned store. |
| [Workday HR assistant with role-scoped tool access](merge/workday-hr-assistant/README.md) | Merge | ✨ Other | Give a NemoClaw agent read access to Workday workers, organizations, and time-off through a Merge Agent Handler Tool Pack that withholds compensation, payslip, and payment tools. |
| [Shrike Security Action Governance](shrike/shrike-security/README.md) | Shrike Security, Inc. | ✨ Other | Governs action-bearing OpenClaw tool calls, including shell commands, SQL, file writes, and web requests. An in-sandbox hook sends action content to Shrike policy before execution and blocks prohibited or approval-required calls. It complements, but does not replace, OpenShell isolation. |
| [Watchtower](tavily/watchtower/README.md) | Tavily | ✨ Other | Tracks what changed across chosen web topics and why it matters, producing scheduled, deduplicated Markdown digests and JSON changelogs with source citations. |
| [Telnyx Inference provider](telnyx/inference-provider/README.md) | Telnyx | ✨ Other | Connects a NemoClaw sandbox to Telnyx Inference through Telnyx's OpenAI-compatible API. |
