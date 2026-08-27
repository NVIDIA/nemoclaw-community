# NemoClaw Community

[![License](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)
[![Security Policy](https://img.shields.io/badge/Security-Report%20a%20Vulnerability-red)](SECURITY.md)

NemoClaw Community is a collection of examples that showcase NemoClaw blueprints for constrained, inspectable agent workflows.

[**Browse examples**](https://nvidia.github.io/nemoclaw-community/) · [**Contribute an example**](CONTRIBUTING.md#add-a-new-example)

NemoClaw is the blueprint layer for composing three things into a repeatable agent system:

- **Model** — the inference endpoint, model selection, and provider configuration the agent uses.
- **Harness** — the agent runtime, skills, bridges, state, and workflow-specific behavior.
- **OpenShell** — the sandbox, gateway, policy, provider, and networking substrate that runs the harness with explicit boundaries.

Recipes and demos show how a model, harness, and OpenShell come together. The catalog also includes launchables and developer tools.

## Reference Examples

Examples are organized as reusable NVIDIA and partner recipes, community
recipes, NVIDIA field demos, environment launchables, and standalone developer
tools. Search the [web catalog](https://nvidia.github.io/nemoclaw-community/)
by example type or industry, browse the
[source example catalog](examples/README.md), or consume the
[machine-readable catalog](https://nvidia.github.io/nemoclaw-community/catalog.json).
See the [catalog architecture](docs/catalog-architecture.md) for its metadata,
generation, URL-filter, and JSON contracts.

Each example has its own prerequisites, credentials, setup, and limitations.
Review the example README before setup.

Additional NemoClaw examples are available in
[brevdev/nemoclaw-demos](https://github.com/brevdev/nemoclaw-demos).

## Getting Started

Choose an example and follow its README. To run an example from this repository,
clone the repo first:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community
```

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

## License And Notices

This project is licensed under the Apache 2.0 License. See [LICENSE](LICENSE) for details.

Some examples download additional third-party software. See [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).
