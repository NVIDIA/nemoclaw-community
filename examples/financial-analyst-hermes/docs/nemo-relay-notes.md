# Nemo Relay Notes

This example keeps lifecycle logging simple by default:

```bash
nemohermes financial-analyst status
nemohermes financial-analyst logs --follow
```

That path is enough to show the NemoClaw lifecycle, OpenShell sandbox state,
Hermes API availability, and runtime logs.

## Sidecar Pattern

For booth observability, add NeMo Relay inside the Hermes sandbox, following
the same pattern as the personal community sentiment agent. Relay gives
structured traces across:

- API requests into Hermes
- tool calls from Hermes
- per-turn artifacts
- optional Phoenix or object-store export

This finance example includes the minimal sidecar assets under
`agents/hermes/`:

- `plugins/nemo-relay/`
- `nemo-relay/finalize-hook`
- `nemo-relay/plugins.toml.in`
- `relay-hooks.yaml`

The personal sentiment agent remains the full production reference for baking
Relay into a custom Hermes sandbox image and for optional Outlook/ATIF relay
bridges.

## Minimal Adaptation Path

1. Start from the stock NemoClaw Hermes Dockerfile contract.
2. Copy the Nemo Relay binary and plugin assets into the image.
3. Preserve `/sandbox/.hermes/plugins/nemoclaw`.
4. Add the Nemo Relay plugin under the Hermes plugin directory used by your
   custom image.
5. Add policy for your trace sink, such as local Phoenix or an internal relay.
6. Re-onboard with:

```bash
nemohermes onboard --from ./Dockerfile --name financial-analyst
```

For a live Brev sandbox retrofit, prefer:

```bash
bash scripts/recover-brev-demo.sh
```

The recovery script starts host Relay on `0.0.0.0:4040`, refreshes the Hermes
plugin assets, restarts Hermes with
`NEMO_RELAY_GATEWAY_URL=http://host.openshell.internal:4040`, and verifies that
Phoenix receives fresh `skill_view` tool spans.
