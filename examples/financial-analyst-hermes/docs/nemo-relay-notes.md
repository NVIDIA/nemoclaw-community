# Nemo Relay Notes

This example keeps logging simple by default:

```bash
nemohermes financial-analyst status
nemohermes financial-analyst logs --follow
```

That path is enough to show the NemoClaw lifecycle, OpenShell sandbox state,
Hermes API availability, and runtime logs.

## When to Add Nemo Relay

Add Nemo Relay when you want structured traces across:

- API requests into Hermes
- tool calls from Hermes
- per-turn artifacts
- optional Phoenix or object-store export

The repository already includes a fuller reference implementation under
`examples/personal-community-sentiment-triage/agents/hermes/`:

- `nemo-relay/plugins.toml.in`
- `plugins/nemo-relay/`
- `nemo-relay/finalize-hook`
- `bridges/atif/`
- Phoenix and ATIF relay documentation

Use that example when you want to bake Nemo Relay into a custom Hermes sandbox
image with `nemohermes onboard --from <Dockerfile>`.

## Minimal Adaptation Path

1. Start from the stock NemoClaw Hermes Dockerfile contract.
2. Copy the Nemo Relay binary and plugin assets into the image.
3. Preserve `/sandbox/.hermes/plugins/nemoclaw`.
4. Add the Nemo Relay plugin under `/sandbox/.hermes-data/plugins/`.
5. Add policy for your trace sink, such as local Phoenix or an internal relay.
6. Re-onboard with:

```bash
nemohermes onboard --from ./Dockerfile --name financial-analyst
```

For this introductory finance assistant, the added image complexity is optional.
The skills and API workflow work without Nemo Relay.
