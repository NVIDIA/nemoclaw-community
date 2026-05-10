# Examples

Each example in this directory is intended to be runnable on its own. Start with
the example README, copy `.env.example` to `.env` when present, and use the
scripts in that example rather than mixing files across examples.

## Choosing An Example

| Example | Agent | Primary workflow | Start here |
|---|---|---|---|
| [personal-community-sentiment-triage](personal-community-sentiment-triage/) | Hermes | Outlook-first community sentiment triage with Slack and mirrored GitHub/forum data. | Use when you want the full reference architecture with host ETLs and MS Graph. |
| [personal-community-sentiment-triage-simplified](personal-community-sentiment-triage-simplified/) | Hermes | Slack-first community sentiment triage with Tavily and GitHub CLI live search. | Use when you want the lean community triage path. |
| [hermes-omni-demo](hermes-omni-demo/) | Hermes | Browser UI for video, audio, image, and PDF Q&A with Nemotron Omni. | Use when you want to test multimodal Hermes skills and the host UI pattern. |
| [openclaw-omni-demo](openclaw-omni-demo/) | OpenClaw | Main-agent delegation to an Omni-backed `vision-operator` sub-agent. | Use when you want to test OpenClaw sub-agent configuration and image delegation. |

## Standard Layout

Examples should use this shape where it applies:

```text
README.md        first-stop explanation and quickstart
.env.example     local credential/settings template
policy.yaml      OpenShell policy or policy patch/reference
agents/          agent-facing config, skills, SOUL, workspace assets
app/             optional host UI/server code
docs/            deeper setup and troubleshooting notes
extras/          optional host services such as Phoenix
scripts/         setup, bring-up, verify, teardown, and helper scripts
```

Not every example needs every directory. The rule of thumb is that a user should
be able to answer three questions quickly:

- What does this demo do?
- What runs on my host versus inside the sandbox?
- Which command proves it works?

## Testing Pattern

Prefer an example-local verification command:

```bash
bash scripts/verify.sh
```

For demos that create their own sandbox from scratch, `scripts/bring-up.sh`
should be the main path. For demos that patch an existing onboarded sandbox,
`scripts/setup.sh` or `scripts/apply-*.sh` should do the configuration, and
`scripts/verify.sh` should test it.

## Observability Pattern

Examples may include Phoenix as an optional local host service:

```bash
bash scripts/00-host-services.sh
```

When a demo emits NemoFlow/OpenInference traces, use an example-specific
`NEMO_FLOW_PROJECT_NAME` alongside `PHOENIX_COLLECTOR_ENDPOINT`. Phoenix uses
the OpenInference project resource attribute for grouping, so this keeps traces
out of the generic `default` project and makes side-by-side demo testing easier.
