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
export NVIDIA_API_KEY=<your-build-api-key>

curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
nemohermes onboard --fresh --name financial-analyst
```

The equivalent generic CLI form is:

```bash
nemoclaw onboard --agent hermes --fresh --name financial-analyst
```

Choose NVIDIA Endpoints and use:

```text
nvidia/nemotron-3-ultra-550b-a55b
```

On the tested Brev instance, direct Nemotron Ultra chat completions worked but
took about 50 seconds, which exceeded the onboarding validator's shorter
timeout. If Ultra validation times out during onboarding, onboard with
`nvidia/nemotron-3-super-120b-a12b` first, then switch the configured route to
Ultra:

```bash
nemohermes inference set \
  --sandbox financial-analyst \
  --provider nvidia-prod \
  --model nvidia/nemotron-3-ultra-550b-a55b \
  --no-verify
```

## 4. Install Skills and Policy

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

## 5. Forward Ports From Brev

From your local machine:

```bash
brev port-forward financial-assistant-agent -p 18789:18789
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

## 6. Run the UI on Brev

In the Brev shell:

```bash
cd nemoclaw-community/examples/financial-analyst-hermes
python3 scripts/mock_hermes_server.py \
  --host 0.0.0.0 \
  --port 18080 \
  --proxy-base-url http://127.0.0.1:8642
```

From your local machine:

```bash
brev port-forward financial-assistant-agent -p 18080:18080
```

Open `http://127.0.0.1:18080`, set the API base URL to
`http://127.0.0.1:18080/v1`, and enter the Hermes API token if your sandbox
requires it. The helper server proxies `/v1/*` to Hermes, avoiding browser CORS
issues and avoiding port `8080`, which OpenShell uses for the gateway.

## 7. Operational Checks

```bash
nemohermes financial-analyst status
nemohermes financial-analyst logs --follow
nemohermes financial-analyst policy-list
nemohermes inference get
```

## 8. Cleanup

Destroy only the sandbox:

```bash
nemohermes financial-analyst destroy --yes
```

Delete the Brev instance when you no longer need it:

```bash
brev delete financial-assistant-agent
```
