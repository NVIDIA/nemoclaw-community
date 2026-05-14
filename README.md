# NemoClaw Community

[![License](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)
[![Security Policy](https://img.shields.io/badge/Security-Report%20a%20Vulnerability-red)](SECURITY.md)

NemoClaw Community is a collection of examples that showcase NemoClaw blueprints for constrained, inspectable agent workflows.

NemoClaw is the blueprint layer for composing three things into a repeatable agent system:

- **Model** — the inference endpoint, model selection, and provider configuration the agent uses.
- **Harness** — the agent runtime, skills, bridges, state, and workflow-specific behavior.
- **OpenShell** — the sandbox, gateway, policy, provider, and networking substrate that runs the harness with explicit boundaries.

The examples in this repository demonstrate complete blueprint patterns: they show how a model is wired to a harness, how the harness is packaged with skills and integrations, and how OpenShell constrains and runs the resulting agent.

## What's Here

| Directory | Description |
| --------- | ----------- |
| `examples/personal-community-sentiment-triage/` | NemoClaw blueprint example pairing a Hermes harness with an OpenShell sandbox and community-signal integrations across Slack, Outlook, GitHub mirrors, and NVIDIA forum mirrors. |
| `scripts/` | Repository maintenance checks used by CI. |

## Getting Started

Install the OpenShell CLI and move into the example:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/personal-community-sentiment-triage
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | OPENSHELL_VERSION=v0.0.38 sh
```

Then follow the full setup guide in [examples/personal-community-sentiment-triage/README.md](examples/personal-community-sentiment-triage/README.md).

## Requirements

- Linux host with Docker or a compatible container runtime
- OpenShell CLI and gateway
- Access to an OpenAI-compatible inference endpoint
- Optional integration credentials for Slack, Microsoft Graph/Outlook, GitHub, and source ETL mirrors

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
