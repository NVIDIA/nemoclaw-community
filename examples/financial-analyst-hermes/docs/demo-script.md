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

After onboarding, switch Hermes to the provider and model you want to demo:

```bash
export FINANCE_API_URL=https://integrate.api.nvidia.com/v1
export FINANCE_API_KEY=<your-build-api-key>
export FINANCE_MODEL=nvidia/nemotron-3-ultra-550b-a55b
export NVIDIA_API_KEY="${NVIDIA_API_KEY:-$FINANCE_API_KEY}"

openshell provider create \
  --name compatible-endpoint \
  --type nvidia \
  --credential NVIDIA_API_KEY \
  --config NVIDIA_BASE_URL="$FINANCE_API_URL"

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
  /usr/bin/python3 /sandbox/.hermes/skills/financial-market-snapshot/scripts/finance_snapshot.py quote NVDA MSFT

nemohermes financial-analyst exec -- \
  /usr/bin/python3 /sandbox/.hermes/skills/sec-company-facts/scripts/sec_company_facts.py facts NVDA
```

Talking point: the tools return structured JSON that Hermes can cite and
synthesize, while OpenShell still constrains where the helper can connect.

## 5. Show API Access

```bash
curl -sf http://127.0.0.1:8642/health
python3 scripts/smoke-hermes-api.py --api-url http://127.0.0.1:8642/v1 --timeout 180
```

Talking point: Hermes exposes a chat-completions API, so existing apps can call
the sandboxed assistant without learning a custom protocol. For this demo,
OpenShell routes that API through Build API while keeping credentials
server-side.

## 6. Show the UI

```bash
python3 scripts/finance_ui_server.py --port 18080 --api-url http://127.0.0.1:8642
```

Open `http://127.0.0.1:18080` and use this prompt:

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
