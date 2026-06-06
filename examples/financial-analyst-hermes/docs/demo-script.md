# Demo Script

Use this when you want to show the power of NemoClaw with a simple financial
analyst assistant instead of a complex enterprise integration.

## 1. Show the Stack

```bash
nemohermes --version
openshell --version
nemohermes resources
```

Talking point: NemoClaw orchestrates the model, Hermes runtime, and OpenShell
sandbox. OpenShell enforces the policy boundary around the agent.

## 2. Onboard Hermes

```bash
export NEMOCLAW_AGENT=hermes
export NVIDIA_API_KEY=<your-build-api-key>
nemohermes onboard --fresh --name financial-analyst
```

Equivalent generic NemoClaw form:

```bash
nemoclaw onboard --agent hermes --fresh --name financial-analyst
```

Choose NVIDIA Endpoints and model:

```text
nvidia/nemotron-3-ultra-550b-a55b
```

## 3. Show the Governed Policy

Preview the read-only finance preset:

```bash
nemohermes financial-analyst policy-add \
  --from-file presets/finance-data-readonly.yaml \
  --dry-run
```

Apply it with the skill installer:

```bash
bash scripts/install-skills.sh financial-analyst
```

Show the sandbox policy state:

```bash
nemohermes financial-analyst policy-list
```

Talking point: the assistant gets only the finance endpoints it needs for this
demo. It does not get brokerage, email, Slack, or arbitrary internal access.

## 4. Show Tools Inside the Sandbox

```bash
nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes-data/skills/financial-market-snapshot/scripts/finance_snapshot.py quote NVDA MSFT

nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes-data/skills/sec-company-facts/scripts/sec_company_facts.py facts NVDA
```

Talking point: the tools return structured JSON that Hermes can cite and
synthesize, while OpenShell still constrains where the helper can connect.

## 5. Show API Access

```bash
curl -sf http://127.0.0.1:8642/health
python3 scripts/smoke-hermes-api.py --base-url http://127.0.0.1:8642/v1
```

Talking point: Hermes exposes an OpenAI-compatible API, so existing internal
apps can call the sandboxed assistant without learning a custom protocol.

## 6. Show the UI

```bash
python3 -m http.server 8080 --directory ui
```

Open `http://127.0.0.1:8080`, set API base URL to
`http://127.0.0.1:8642/v1`, and use this prompt:

```text
Create a concise analyst brief for NVDA. Use a public market snapshot and SEC
company facts. Separate facts from hypotheses, include checks before acting,
and include a caveat that this is not investment advice.
```

## 7. Show Logs

```bash
nemohermes financial-analyst status
nemohermes financial-analyst logs --follow
```

For structured Nemo Relay traces, use the adaptation notes in
[nemo-relay-notes.md](nemo-relay-notes.md).
