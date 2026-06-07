# Financial Analyst Hermes Assistant

A small NemoClaw/NemoHermes example for a financial analyst. It uses a stock
NemoHermes sandbox, NVIDIA-hosted Nemotron Ultra, three installable Hermes
skills, a read-only finance data policy preset, and a tiny host UI that talks to
the Hermes OpenAI-compatible API.

This example is intentionally narrow: public quote snapshots, SEC
company facts, concise analyst briefs, and explicit caveats. It does not connect
to brokerage accounts, place trades, or provide personalized investment advice.

## What It Shows

- `nemohermes onboard` as the main lifecycle command.
- `nvidia/nemotron-3-ultra-550b-a55b` through NVIDIA Endpoints on
  `https://integrate.api.nvidia.com/v1`.
- Hermes skills installed with `nemohermes <sandbox> skill install <path>`.
- Read-only OpenShell/NemoClaw policy for public finance data.
- API access through Hermes on `http://127.0.0.1:8642/v1`.
- A tiny local UI for prompt templates and OpenAI-compatible chat calls.
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
  presets/
    finance-data-readonly.yaml
  scripts/
    install-skills.sh
    smoke-hermes-api.py
    smoke-nemotron-ultra.py
    mock_hermes_server.py
    ui-smoke.mjs
  ui/
    index.html
    styles.css
    app.js
  docs/
    brev-deployment.md
    verify-functionality.md
    nemo-relay-notes.md
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

When prompted, choose NVIDIA Endpoints, enter your `NVIDIA_API_KEY`, and select
the model ID:

```text
nvidia/nemotron-3-ultra-550b-a55b
```

Non-interactive starter:

```bash
export NEMOCLAW_AGENT=hermes
export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
export NEMOCLAW_SANDBOX_NAME=financial-analyst
export NEMOCLAW_PROVIDER=build
export NEMOCLAW_MODEL=nvidia/nemotron-3-ultra-550b-a55b
export NVIDIA_API_KEY=<your-build-api-key>

curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
```

On some remote hosts, Nemotron Ultra can take longer than the onboarding
validator's short chat-completions timeout. If validation times out, onboard
with `nvidia/nemotron-3-super-120b-a12b` first, then switch the configured route
to Ultra without revalidating:

```bash
nemohermes inference set \
  --sandbox financial-analyst \
  --provider nvidia-prod \
  --model nvidia/nemotron-3-ultra-550b-a55b \
  --no-verify
```

## 2. Install Finance Skills and Policy

From this example directory:

```bash
cd examples/financial-analyst-hermes
bash scripts/install-skills.sh financial-analyst
```

The script applies [presets/finance-data-readonly.yaml](presets/finance-data-readonly.yaml)
and installs all three skill directories.

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
  --base-url http://127.0.0.1:8642/v1 \
  --token "$HERMES_API_KEY" \
  --timeout 180
```

Use the dashboard URL:

```bash
nemohermes financial-analyst dashboard-url --quiet
```

## 5. Use the Tiny UI

Serve the UI locally with same-origin proxying to Hermes:

```bash
cd examples/financial-analyst-hermes
python3 scripts/mock_hermes_server.py \
  --port 18080 \
  --proxy-base-url http://127.0.0.1:8642
```

Open `http://127.0.0.1:18080`, set the API base URL to
`http://127.0.0.1:18080/v1`, enter the Hermes API token if required, and send a
prompt. The helper server avoids browser CORS issues by proxying `/v1/*` to
Hermes on the host.

For a no-sandbox UI smoke test, use the mock Hermes server:

```bash
cd examples/financial-analyst-hermes
python3 scripts/mock_hermes_server.py --port 8765
```

Then open `http://127.0.0.1:8765`.

## 6. Good Demo Prompt

```text
Create a concise analyst brief for NVDA. Use a public market snapshot
and SEC company facts. Separate facts from hypotheses, include checks before
acting, and include a caveat that this is not investment advice.
```

## 7. Nemo Relay Logging

The minimal path uses current NemoHermes lifecycle logs:

```bash
nemohermes financial-analyst status
nemohermes financial-analyst logs --follow
```

For Nemo Relay style trace forwarding, see
[docs/nemo-relay-notes.md](docs/nemo-relay-notes.md). The existing
`personal-community-sentiment-triage` example already contains a richer
Nemo Relay/Phoenix integration that can be used as the starting point for a
custom Hermes image.

## 8. Demo Runbook

For a concise walkthrough that shows the NemoClaw/OpenShell/Hermes value rather
than only the final assistant output, see [docs/demo-script.md](docs/demo-script.md).

## Security and Analyst Caveats

- The skills are read-only and public-data only.
- The UI is a local demo surface, not a production authenticated web app.
- Do not paste account credentials, MNPI, client PII, or trading instructions.
- Outputs are research support, not financial advice.
