# Start The Financial Assistant Agent

This guide starts the NemoHermes Financial Desk from a fresh checkout. It is
written as copy/paste steps for a Brev instance, with notes for local use where
the commands differ.

## What You Will Run

```text
Browser UI on :18080
  -> same-origin /v1 proxy
  -> NemoHermes API on 127.0.0.1:8642
  -> OpenShell provider route
  -> compatible chat-completions API

Hermes sandbox
  -> finance skills
  -> read-only public finance helpers
  -> optional NeMo Relay sidecar
  -> optional Phoenix on :6006
  -> optional Outlook bridge
```

The browser never receives your API key. The UI server injects any required
upstream bearer token server-side and proxies browser requests to Hermes.

## 1. Create Or Open A Brev Instance

From your local machine:

```bash
brev ls --no-check-latest
brev create financial-assistant-agent --gpu n1-highmem-4:nvidia-tesla-t4:1
brev shell financial-assistant-agent
```

If the instance already exists, skip `brev create` and run:

```bash
brev shell financial-assistant-agent
```

## 2. Clone The Repo

Run these commands inside the Brev shell:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community
```

If this example has not been merged yet, switch to the feature branch:

```bash
git remote add pastorsj https://github.com/pastorsj/nemoclaw-community.git || true
git fetch pastorsj feature/hermes-financial-assistant
git checkout feature/hermes-financial-assistant
```

Then enter the example directory:

```bash
cd examples/financial-analyst-hermes
```

After this step, all paths in this guide assume you are in:

```bash
pwd
# .../nemoclaw-community/examples/financial-analyst-hermes
```

## 3. Create `.env`

```bash
cp .env.example .env
${EDITOR:-vi} .env
```

Fill in at least:

```dotenv
FINANCE_API_URL=https://api.example.com/v1
FINANCE_API_KEY=<your-compatible-api-key>
FINANCE_MODEL=openai/openai/gpt-5.5
NEMOCLAW_SANDBOX_NAME=financial-analyst
```

Optional but useful:

```dotenv
SEC_USER_AGENT=Your Name your.email@example.com
PHOENIX_COLLECTOR_ENDPOINT=http://host.openshell.internal:6006/v1/traces
PHOENIX_PROJECT_NAME=financial-assistant-relay
FINANCE_PHOENIX_GRAPHQL_URL=http://127.0.0.1:6006/graphql
```

For Outlook, fill the optional Outlook block only when you have a Microsoft
Graph app and a mailbox ready:

```dotenv
OUTLOOK_TENANT_ID=<directory-tenant-id>
OUTLOOK_CLIENT_ID=<application-client-id>
OUTLOOK_TARGET_MAILBOX=<agent mailbox>
OUTLOOK_REPLY_TO=<your mailbox>
OUTLOOK_ALLOWED_SENDERS=<same value as OUTLOOK_REPLY_TO>
```

Load the file into the shell:

```bash
set -a
. ./.env
set +a

export OPENAI_API_KEY="${OPENAI_API_KEY:-$FINANCE_API_KEY}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-$FINANCE_API_URL}"
export OPENAI_MODEL="${OPENAI_MODEL:-$FINANCE_MODEL}"
export NEMOCLAW_SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-financial-analyst}"
```

## 4. Install NemoClaw And Onboard NemoHermes

```bash
export NEMOCLAW_AGENT=hermes
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash

nemohermes onboard --fresh --name "$NEMOCLAW_SANDBOX_NAME"
```

The equivalent generic NemoClaw form is:

```bash
nemoclaw onboard --agent hermes --fresh --name "$NEMOCLAW_SANDBOX_NAME"
```

When the onboarding flow asks for an inference provider, choose an
OpenAI-compatible provider. It is fine to choose a default model first; the next
step sets the exact route for this demo.

## 5. Connect The Model Route

Create or update the OpenShell provider:

```bash
if openshell provider get compatible-chat-api >/dev/null 2>&1; then
  openshell provider update compatible-chat-api \
    --credential OPENAI_API_KEY \
    --config OPENAI_BASE_URL="$FINANCE_API_URL"
else
  openshell provider create \
    --name compatible-chat-api \
    --type openai \
    --credential OPENAI_API_KEY \
    --config OPENAI_BASE_URL="$FINANCE_API_URL"
fi
```

Point NemoHermes at that provider and model:

```bash
nemohermes inference set \
  --sandbox "$NEMOCLAW_SANDBOX_NAME" \
  --provider compatible-chat-api \
  --model "$FINANCE_MODEL" \
  --no-verify
```

Smoke test the route:

```bash
python3 scripts/smoke-hermes-api.py \
  --api-url http://127.0.0.1:8642/v1 \
  --model "$FINANCE_MODEL" \
  --timeout 180
```

## 6. Install Finance Skills And Policy

```bash
bash scripts/install-skills.sh "$NEMOCLAW_SANDBOX_NAME"
```

Verify the public-data helpers inside the sandbox:

```bash
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/financial-market-snapshot/scripts/finance_snapshot.py quote NVDA MSFT

