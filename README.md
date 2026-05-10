# NemoClaw Community

NemoClaw Community is a landing place for practical, end-to-end examples that
show how to build sandboxed Hermes and OpenClaw agents with OpenShell/NemoClaw.

This is an example-first repository, not a packaged SDK. Each example is a
reference deployment with its own policy, scripts, credentials template, agent
assets, and docs so it can be copied, adapted, or reduced for a real workflow.
The catalog is expected to grow over time: some examples will show complete
application workflows, some will focus on one integration, and others will
demonstrate a specific agent architecture or sandbox capability.

## Why This Exists

Agent demos are easiest to understand when they are runnable, inspectable, and
small enough to take apart. This repo exists to make those patterns visible:
what the sandbox policy allows, where credentials enter, which code runs on the
host, which code runs in the sandbox, and which command proves the demo works.

The examples here currently cover community sentiment triage, multimodal media
analysis, and visual sub-agent delegation. Future examples can add new domains,
integrations, agent types, policies, and host-side applications without changing
the role of this repo: a readable place to find working patterns.

This repo explores a more agentic pattern:

- Give the agent a narrow, inspectable sandbox.
- Expose data sources through explicit skills and provider-scoped secrets.
- Keep network egress and filesystem access declared in policy.
- Make bring-up reproducible with local scripts and example-specific docs.
- Preserve a clear human workflow through Slack, Outlook, a browser UI, or a
  repeatable CLI smoke test.

## Examples

| Example | Agent | What it demonstrates | Best for |
|---|---|---|---|
| [personal-community-sentiment-triage](examples/personal-community-sentiment-triage/) | Hermes | Outlook-first community sentiment triage with Slack, host-side GitHub/forum ETLs, Postgres/PostgREST, MS Graph token management, and telemetry. | A fuller reference architecture with durable mirrored source data. |
| [personal-community-sentiment-triage-simplified](examples/personal-community-sentiment-triage-simplified/) | Hermes | Slack-first community sentiment triage with live Tavily web/forum search and GitHub CLI search. | The fastest path to the community triage workflow without Outlook or host ETLs. |
| [hermes-omni-demo](examples/hermes-omni-demo/) | Hermes | Browser-based video, audio, image, and PDF Q&A against Nemotron 3 Nano Omni, with host UI and sandboxed skills. | Testing multimodal Hermes behavior and the host UI pattern. |
| [openclaw-omni-demo](examples/openclaw-omni-demo/) | OpenClaw | Main-agent to `vision-operator` delegation, where a text agent uses an Omni-backed visual sub-agent. | Testing OpenClaw sub-agent configuration and visual delegation. |

See [examples/README.md](examples/README.md) for the current catalog and the
standard example layout.

## Observability

Examples that include `extras/docker-compose.yml` can start Phoenix locally with
their `scripts/00-host-services.sh` helper. Demos that emit NemoFlow
OpenInference traces set an explicit `NEMO_FLOW_PROJECT_NAME` so Phoenix shows
traces under the example name instead of `default`.

Current project names:

| Example | Phoenix project |
|---|---|
| `personal-community-sentiment-triage` | `personal-community-sentiment-triage` |
| `personal-community-sentiment-triage-simplified` | `personal-community-sentiment-triage-simplified` |
| `hermes-omni-demo` | `hermes-omni-demo` when the onboarded Hermes runtime includes NemoFlow. |
| `openclaw-omni-demo` | `openclaw-omni-demo` when the OpenClaw runtime includes the NemoFlow plugin. |

## Example Presentation

Examples should be easy to compare even when they demonstrate different things.
The current Omni demos are a good example:

- [hermes-omni-demo](examples/hermes-omni-demo/) keeps Hermes as the primary
  agent. Media analysis is exposed as Hermes skills, and a host-side browser UI
  uploads files, prepares media, and calls into the sandbox through OpenShell.
- [openclaw-omni-demo](examples/openclaw-omni-demo/) keeps the main OpenClaw
  agent text-focused and delegates visual tasks to a `vision-operator`
  sub-agent backed by Omni.

Both demos answer the same testing question: can a sandboxed agent use Omni for
visual or media understanding through an explicit, auditable path?

That is the presentation goal for new examples too: make the agent pattern, host
responsibilities, sandbox responsibilities, policy surface, and verification
command obvious from the README.

## Quickstart

Start with one example and follow its README. For example, to try the simplified
Slack-first community triage workflow:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/personal-community-sentiment-triage-simplified
cp .env.example .env
bash scripts/bring-up.sh
```

Before running bring-up, fill in the credentials required by the selected
example. Requirements vary by demo: Slack/Tavily/GitHub for the simplified
triage example, Outlook/MS Graph for the full triage example, and NVIDIA
Endpoint access to Nemotron Omni for the current Omni examples.

Most examples expose a local verification command once configured:

```bash
bash scripts/verify.sh
```

The full triage examples use their own bring-up and health-check flow because
they create and manage a full sandbox deployment.

## Requirements

- Docker with a running daemon.
- OpenShell CLI. Each example README pins the tested install command.
- Provider credentials for the services used by the selected example.
- Access to an OpenAI-compatible inference endpoint.

## Repository Layout

```text
examples/
  README.md
    How to choose and navigate the examples.
  personal-community-sentiment-triage/
    Full Outlook-centered community sentiment triage example.
  personal-community-sentiment-triage-simplified/
    Slack-first version using Tavily and GitHub CLI live search.
  hermes-omni-demo/
    Hermes multimodal UI demo with Nemotron Omni.
  openclaw-omni-demo/
    OpenClaw Omni vision sub-agent demo.
```

Examples follow the same shape when it applies:

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

Not every example needs every directory, but the goal is consistent: a user
should quickly see what the demo does, what runs on the host, what runs in the
sandbox, and how to test it.

## Working With The Examples

The examples are designed to be adapted. Common changes include swapping the
inference endpoint, changing Slack channel allowlists, adding a new research
skill, tightening network policy, replacing one source with another, or changing
which host-side app launches around the sandbox.

Secrets should stay in local `.env` files or provider stores and should not be
committed. Generated planning artifacts such as `.planning/` are local workflow
state and are not part of the example payload.

## Contributing

Contributions are most useful when they make an example easier to run, easier
to audit, or easier to adapt. Good additions include new skills, clearer setup
docs, narrower policies, better smoke tests, and new example variants that show
meaningfully different deployment choices.
