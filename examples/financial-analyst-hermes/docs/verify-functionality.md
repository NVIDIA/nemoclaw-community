# Verify Functionality

Run these checks after onboarding a sandbox named `financial-analyst`.

## Host CLI

```bash
nemohermes --version
nemohermes financial-analyst status
nemohermes inference get
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
python3 scripts/smoke-hermes-api.py --base-url http://127.0.0.1:8642/v1 --timeout 180
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

## Tiny UI

Mock test:

```bash
python3 scripts/mock_hermes_server.py --port 8765
npm install
npm run ui:smoke
```

Live test:

```bash
python3 scripts/mock_hermes_server.py --port 18080 --proxy-base-url http://127.0.0.1:8642
```

Open `http://127.0.0.1:18080` and set API base URL to
`http://127.0.0.1:18080/v1`.

## Demo Prompt

```text
Create a concise analyst brief for NVDA using a public market snapshot
and SEC company facts. Separate facts from hypotheses and include checks before
acting.
```