nemohermes "$NEMOCLAW_SANDBOX_NAME" exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/sec-company-facts/scripts/sec_company_facts.py facts NVDA
```

Both commands should return structured JSON with `"ok": true`.

## 7. Start Phoenix

Phoenix is optional for basic chat, but recommended for a booth demo:

```bash
docker compose -f observability/phoenix-compose.yml up -d
```

Check that it is reachable on the Brev host:

```bash
curl -sf http://127.0.0.1:6006 | head
```

If you enable the Relay/Phoenix hooks in the sandbox, use:

```dotenv
PHOENIX_COLLECTOR_ENDPOINT=http://host.openshell.internal:6006/v1/traces
PHOENIX_PROJECT_NAME=financial-assistant-relay
```

The current demo assets for Relay live under:

```text
agents/hermes/plugins/nemo-relay/
agents/hermes/nemo-relay/finalize-hook
agents/hermes/nemo-relay/plugins.toml.in
agents/hermes/relay-hooks.yaml
```

## 8. Build And Start The Financial Desk UI

```bash
npm install
npm run build

python3 scripts/finance_ui_server.py \
  --env-file .env \
  --host 0.0.0.0 \
  --port 18080 \
  --api-url http://127.0.0.1:8642 \
  --model "$FINANCE_MODEL" \
  --upstream-label "${FINANCE_UPSTREAM_LABEL:-Compatible API}" \
  --phoenix-url "${FINANCE_PHOENIX_GRAPHQL_URL:-http://127.0.0.1:6006/graphql}"
```

In another local terminal, forward the UI:

```bash
brev port-forward financial-assistant-agent -p 18080:18080
```

Open:

```text
http://127.0.0.1:18080
```

Ask:

```text
Create a concise analyst brief for NVDA using a public market snapshot and SEC company facts. Include caveats.
```

## 9. Run Smoke Tests

From your local checkout while the port-forward is active:

```bash
cd examples/financial-analyst-hermes

FINANCE_UI_URL=http://127.0.0.1:18080/ \
FINANCE_API_URL=http://127.0.0.1:18080/v1 \
FINANCE_RESPONSE_TIMEOUT_MS=180000 \
npm run ui:smoke
```

Require Phoenix trace evidence:

```bash
FINANCE_UI_URL=http://127.0.0.1:18080/ \
FINANCE_API_URL=http://127.0.0.1:18080/v1 \
FINANCE_REQUIRE_TRACE_EVENTS=1 \
FINANCE_RESPONSE_TIMEOUT_MS=180000 \
npm run ui:smoke
```

## 10. Outlook Fixture Rehearsal

Use fixture mode before real Microsoft Graph wiring:

```bash
OUTLOOK_TARGET_MAILBOX=agent@example.com \
OUTLOOK_REPLY_TO=pm@northstar-cap.com \
FINANCE_MODEL="$FINANCE_MODEL" \
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:18080/v1 \
  --fixture fixtures/outlook-emails.json \
  --limit 1 \
  --reply-mode print
```

This sends a fixture email prompt to the same assistant route and prints the
reply without sending email.

## 11. Real Outlook Setup

Real Outlook is optional and uses the same OpenShell provider pattern as the
personal community sentiment agent:

1. Create a Microsoft Entra app with public client/device-code flow enabled.
2. Grant delegated Microsoft Graph permissions:
   - `Mail.Read`
   - `Mail.Send`
   - `offline_access`
3. Set `OUTLOOK_TENANT_ID`, `OUTLOOK_CLIENT_ID`,
   `OUTLOOK_TARGET_MAILBOX`, and `OUTLOOK_REPLY_TO` in `.env`.
4. Configure the OpenShell provider:

```bash
bash scripts/setup-outlook-provider.sh "$NEMOCLAW_SANDBOX_NAME"
```

5. Validate without sending mail:

```bash
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:8642/v1 \
  --limit 1 \
  --reply-mode print
```

6. Only after print mode works, send Graph replies:

```bash
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:8642/v1 \
  --limit 1 \
  --reply-mode graph
```

The bridge is one-owner only:

- reads only `OUTLOOK_TARGET_MAILBOX`,
- processes only `OUTLOOK_REPLY_TO`,
- replies only in-thread,
- records processed message IDs so it does not reply twice.

If Microsoft returns `AADSTS53003`, the sign-in succeeded but tenant
conditional access blocked the app/account/location/device. Fix that Entra
policy or app assignment and rerun `scripts/setup-outlook-provider.sh`.

## 12. Operational Checks

```bash
nemohermes "$NEMOCLAW_SANDBOX_NAME" status
nemohermes inference get --json
curl -sf http://127.0.0.1:8642/health
curl -sf http://127.0.0.1:18080/health
curl -sf http://127.0.0.1:18080/api/phoenix/recent | python3 -m json.tool
```

## 13. Cleanup

Stop the UI with `Ctrl-C`.

Destroy only the sandbox:

```bash
nemohermes "$NEMOCLAW_SANDBOX_NAME" destroy --yes
```

Stop Phoenix:

```bash
docker compose -f observability/phoenix-compose.yml down
```

Delete the Brev instance when you no longer need it:

```bash
brev delete financial-assistant-agent
```
