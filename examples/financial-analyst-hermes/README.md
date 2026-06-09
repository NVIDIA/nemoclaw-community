# Financial Analyst Hermes Assistant

A small NemoClaw/NemoHermes example for a financial analyst. It uses a stock
NemoHermes sandbox, a configurable OpenAI-compatible chat API, four installable
Hermes skills, a read-only finance data policy preset, and a streaming
financial desk UI that talks to the Hermes OpenAI-compatible API.

This example is intentionally narrow: public quote snapshots, SEC
company facts, concise analyst briefs, and explicit caveats. It does not connect
to brokerage accounts, place trades, or provide personalized investment advice.

## What It Shows

- `nemohermes onboard` as the main lifecycle command.
- A provider-agnostic API route configured with API URL, API key, and model.
- Hermes skills installed with `nemohermes <sandbox> skill install <path>`.
- A scoped financial skill profile so the model does not load unrelated
  bundled skills into every request.
- Read-only OpenShell/NemoClaw policy for public finance data.
- API access through Hermes on `http://127.0.0.1:8642/v1`.
- A financial desk UI for streaming chat, Outlook-style email prompts, and run
  telemetry.
- Optional Outlook, NeMo Relay, and Phoenix integration scaffolding.
- Brev deployment commands in [docs/brev-deployment.md](docs/brev-deployment.md).

