# NemoClaw Community

NemoClaw Community is a home for practical, end-to-end examples that show how
to build sandboxed Hermes/OpenShell agents for community intelligence work.

The examples in this repo focus on a concrete problem: helping a developer or
product team understand what a technical community is asking for, struggling
with, and repeatedly resurfacing across Slack, GitHub, forums, email, and the
open web. The repo is intentionally example-first. It is not a packaged SDK; it
is a set of reference deployments, policies, scripts, skills, and operating
notes that can be copied, adapted, and simplified for real team workflows.

## Why This Exists

Community feedback is usually scattered. Important signals hide in Slack
threads, GitHub issues, forum posts, PR comments, docs gaps, and private mail.
Traditional dashboards help count activity, but they often miss the connective
tissue: which requests repeat, where sentiment is changing, which topics are
blocked by missing examples, and where product priorities do or do not match
what users are actually asking for.

This repo explores a more agentic pattern:

- Give the agent a narrow, inspectable sandbox.
- Expose data sources through explicit skills and provider-scoped secrets.
- Keep network egress and filesystem access declared in policy.
- Make bring-up reproducible with local scripts and example-specific docs.
- Preserve a human-in-the-loop workflow through familiar channels like Slack or Outlook.

## Examples

| Example | Interaction channel | Research sources | Best for |
|---|---|---|---|
| [personal-community-sentiment-triage](examples/personal-community-sentiment-triage/) | Outlook primary, Slack optional | Host-side ETLs for GitHub and NVIDIA Forums, plus Slack and Outlook | A fuller reference architecture with durable mirrored source data, MS Graph token management, Postgres/PostgREST, and telemetry. |
| [personal-community-sentiment-triage-simplified](examples/personal-community-sentiment-triage-simplified/) | Slack required | Live Tavily web/forum search and GitHub CLI search | A leaner Slack-first setup that avoids Outlook and host-side ETL services while keeping the same community triage intent. |

Choose the simplified example if you want the fastest path to a running agent.
Choose the fuller example if you need the original Outlook workflow or a local
source mirror for repeatable analysis over GitHub and forum data.

## Quickstart

Start with one example and follow its README. For the simplified Slack-first
variant:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/personal-community-sentiment-triage-simplified
cp .env.example .env
bash scripts/bring-up.sh
```

Before running bring-up, fill in the credentials required by the selected
example. The simplified example needs an OpenAI-compatible inference key, Slack
tokens, a Tavily API key, and a GitHub token. The full example also includes
Outlook/MS Graph and host-side ETL configuration.

## Requirements

- Docker with a running daemon.
- OpenShell CLI. Each example README pins the tested install command.
- Provider credentials for the services used by the selected example.
- Access to an OpenAI-compatible inference endpoint.

## Repository Layout

```text
examples/
  personal-community-sentiment-triage/
    Full Outlook-centered community sentiment triage example.
  personal-community-sentiment-triage-simplified/
    Slack-first version using Tavily and GitHub CLI live search.
```

Each example owns its own sandbox image, OpenShell policy, skills, scripts,
credential template, and teardown flow. That keeps the examples easy to compare
without forcing one deployment model onto the other.

## Working With The Examples

The examples are designed to be adapted. Common changes include swapping the
inference endpoint, changing Slack channel allowlists, adding a new research
skill, tightening network policy, or replacing one source with another.

Secrets should stay in local `.env` files or provider stores and should not be
committed. Generated planning artifacts such as `.planning/` are local workflow
state and are not part of the example payload.

## Contributing

Contributions are most useful when they make an example easier to run, easier
to audit, or easier to adapt. Good additions include new skills, clearer setup
docs, narrower policies, better smoke tests, and new example variants that show
meaningfully different deployment choices.

## License

See [LICENSE](LICENSE) for license terms.
