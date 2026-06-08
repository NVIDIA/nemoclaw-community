# NeMo Relay And Phoenix

Phoenix tracing should come from the Hermes sandbox, not from the browser UI
server. This finance example follows the personal community sentiment agent
pattern:

```text
Hermes shell hooks + in-process nemo-relay plugin
  -> NeMo Relay sidecar on 127.0.0.1:4040
  -> Phoenix OTLP HTTP endpoint
```

The UI server only serves files and proxies `/v1/*` to Hermes so the browser can
stream chat responses without CORS issues.

## Start Phoenix

```bash
cd examples/financial-analyst-hermes
docker compose -f observability/phoenix-compose.yml up -d
```

Phoenix UI:

```text
http://127.0.0.1:6006
```

OTLP HTTP endpoint:

```text
http://127.0.0.1:6006/v1/traces
```

## Sidecar Assets

The finance assets live under:

```text
agents/hermes/
  plugins/nemo-relay/
  nemo-relay/finalize-hook
  nemo-relay/plugins.toml.in
  relay-hooks.yaml
```

They mirror the personal sentiment agent:

- `plugins/nemo-relay/` forwards `pre_api_request`, `post_api_request`,
  `pre_tool_call`, and `post_tool_call` with exact request/response payloads.
- `relay-hooks.yaml` shell-forwards session and LLM lifecycle hooks.
- `nemo-relay/finalize-hook` synthesizes per-turn finalize events so Phoenix
  root spans close after each response.
- `nemo-relay/plugins.toml.in` enables ATIF plus Phoenix OpenInference export.

## Expected Phoenix Shape

A healthy trace should look like a real Hermes turn:

- an agent/root span for the conversation turn,
- LLM spans from Hermes API calls,
- tool spans from Hermes tool calls,
- `input.value` / `output.value` populated by Relay's Hermes adapter,
- per-turn finalize so spans close promptly.

If Phoenix only shows a flat synthetic span from the UI server, the demo is on
the wrong path. Start the Relay sidecar and enable the Hermes hooks/plugin
instead.

## Brev Notes

For a Brev-hosted Phoenix collector, use:

```text
PHOENIX_COLLECTOR_ENDPOINT=http://host.openshell.internal:6006/v1/traces
PHOENIX_PROJECT_NAME=financial-assistant-relay
```

The sandbox policy must allow POST traffic from the `nemo-relay` binary to the
Phoenix host/port. The live retrofit used by the booth rehearsal installs
`nemo-relay` in the sandbox, starts it on `127.0.0.1:4040`, and merges
`agents/hermes/relay-hooks.yaml` into Hermes config.