Current NemoClaw docs describe `nemohermes` as the Hermes-selected alias for
NemoClaw. Use `nemohermes <sandbox> dashboard-url --quiet` to discover the
dashboard URL; the OpenAI-compatible API is exposed on port `8642`. See the official
[NemoClaw Hermes quickstart](https://docs.nvidia.com/nemoclaw/latest/user-guide/hermes/get-started/quickstart)
and [NemoClaw inference options](https://docs.nvidia.com/nemoclaw/latest/inference/inference-options.html).

## Repository Layout

```text
examples/financial-analyst-hermes/
  skills/
    financial-market-snapshot/
    sec-company-facts/
    financial-analyst-brief/
    financial-analyst-playbook/
  presets/
    finance-data-readonly.yaml
  scripts/
    install-skills.sh
    configure-finance-skills.sh
    smoke-hermes-api.py
    smoke-compatible-api.py
    finance_ui_server.py
    login-ms-graph.py
    outlook_finance_bridge.py
    setup-outlook-provider.sh
    ui-smoke.mjs
  providers/
    compatible-chat-api.yaml
    outlook-email.yaml
  agents/hermes/
    plugins/nemo-relay/
    nemo-relay/finalize-hook
    nemo-relay/plugins.toml.in
    relay-hooks.yaml
  observability/
    phoenix-compose.yml
  fixtures/
    outlook-emails.json
  ui/
    index.html
    src/
      App.tsx
      styles.css
  docs/
    brev-deployment.md
    verify-functionality.md
    nemo-relay-notes.md
    booth-demo-upgrade.md
    outlook-integration.md
    relay-phoenix.md
    self-evolving-demo.md
    demo-script.md
```

## 1. Onboard NemoHermes

Interactive:

```bash
export NEMOCLAW_AGENT=hermes
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash

nemohermes onboard --fresh --name financial-analyst
```

`nemohermes onboard` is the preferred Hermes-specific entry point. If you want
to start from the generic NemoClaw command named in many docs and demos, use the
same sandbox name with the Hermes agent selected:

```bash
nemoclaw onboard --agent hermes --fresh --name financial-analyst
```

When prompted, choose an OpenAI-compatible provider and enter the API key for
that provider. Onboard can use a default model first; then switch the running
Hermes sandbox to the provider and model you want for the demo:

```bash
export FINANCE_API_URL=<your-compatible-api-url>
export FINANCE_API_KEY=<your-compatible-api-key>
export FINANCE_MODEL=openai/openai/gpt-5.5
export OPENAI_API_KEY="$FINANCE_API_KEY"

openshell provider create \
  --name compatible-chat-api \
  --type openai \
  --credential OPENAI_API_KEY \
  --config OPENAI_BASE_URL="$FINANCE_API_URL"

nemohermes inference set \
  --sandbox financial-analyst \
  --provider compatible-chat-api \
  --model "$FINANCE_MODEL" \
  --no-verify
```

Non-interactive starter:

```bash
export NEMOCLAW_AGENT=hermes
export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
export NEMOCLAW_SANDBOX_NAME=financial-analyst
export NEMOCLAW_PROVIDER=openai
export NEMOCLAW_MODEL=openai/openai/gpt-5.5
export OPENAI_API_KEY=<your-compatible-api-key>

curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
```

The provider route is:

```text
provider: compatible-chat-api
API URL: set by FINANCE_API_URL or OPENAI_BASE_URL
model: set by FINANCE_MODEL or OPENAI_MODEL
```

Verification note from 2026-06-08: the Brev demo was redeployed with
`openai/openai/gpt-5.5` through a compatible chat-completions provider and
Hermes. If a selected model returns upstream errors, choose another model
supported by the same API provider and rerun the smoke tests below.

## 2. Install Finance Skills and Policy

From this example directory:

```bash
cd examples/financial-analyst-hermes
bash scripts/install-skills.sh financial-analyst
```

The script applies [presets/finance-data-readonly.yaml](presets/finance-data-readonly.yaml)
installs all four skill directories, and narrows the active Hermes skill set to:

- `financial-market-snapshot`
- `sec-company-facts`
- `financial-analyst-brief`
- `financial-analyst-playbook`
- `nemoclaw-openshell-runtime-context`

That scoping matters. A stock Hermes sandbox may include many bundled skills;
loading all of them can add substantial prompt context and make skill selection
less predictable for a focused finance demo.

To reapply the scoped profile after adding or removing skills:

```bash
bash scripts/configure-finance-skills.sh financial-analyst
```

If the gateway is already running and you add a new skill file manually, ask the
agent to reload skills or restart the sandbox before expecting automatic skill
matching to change. Explicitly named skills can still be used when present on
disk, but automatic matching is best after the reload.

The policy allows read-only requests from Python helpers to:

- `query1.finance.yahoo.com/v8/finance/chart/**`
- `www.sec.gov/files/company_tickers.json`
- `data.sec.gov/api/xbrl/companyfacts/**`

Preview the policy before applying:

```bash
nemohermes financial-analyst policy-add \
  --from-file presets/finance-data-readonly.yaml \
  --dry-run
```

## 3. Verify the Helpers Inside the Sandbox

```bash
nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/financial-market-snapshot/scripts/finance_snapshot.py quote NVDA MSFT

nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/sec-company-facts/scripts/sec_company_facts.py facts NVDA
```

For SEC usage in a real workflow, set a descriptive user agent:

```bash
export SEC_USER_AGENT="Your Name your.email@example.com"
```

## 4. Use the Hermes API

NemoHermes forwards the Hermes API to the host on port `8642`:

```bash
curl -sf http://127.0.0.1:8642/health
```

Run the included API smoke:

```bash
python3 scripts/smoke-hermes-api.py \
  --api-url http://127.0.0.1:8642/v1 \
  --timeout 180
```

Smoke-test a compatible API directly before changing a sandbox route:

```bash
python3 scripts/smoke-compatible-api.py --env-file ../../.env
```

Use the dashboard URL:

```bash
nemohermes financial-analyst dashboard-url --quiet
```

## 5. Use the Financial Desk UI

Serve the UI locally with same-origin proxying to Hermes:

```bash
cd examples/financial-analyst-hermes
npm install
npm run build
python3 scripts/finance_ui_server.py \
  --port 18080 \
  --api-url http://127.0.0.1:8642
```

Open `http://127.0.0.1:18080` and send a prompt. The helper server avoids
browser CORS issues by proxying `/v1/*` to Hermes on the host. Chat responses
stream token chunks into the UI, assistant markdown is rendered inline, and the
browser does not ask for an API token or API URL.

The UI also includes Outlook-style inbox cards for a booth-safe email demo.
For the upgraded walkthrough, see
[docs/booth-demo-upgrade.md](docs/booth-demo-upgrade.md).

Run the UI smoke in prompt and email modes:

```bash
FINANCE_UI_URL=http://127.0.0.1:18080/ npm run ui:smoke
FINANCE_UI_URL=http://127.0.0.1:18080/ FINANCE_SMOKE_MODE=email npm run ui:smoke
```

## 6. Good Demo Prompt

```text
Create a concise analyst brief for NVDA. Use a public market snapshot
and SEC company facts. Separate facts from hypotheses, include checks before
acting, and include a caveat that this is not investment advice.
```

## 7. Outlook Email

Fixture rehearsal:

```bash
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:18080/v1 \
  --fixture fixtures/outlook-emails.json \
  --limit 1
```

For real Microsoft Graph setup, see
[docs/outlook-integration.md](docs/outlook-integration.md).

The real Outlook path is deliberately one-owner only. It reads only
`OUTLOOK_TARGET_MAILBOX`, accepts only messages from `OUTLOOK_REPLY_TO`, and
replies only in-thread. Configure the OpenShell provider with:

```bash
bash scripts/setup-outlook-provider.sh financial-analyst
```

Then validate with `--reply-mode print` before using `--reply-mode graph`.

## 8. Self-Evolving Analyst Demo

Run the 10-question/follow-up evaluation to prove the assistant uses the right
skills, remembers session preferences, and improves into a consistent briefing
playbook:

```bash
python3 scripts/self_evolving_eval.py \
  --api-url http://127.0.0.1:18080/v1 \
  --questions fixtures/self-evolving-questions.json
```

The full walkthrough is in
[docs/self-evolving-demo.md](docs/self-evolving-demo.md).

## 9. Nemo Relay And Phoenix

Use the same sidecar pattern as the personal community sentiment agent:
Hermes owns skills and LLM/tool hooks, NeMo Relay runs on loopback inside the
sandbox, and Phoenix receives OpenInference traces from Relay. The UI server
does not emit traces.

See [agents/hermes/README.md](agents/hermes/README.md),
[docs/relay-phoenix.md](docs/relay-phoenix.md), and
[docs/nemo-relay-notes.md](docs/nemo-relay-notes.md).

## 10. Demo Runbook

For a concise walkthrough that shows the NemoClaw/OpenShell/Hermes value rather
than only the final assistant output, see [docs/demo-script.md](docs/demo-script.md).

## Security and Analyst Caveats

- The skills are read-only and public-data only.
- The UI is a local demo surface, not a production authenticated web app.
- Do not paste account credentials, MNPI, client PII, or trading instructions.
- Outputs are research support, not financial advice.
