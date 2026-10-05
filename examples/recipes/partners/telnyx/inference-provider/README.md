<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Telnyx. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Telnyx Inference provider

| Catalog field | Value |
| --- | --- |
| Description | Connects a NemoClaw sandbox to Telnyx Inference through Telnyx's OpenAI-compatible API. |
| Industry | ✨ Other |
| Requirements | NemoClaw · Telnyx account with Inference access · Telnyx API key |
| NemoClaw | Unpinned |
| Harness | Unpinned |
| OpenShell | Unpinned |
| Contributor | Telnyx |

This guide shows how to use Telnyx Inference as a custom OpenAI-compatible
inference endpoint for NemoClaw. It does not add a named Telnyx provider to
NemoClaw; it uses the provider configuration supported by the current
NemoClaw installation.

## Telnyx endpoints

Telnyx's OpenAI-compatible base URL is:

```text
https://api.telnyx.com/v2/ai/openai
```

The model catalog is available at
[`GET /v2/ai/openai/models`](https://developers.telnyx.com/api-reference/openai-chat/get-available-models-openai-compatible).
Chat completions are available at
[`POST /v2/ai/openai/chat/completions`](https://developers.telnyx.com/api-reference/openai-chat/create-a-chat-completion-openai-compatible).

Telnyx model IDs are returned by the authenticated model catalog. Use the exact
ID for the model you want to run; do not guess or substitute a nearby model.

## Get a Telnyx API key

Create or manage a Telnyx API key in the
[Telnyx Mission Control Portal](https://portal.telnyx.com/#/api-keys). Keep the
key private and do not commit it to this repository.

## Configure NemoClaw

Set the custom-provider variables in the shell where you will run NemoClaw.
Replace `<model-id>` with an exact model ID returned by the Telnyx catalog.

```bash
export NEMOCLAW_PROVIDER=custom
export NEMOCLAW_ENDPOINT_URL=https://api.telnyx.com/v2/ai/openai
export NEMOCLAW_MODEL=<model-id>
export COMPATIBLE_API_KEY=<your-telnyx-api-key>
```

Then run the normal NemoClaw onboarding flow:

```bash
nemoclaw onboard
```

When NemoClaw asks for the inference provider, select the custom or other
OpenAI-compatible endpoint option and use the values above. The exact prompts
may vary by NemoClaw release.

## Verify the Telnyx route

Before onboarding, verify that the key can discover models and that the chosen
model is present:

```bash
curl --fail --silent --show-error \
  https://api.telnyx.com/v2/ai/openai/models \
  -H "Authorization: Bearer $COMPATIBLE_API_KEY"
```

The response contains the model IDs available to the account. Set
`NEMOCLAW_MODEL` to one of those exact IDs before onboarding.

For the full Telnyx API reference, see the
[OpenAI-compatible chat completions documentation](https://developers.telnyx.com/api-reference/openai-chat/create-a-chat-completion-openai-compatible).

## Notes

- The endpoint requires Bearer authentication.
- The model catalog is account-authenticated and can change as model access changes.
- Telnyx and NemoClaw may support different model capabilities; use the model
  metadata and the Telnyx API documentation for the selected model.
- This guide does not send or include an API key.

