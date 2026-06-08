# Brev Deployment

This guide deploys the financial analyst assistant on a Brev NVIDIA instance
using the current `brev` CLI command shapes.

## 1. Pick or Create an Instance

List existing instances:

```bash
brev ls --no-check-latest
```

Create a fresh GPU instance if needed:

```bash
brev create financial-assistant-agent --gpu n1-highmem-4:nvidia-tesla-t4:1
```

Wait until the instance is `READY`.

## 2. Open a Shell

```bash
brev shell financial-assistant-agent
```

Inside the Brev instance:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community
```

If you are testing this feature branch before it is merged:

```bash
git remote add pastorsj https://github.com/pastorsj/nemoclaw-community.git || true
git fetch pastorsj feature/hermes-financial-assistant
git checkout feature/hermes-financial-assistant
```

Then enter the example directory:

```bash
cd examples/financial-analyst-hermes
```

## 3. Install and Onboard NemoHermes

```bash
export NEMOCLAW_AGENT=hermes
export NEMOCLAW_SANDBOX_NAME=financial-analyst
export OPENAI_API_KEY=<your-compatible-api-key>

curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
nemohermes onboard --fresh --name financial-analyst
```

The equivalent generic CLI form is:

```bash
nemoclaw onboard --agent hermes --fresh --name financial-analyst
```

Choose the compatible API provider you want to use. It is fine to onboard with
the default model first, then switch to the model and provider route for the
demo after the sandbox is healthy.

## 4. Switch Hermes to a Compatible Chat API

Put the API URL, API key, and model in `.env`. Do not expose the key to the
browser. On the Brev instance, from this example directory:

```bash
set -a
. ./.env
set +a
export OPENAI_API_KEY="$FINANCE_API_KEY"
```

Create or update OpenShell's NemoHermes-compatible endpoint provider:

```bash
openshell provider create \
  --name compatible-chat-api \
  --type openai \
  --credential OPENAI_API_KEY \
  --config OPENAI_BASE_URL="$FINANCE_API_URL"
```

If the provider already exists, update it instead:

```bash
openshell provider update compatible-chat-api \
  --credential OPENAI_API_KEY \
  --config OPENAI_BASE_URL="$FINANCE_API_URL"
```

Then sync the Hermes sandbox route:

```bash
nemohermes inference set \
  --sandbox financial-analyst \
  --provider compatible-chat-api \
  --model "$FINANCE_MODEL" \
  --no-verify
```

Verify the route:

```bash
nemohermes inference get --json
python3 scripts/smoke-hermes-api.py --api-url http://127.0.0.1:8642/v1 --timeout 180
```

Expected route:

```text
provider: compatible-chat-api
model: openai/openai/gpt-5.5
```

Verification note from 2026-06-08: the Brev demo was redeployed with
`openai/openai/gpt-5.5` and passed the UI smoke through Hermes. If your selected
model returns upstream errors, switch `FINANCE_MODEL` to another model available
from the same provider and rerun the smoke tests.

## 5. Install Skills and Policy

```bash
bash scripts/install-skills.sh financial-analyst
```

Verify the installed tools from the sandbox:

```bash
nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/financial-market-snapshot/scripts/finance_snapshot.py quote NVDA MSFT

nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/sec-company-facts/scripts/sec_company_facts.py facts NVDA
```

## 6. Forward Ports From Brev

From your local machine:

```bash
brev port-forward financial-assistant-agent -p 8642:8642
```

Open the Hermes dashboard:

```bash
nemohermes financial-analyst dashboard-url --quiet
```

Or use the API:

```bash
curl -sf http://127.0.0.1:8642/health
```

## 7. Run the Streaming UI on Brev

In the Brev shell:

```bash
cd nemoclaw-community/examples/financial-analyst-hermes
npm install
npm run build
python3 scripts/finance_ui_server.py \
  --host 0.0.0.0 \
  --port 18080 \
  --api-url http://127.0.0.1:8642 \
  --model "$FINANCE_MODEL"
```

From your local machine:

```bash
brev port-forward financial-assistant-agent -p 18080:18080
```

Open `http://127.0.0.1:18080`. The helper server proxies same-origin `/v1/*` to
Hermes, avoiding browser CORS issues and avoiding port `8080`, which OpenShell
uses for the gateway. Hermes is already routed to the configured provider
through OpenShell, so the UI does not need an API token or visible endpoint
field. Chat responses stream as token chunks in the browser.

Run browser smoke tests from your local checkout while the tunnel is active:

```bash
cd examples/financial-analyst-hermes
FINANCE_UI_URL=http://127.0.0.1:18080/ \
FINANCE_API_URL=http://127.0.0.1:18080/v1 \
FINANCE_EXPECT_TEXT= \
npm run ui:smoke

FINANCE_UI_URL=http://127.0.0.1:18080/ \
FINANCE_API_URL=http://127.0.0.1:18080/v1 \
FINANCE_EXPECT_TEXT= \
FINANCE_SMOKE_MODE=email \
npm run ui:smoke
```

## 8. Outlook Fixture Rehearsal

Use fixture mode before wiring real Microsoft Graph credentials:

```bash
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:18080/v1 \
  --fixture fixtures/outlook-emails.json \
  --limit 1 \
  --reply-mode print
```

For real Outlook setup, follow [outlook-integration.md](outlook-integration.md)
and use `providers/outlook-email.yaml`.

## 9. Phoenix

Start Phoenix on Brev:

```bash
docker compose -f observability/phoenix-compose.yml up -d
```

Forward Phoenix:

```bash
ssh -F ~/.brev/ssh_config -f -N -T \
  -L 6006:127.0.0.1:6006 financial-assistant-agent
```

Open `http://127.0.0.1:6006`.

For booth demos, traces should come from the Hermes sandbox via the NeMo Relay
sidecar, not from the UI server. The finance example carries the same Relay
assets as the personal community sentiment agent:

```text
agents/hermes/plugins/nemo-relay/
agents/hermes/nemo-relay/finalize-hook
agents/hermes/nemo-relay/plugins.toml.in
agents/hermes/relay-hooks.yaml
```

The sidecar runtime shape is:

```text
Hermes hooks/plugin -> nemo-relay sidecar on 127.0.0.1:4040 -> Phoenix
```

Set the collector endpoint for a Brev-hosted Phoenix instance to:

```text
PHOENIX_COLLECTOR_ENDPOINT=http://host.openshell.internal:6006/v1/traces
PHOENIX_PROJECT_NAME=financial-assistant-relay
```

After a chat request, Phoenix should show a real Hermes turn trace: agent/root
span, LLM spans, tool spans, and per-turn finalize. If Phoenix only shows a flat
synthetic UI span, the wrong component is exporting telemetry.

## 10. Operational Checks

```bash
nemohermes financial-analyst status
nemohermes financial-analyst logs --follow
nemohermes financial-analyst policy-list
nemohermes inference get
```

## 11. Cleanup

Destroy only the sandbox:

```bash
nemohermes financial-analyst destroy --yes
```

Delete the Brev instance when you no longer need it:

```bash
brev delete financial-assistant-agent
```
