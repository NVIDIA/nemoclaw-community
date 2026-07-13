# NemoClaw Community

[![License](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)
[![Security Policy](https://img.shields.io/badge/Security-Report%20a%20Vulnerability-red)](SECURITY.md)

NemoClaw Community is a collection of examples that showcase NemoClaw blueprints for constrained, inspectable agent workflows.

NemoClaw is the blueprint layer for composing three things into a repeatable agent system:

- **Model** — the inference endpoint, model selection, and provider configuration the agent uses.
- **Harness** — the agent runtime, skills, bridges, state, and workflow-specific behavior.
- **OpenShell** — the sandbox, gateway, policy, provider, and networking substrate that runs the harness with explicit boundaries.

The examples in this repository demonstrate complete blueprint patterns: they show how a model is wired to a harness, how the harness is packaged with skills and integrations, and how OpenShell constrains and runs the resulting agent.

## Reference Examples

The table below lists examples maintained in this repository. Additional NemoClaw examples are available in [brevdev/nemoclaw-demos](https://github.com/brevdev/nemoclaw-demos).

| Example | Description | Link |
| ---- | ----------- | ---- |
| Personal Community Sentiment Triage | Pairs a Hermes harness with an OpenShell sandbox and community-signal integrations across Slack, Outlook, live read-only GitHub REST, GitHub discussion mirrors, and NVIDIA forum mirrors. | [Guide](examples/personal-community-sentiment-triage/README.md) |
| Hermes Brev Launchable | Provides a notebook path from a fresh Brev CPU instance to a working NemoClaw-managed Hermes sandbox, including installation, onboarding, API verification, and terminal access. | [Guide](examples/hermes-launchable/README.md) |
| Harness Engineering Playground | A CLI dev tool (not an OpenShell blueprint) for automated, eval-driven harness profile improvement, with pluggable target-framework adapters and optimization techniques. | [Guide](examples/harness-engineering-playground/README.md) |
| Retail Assistant | Deploys a Telegram-based retail management assistant that maps users to store roles, queries retail data through a FastAPI service, and runs the agent inside an OpenShell sandbox. | [Guide](examples/retail-assistant/README.md) |
| Watchtower | Runs a scheduled web-monitoring agent that searches watchlist topics with Tavily, extracts source text when needed, dedups against persistent seen-state, and writes cited Markdown digests plus JSON changelogs from an OpenShell sandbox. | [Guide](examples/watchtower/README.md) |
| Payment Operations Hermes Assistant | Runs a regulated payment-operations workflow in a constrained Hermes sandbox, with NeMo Relay evidence, sanctions screening, and a platform-enforced human release boundary. | [Guide](examples/payment-ops-hermes/README.md) |

## Getting Started

Choose an example from the table above and follow its guide. To run an example from this repository, clone the repo first:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community
```

For examples maintained outside this repository, see [brevdev/nemoclaw-demos](https://github.com/brevdev/nemoclaw-demos). Each example documents its own host requirements, credentials, setup steps, and OpenShell policy details.

## Requirements

- Linux host with Docker or a compatible container runtime
- OpenShell CLI and gateway
- Access to an OpenAI-compatible inference endpoint
- Optional integration credentials for Slack, Microsoft Graph/Outlook, GitHub live reads, and source ETL mirrors

This project will download and install additional third-party open source software projects. Review the license terms of these open source projects before use. See [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES) for the repository inventory.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). This project uses Developer Certificate of Origin sign-offs for inbound contributions.

## Security

See [SECURITY.md](SECURITY.md). Do not file public GitHub issues for security vulnerabilities.

## Support

See [SUPPORT.md](SUPPORT.md) for support channels and expectations.

## Governance And Maintainers

- Governance: [GOVERNANCE.md](GOVERNANCE.md)
- Maintainers: [MAINTAINERS.md](MAINTAINERS.md)
- Code owners: [.github/CODEOWNERS](.github/CODEOWNERS)

## License

This project is licensed under the Apache 2.0 License. See [LICENSE](LICENSE) for details.
