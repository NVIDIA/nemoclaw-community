# Booth Demo Upgrade

This example now supports a simple multi-surface demo:

- browser chat with streaming token output,
- Outlook-style email requests through the UI,
- a fixture-driven Outlook bridge for rehearsal,
- optional Microsoft Graph bridge setup for real Outlook mail,
- optional NeMo Relay / Phoenix observability.

## Streaming

The UI sends OpenAI-compatible chat-completions requests with `stream: true`.
The helper server proxies `text/event-stream` responses from Hermes/OpenShell
without buffering and the browser renders each incoming delta.

This is possible because NemoClaw/OpenShell use the same
`/v1/chat/completions` path for compatible endpoints, and current NemoClaw docs
describe validation of streaming events for compatible inference routes:

https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/inference/use-local-inference

## Booth Flow

1. Open `http://127.0.0.1:18080`.
2. Click `NVDA brief`, `Market snapshot`, `SEC facts`, or `Email triage`.
3. Watch the response stream into the conversation with markdown tables and the
   animated `Thinking ...` state.
4. Point to the telemetry panel for run ID, chunk count, channel, Phoenix link,
   and the `Tool Calls / Trace Clues` table populated from recent Phoenix spans.
5. In Phoenix, show the corresponding Hermes turn trace from the Relay sidecar.

## Brev / Live Hermes Mode

First route Hermes through the compatible API provider you want to demo:

```bash
export FINANCE_API_URL=<your-compatible-api-url>
export FINANCE_API_KEY=<your-compatible-api-key>
export FINANCE_MODEL=<your-chat-model>
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

Then run the UI server against Hermes:

```bash
cd examples/financial-analyst-hermes
npm install
npm run build
python3 scripts/finance_ui_server.py \
  --port 18080 \
  --api-url http://127.0.0.1:8642
```

From your laptop:

```bash
ssh -F ~/.brev/ssh_config -f -N -T \
  -L 18080:127.0.0.1:18080 financial-assistant-agent
```

Then open `http://127.0.0.1:18080`.

For a booth-health smoke test with trace evidence enabled:

```bash
FINANCE_UI_URL=http://127.0.0.1:18080/ \
FINANCE_API_URL=http://127.0.0.1:18080/v1 \
FINANCE_REQUIRE_TRACE_EVENTS=1 \
FINANCE_RESPONSE_TIMEOUT_MS=180000 \
npm run ui:smoke
```

## Outlook Rehearsal Mode

The browser UI includes two Outlook-style inbox cards. They are fixture prompts
that exercise the same assistant route as chat, so they are safe for a booth
without Microsoft credentials.

For command-line rehearsal:

```bash
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:18080/v1 \
  --fixture fixtures/outlook-emails.json \
  --limit 1 \
  --reply-mode print
```

## Real Outlook Mode

Real Outlook delivery follows the Microsoft Graph provider pattern from the
`personal-community-sentiment-triage` example:

- register an Entra app,
- grant delegated Graph permissions,
- log in with device code as the agent mailbox,
- store the refresh token in the OpenShell provider store,
- attach `providers/outlook-email.yaml` to the sandbox,
- run `scripts/outlook_finance_bridge.py` without `--fixture`.

Required Graph permissions:

- `Mail.Read`
- `Mail.Send`
- `offline_access`

The bridge reads recent inbox messages and can print replies or call the Graph
`/reply` action when `--reply-mode graph` is used.

## NeMo Relay / Phoenix

Start Phoenix:

```bash
docker compose -f observability/phoenix-compose.yml up -d
```

Open `http://127.0.0.1:6006`.

For a custom Hermes sandbox image, use the sidecar assets in `agents/hermes/`:

- `plugins/nemo-relay/` for in-process API/tool hooks,
- `nemo-relay/finalize-hook` for per-turn finalize,
- `nemo-relay/plugins.toml.in` for ATIF and Phoenix OpenInference export,
- `relay-hooks.yaml` for Hermes shell hooks.

Set the collector endpoint to:

```text
PHOENIX_COLLECTOR_ENDPOINT=http://host.openshell.internal:6006/v1/traces
PHOENIX_PROJECT_NAME=financial-assistant-relay
```

The UI server should not emit Phoenix traces; it only proxies browser chat to
Hermes. It does expose `/api/phoenix/recent` as a read-only summary so the
browser can show recent Relay spans in the right rail.

NeMo Relay observability docs:

- https://docs.nvidia.com/nemo/relay/observability-plugin/about
- https://docs.nvidia.com/nemo/relay/observability-plugin/openinference
