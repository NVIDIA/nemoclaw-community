# Verify Functionality

Run these checks after onboarding a sandbox named `financial-analyst`.

## Host CLI

```bash
nemohermes --version
nemohermes financial-analyst status
nemohermes inference get
```

Expected provider route for the booth demo:

```text
provider: compatible-chat-api
model: value of FINANCE_MODEL
```

## Policy and Skills

```bash
nemohermes financial-analyst policy-list
bash scripts/install-skills.sh financial-analyst
```

## Finance Tools

```bash
nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/financial-market-snapshot/scripts/finance_snapshot.py quote NVDA MSFT AAPL

nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/sec-company-facts/scripts/sec_company_facts.py lookup NVDA

nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/sec-company-facts/scripts/sec_company_facts.py facts NVDA
```

Expected result: structured JSON with `"ok": true`.

## Hermes API

```bash
curl -sf http://127.0.0.1:8642/health
python3 scripts/smoke-hermes-api.py --api-url http://127.0.0.1:8642/v1 --timeout 180
```

Direct compatible API smoke before route changes:

```bash
python3 scripts/smoke-compatible-api.py --env-file ../../.env
```

If the API is not reachable after a restart:

```bash
openshell forward start --background 8642 financial-analyst
```

## Dashboard

```bash
nemohermes financial-analyst dashboard-url --quiet
```

Expected result: the local dashboard URL reported by NemoHermes.

## React UI

Build and unit test the React UI:

```bash
npm test
npm run build
```

Live test:

```bash
python3 scripts/finance_ui_server.py --port 18080 --api-url http://127.0.0.1:8642
```

Open `http://127.0.0.1:18080`. The UI sends requests to same-origin `/v1`, so
there is no visible API URL or API token field. The left rail should show live
public quotes from `/api/quotes`, and the right rail should show skill usage,
run telemetry, and recent Phoenix span evidence from `/api/phoenix/recent`.

Playwright checks:

```bash
FINANCE_UI_URL=http://127.0.0.1:18080/ \
FINANCE_API_URL=http://127.0.0.1:18080/v1 \
FINANCE_EXPECT_TEXT= \
FINANCE_RESPONSE_TIMEOUT_MS=180000 \
npm run ui:smoke

FINANCE_UI_URL=http://127.0.0.1:18080/ \
FINANCE_API_URL=http://127.0.0.1:18080/v1 \
FINANCE_EXPECT_TEXT= \
FINANCE_REQUIRE_TRACE_EVENTS=1 \
FINANCE_RESPONSE_TIMEOUT_MS=180000 \
npm run ui:smoke

FINANCE_UI_URL=http://127.0.0.1:18080/ \
FINANCE_API_URL=http://127.0.0.1:18080/v1 \
FINANCE_EXPECT_TEXT= \
FINANCE_SMOKE_MODE=email \
FINANCE_RESPONSE_TIMEOUT_MS=180000 \
npm run ui:smoke
```

## Relay / Phoenix

If NeMo Relay is enabled, verify the sidecar is healthy from inside the
sandbox:

```bash
nemohermes financial-analyst exec -- \
  /bin/sh -lc 'curl -sf http://127.0.0.1:4040/healthz'
```

After one chat turn, Phoenix should show a real Hermes trace with agent/root,
LLM, and tool spans. The UI server should not be the trace exporter.

The UI bridge exposes a read-only Phoenix summary for booth display:

```bash
curl -sf http://127.0.0.1:18080/api/phoenix/recent | python3 -m json.tool
```

Expected result: spans from `financial-assistant-relay` or
`financial-assistant-agent` with `agent`, `llm`, and `tool` kinds, such as
`tool:skill_view`, `tool:terminal`, `financial-market-snapshot`, or
`sec-company-facts`.

## Demo Prompt

```text
Create a concise analyst brief for NVDA using a public market snapshot
and SEC company facts. Separate facts from hypotheses and include checks before
acting.
```
