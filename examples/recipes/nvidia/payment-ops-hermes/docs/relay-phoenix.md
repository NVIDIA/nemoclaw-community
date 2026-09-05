# NeMo Relay and Phoenix

The pinned NemoClaw base supplies Hermes `0.20.6` and NeMo Relay `0.7.2`.
Hermes owns Relay's provider, tool, and session lifecycles in-process; this
example does not install a separate Relay binary, run a sidecar, or register
forwarding hooks.

## Configuration

`agents/hermes/nemo-relay/plugins.toml` is copied into the sandbox image and
loaded through `HERMES_NEMO_RELAY_PLUGINS_TOML`. This demo always exports
OpenInference spans to its host Phoenix service at the fixed endpoint and
project:

```toml
endpoint = "http://host.openshell.internal:6006/v1/traces"
"openinference.project.name" = "finguard-payment-ops"
```

Relay v3 exports closed turn, LLM, and tool spans during an active conversation.
The top-level Agent span and ATIF trajectory close only at Hermes's native
session-finalization boundary. Completed ATIF files are written to
`/sandbox/atif`; the example does not force finalization after each API turn.

## Health and diagnostics

Hermes and in-process Relay share one workload, so Hermes's health endpoint is
the workload health check:

```bash
openshell sandbox exec --name payment-ops -- \
  curl -fsS http://127.0.0.1:8642/health

openshell sandbox exec --name payment-ops -- \
  sed -n '1,160p' /etc/nemo-relay/config/plugins.toml

openshell sandbox exec --name payment-ops -- \
  tail -50 /tmp/hermes.log
```

Phoenix runs on the host through
`observability/phoenix-compose.yml` and is available on port `6006`.

## Completed ATIF

After Hermes has finalized a session, retrieve its completed trajectory before
sandbox destruction:

```bash
bash scripts/download-traces.sh
```

The script downloads `/sandbox/atif` into the ignored host-side `.tmp`
directory. It may find no file while the API session is still active, and it
does not create a synthetic finalization boundary.
