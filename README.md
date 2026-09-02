# NemoClaw Community

[![License](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)
[![Security Policy](https://img.shields.io/badge/Security-Report%20a%20Vulnerability-red)](SECURITY.md)

NemoClaw Community is a collection of examples that showcase NemoClaw blueprints for constrained, inspectable agent workflows.

[**Launch NemoClaw on Brev**](https://brev.nvidia.com/launchable/deploy?launchableID=env-3Azt0aYgVNFEuz7opyx3gscmowS)
· [**Browse examples**](https://nvidia.github.io/nemoclaw-community/)
· [**Contribute an example**](CONTRIBUTING.md#add-a-new-example)

NemoClaw is the blueprint layer for composing three things into a repeatable agent system:

- **Model** — the inference endpoint, model selection, and provider configuration the agent uses.
- **Harness** — the agent runtime, skills, bridges, state, and workflow-specific behavior.
- **OpenShell** — the sandbox, gateway, policy, provider, and networking substrate that runs the harness with explicit boundaries.

Recipes and demos show how a model, harness, and OpenShell come together. The
catalog also includes standalone developer tools.

## Reference Examples

Examples are organized as reusable NVIDIA and partner recipes, community
recipes, NVIDIA field demos, and standalone developer tools. The Build-a-Claw
view brings its guided demos, tutorials, and tagged recipes together without
changing their canonical paths or contributor provenance. Search the
[web catalog](https://nvidia.github.io/nemoclaw-community/)
by example type or industry, browse the
[source example catalog](examples/README.md), or consume the
[machine-readable catalog](https://nvidia.github.io/nemoclaw-community/catalog.json).
Agent-oriented navigation is available in the generated
[`llms.txt`](https://nvidia.github.io/nemoclaw-community/llms.txt). See the
[catalog architecture](docs/catalog-architecture.md) for its metadata,
generation, URL filter, JSON, and text-index contracts.

Each example has its own prerequisites, credentials, setup, and limitations.
Review the example README before setup.

Additional NemoClaw examples are available in
[brevdev/nemoclaw-demos](https://github.com/brevdev/nemoclaw-demos).

## How Catalog Status Works

Each example detail page reports stack verification and maintenance status.
These are independent evidence signals, not scores for support, quality, or
runtime health.

### Stack Verification

Each example README declares its NemoClaw, harness, and OpenShell values. The
catalog compares those declarations with recognized version variables in a
root `Dockerfile*` or `agents/*/Dockerfile*`. A reviewed exact NemoClaw release
and a recognized harness selection can also supply the stock harness and
OpenShell versions through the checked-in
[release contracts](scripts/nemoclaw-release-contracts.json). The build does
not run the example or guess values from custom file layouts.

| Status | Meaning |
| --- | --- |
| `Confirmed` | Exact README values agree with recognized Dockerfile evidence. |
| `Unconfirmed` | Exact values appear only in the README. |
| `Unpinned` | A participating version is a range or mutable value. |
| `Unknown` | The harness or a required version cannot be determined. |
| `Conflict` | README declarations and Dockerfile evidence disagree. |
| `N/A` | NemoClaw, a harness, and OpenShell do not participate. |

For mixed component results, the overall priority is `Conflict`, `Unknown`,
`Unpinned`, `Unconfirmed`, then `Confirmed`.

### Maintenance Status

The catalog uses the later of two dates: the latest committed change anywhere
under the example, or its optional `Reviewed` date. An explicit `Deprecated`
lifecycle takes effect immediately. The scheduled Pages build recalculates
the age each day from the thresholds in
[`scripts/catalog-maintenance.json`](scripts/catalog-maintenance.json).

| Age since latest activity | Status |
| --- | --- |
| 0–29 days | `Current` |
| 30–59 days | `Review soon` |
| 60–119 days | `Review due` |
| 120–239 days | `Review overdue` |
| 240 days or more | `Review critical` |

Only an explicit `Lifecycle` value of `Deprecated` produces the `Deprecated`
status. The default catalog view hides explicitly deprecated examples; age
alone does not hide an example.

See [Runtime Stack Discovery](CONTRIBUTING.md#runtime-stack-discovery) for the
recognized variables and contributor contract. See the
[catalog architecture](docs/catalog-architecture.md#static-stack-discovery)
for the complete generation contract.

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
