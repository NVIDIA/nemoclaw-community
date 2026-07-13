# NeMo Relay and Phoenix

NeMo Relay `0.3.0` runs inside the custom Hermes sandbox on loopback port
`4040`. The sandbox entrypoint waits for Relay's `/healthz` endpoint before
starting Hermes, preventing first-turn telemetry loss.

Hermes loads `agents/hermes/plugins/nemo-relay`, which forwards exact model
request/response bodies and paired tool-call hooks to Relay. Shell hooks cover
session and LLM lifecycle events. The finalize hook closes each turn so Relay
writes a complete ATIF trajectory without waiting for Hermes's idle timeout.

## Configuration

`agents/hermes/nemo-relay/plugins.toml.in` is rendered during the sandbox image
build. The following `.env` values are staged into the Dockerfile:

```dotenv
PHOENIX_COLLECTOR_ENDPOINT=http://host.openshell.internal:6006/v1/traces
NEMO_RELAY_PROJECT_NAME=finguard-payment-ops
```

The project name is safely quoted and emitted as:

```toml
[components.config.openinference.resource_attributes]
"openinference.project.name" = "finguard-payment-ops"
"nemo.claw.example" = "finguard-payment-ops"
```

If the Phoenix endpoint is empty, OpenInference export is disabled while ATIF
output under `/sandbox/atif` remains active.

## Health and diagnostics

```bash
openshell sandbox exec --name payment-ops -- \
  curl -fsS http://127.0.0.1:4040/healthz

openshell sandbox exec --name payment-ops -- \
  tail -50 /tmp/nemo-relay.log

openshell sandbox exec --name payment-ops -- \
  sed -n '1,160p' /etc/nemo-relay/plugins.toml
```

Phoenix runs on the host through
`observability/phoenix-compose.yml` and is available on port `6006`.

## ATIF

Retrieve trajectories before sandbox destruction:

```bash
bash scripts/download-traces.sh
```

The script downloads `/sandbox/atif` into the ignored host-side `.tmp` directory.
