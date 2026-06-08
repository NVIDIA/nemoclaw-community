# Financial Hermes Relay Sidecar

This directory carries the same Relay pattern used by
`examples/personal-community-sentiment-triage/agents/hermes`.

The UI server is only a static-file/CORS bridge. Hermes runs the agent, skills,
tools, and chat API. NeMo Relay runs as a loopback sidecar on `127.0.0.1:4040`
and exports OpenInference traces to Phoenix.

## Components

- `plugins/nemo-relay/`: in-process Hermes plugin for `pre_api_request`,
  `post_api_request`, `pre_tool_call`, and `post_tool_call`.
- `nemo-relay/finalize-hook`: converts `on_session_end` into a per-turn
  `on_session_finalize`, which closes Relay/Phoenix root spans promptly.
- `nemo-relay/plugins.toml.in`: Relay observability config for ATIF plus
  Phoenix OpenInference export.
- `relay-hooks.yaml`: the Hermes config block to enable shell hooks and both
  `nemoclaw` and `nemo-relay` plugins.

## Runtime Shape

```text
Browser UI -> finance_ui_server.py -> Hermes /v1/chat/completions
                                      |
                                      +-> finance skills/tools
                                      +-> nemo-relay Hermes plugin
                                      +-> shell hooks
                                            |
                                            v
                                      NeMo Relay sidecar -> Phoenix
```

Use the personal sentiment agent as the production-grade reference for baking
these assets into a custom image. For this finance demo, the same assets can
also be copied into an existing sandbox for a Brev booth rehearsal.
