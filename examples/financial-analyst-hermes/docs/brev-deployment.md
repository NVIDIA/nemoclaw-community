# Brev Deployment

This guide deploys the financial analyst assistant on a Brev NVIDIA instance
using the current `brev` CLI command shapes.

For the complete copy/paste runbook, including local forwarding, Phoenix,
Outlook fixture rehearsal, real Outlook setup, and cleanup, see
[start-agent.md](start-agent.md).

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

Create the environment file from the committed template:

```bash
cp .env.example .env
${EDITOR:-vi} .env
```

Fill in at least:

```dotenv
FINANCE_API_URL=https://integrate.api.nvidia.com/v1
FINANCE_API_KEY=<your-build-api-key>
FINANCE_MODEL=nvidia/nemotron-3-ultra-550b-a55b
NEMOCLAW_SANDBOX_NAME=financial-analyst
```

## 3. Install and Onboard NemoHermes

```bash
export NEMOCLAW_AGENT=hermes
export NEMOCLAW_SANDBOX_NAME=financial-analyst
set -a
. ./.env
set +a
export NVIDIA_API_KEY="${NVIDIA_API_KEY:-$FINANCE_API_KEY}"

curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
nemohermes onboard --fresh --name financial-analyst
```

The equivalent generic CLI form is:

```bash
nemoclaw onboard --agent hermes --fresh --name financial-analyst
```

Use the Build API compatible endpoint for the demo. It is fine to onboard with
the default model first, then switch to the model and provider route for the
demo after the sandbox is healthy.

## 4. Switch Hermes to a Compatible Chat API

Put the API URL, API key, and model in `.env`. Do not expose the key to the
browser. On the Brev instance, from this example directory:

```bash
set -a
. ./.env
set +a
export NVIDIA_API_KEY="${NVIDIA_API_KEY:-$FINANCE_API_KEY}"
```

Create or update OpenShell's NemoHermes-compatible endpoint provider:

```bash
openshell provider create \
  --name compatible-endpoint \
  --type nvidia \
  --credential NVIDIA_API_KEY \
  --config NVIDIA_BASE_URL="$FINANCE_API_URL"
```

If the provider already exists, update it instead:

```bash
openshell provider update compatible-endpoint \
  --credential NVIDIA_API_KEY \
  --config NVIDIA_BASE_URL="$FINANCE_API_URL"
```

Then sync the Hermes sandbox route:

```bash
nemohermes inference set \
  --sandbox financial-analyst \
  --provider compatible-endpoint \
  --model "$FINANCE_MODEL" \
  --no-verify

openshell inference set \
  --provider compatible-endpoint \
  --model "$FINANCE_MODEL" \
  --timeout 240 \
  --no-verify
```

Verify the route:

```bash
nemohermes inference get --json
openshell inference get
python3 scripts/smoke-hermes-api.py --api-url http://127.0.0.1:8642/v1 --timeout 240
```

Expected route:

```text
provider: compatible-endpoint
model: nvidia/nemotron-3-ultra-550b-a55b
```

Verification note from 2026-06-09: the Brev demo was redeployed with
`nvidia/nemotron-3-ultra-550b-a55b`; direct Build API smoke and the minimal
Hermes route smoke passed. If the endpoint returns upstream errors, confirm the
Build API key, endpoint, and model access, then rerun the smoke tests.

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

If your `.env` contains `OUTLOOK_TENANT_ID`, `OUTLOOK_CLIENT_ID`,
`OUTLOOK_TARGET_MAILBOX`, and `OUTLOOK_REPLY_TO`, configure the OpenShell
provider from the Brev shell:

```bash
bash scripts/setup-outlook-provider.sh financial-analyst
```

The helper prints a Microsoft device-code URL and code. Sign in as
`OUTLOOK_TARGET_MAILBOX`, not your personal mailbox. If Microsoft returns a
conditional-access error such as `AADSTS53003`, the tenant blocked the app or
sign-in context; fix that policy/app assignment and rerun the helper.

Validate the agent email flow without sending mail first:

```bash
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:8642/v1 \
  --limit 1 \
  --reply-mode print
```

Only after that works should you use `--reply-mode graph`. The bridge reads only
`OUTLOOK_TARGET_MAILBOX`, accepts only `OUTLOOK_REPLY_TO`, and replies only
in-thread.

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
