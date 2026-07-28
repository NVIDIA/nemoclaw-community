# Contributing to NemoClaw Community

Thank you for your interest in improving NemoClaw Community.

This repository contains independently deployable examples and developer tools
built around NemoClaw. By participating, you agree to follow our
[Code of Conduct](CODE_OF_CONDUCT.md).

Do not report security vulnerabilities in public issues or pull requests.
Follow [SECURITY.md](SECURITY.md) instead.

## Ways to Contribute

- Improve an existing example or its documentation.
- Fix setup, verification, teardown, or sandbox lifecycle problems.
- Add or improve agent skills, policies, integrations, or developer tools.
- Contribute a new example.
- Report a reproducible problem with the affected example and environment
  details.

Choose a project from the [reference examples](README.md#reference-examples).
Follow that example's README and any linked setup and verification
instructions.

Before implementing a major feature, new dependency, distribution change,
container publication, or compliance-sensitive change, discuss it with the
maintainers. See [GOVERNANCE.md](GOVERNANCE.md).

## Prerequisites

Repository-level checks require:

- Git.
- Python 3.10 or newer, invoked as `python3`.

Individual examples may require newer Python versions or additional tools such
as Docker, `uv`, Helm, Bash, credentials, or access to external services.
Follow the prerequisites documented by each example you modify.

## Fork and Create a Branch

External contributors should first fork the repository on GitHub.

Clone your fork and add the NVIDIA repository as `upstream`:

```bash
git clone https://github.com/<your-github-user>/nemoclaw-community.git
cd nemoclaw-community
git remote add upstream https://github.com/NVIDIA/nemoclaw-community.git
git fetch upstream main
git checkout -b <short-branch-name> upstream/main
```

Push your branch to your fork:

```bash
git push -u origin <short-branch-name>
```

Before opening or updating a pull request, refresh the upstream reference:

```bash
git fetch upstream main
```

If the selected example uses a Git submodule, follow that example's README to
initialize it. Recursive submodule checkout is not required for contributors
working on unrelated examples.

## Work Within an Example

This repository does not have one shared runtime setup. Each example owns its
development and verification workflow.

Follow the selected example's instructions for:

- Prerequisites and supported environments.
- Credentials and secret handling.
- Setup and configuration.
- Sandbox, network, and policy permissions.
- Startup and shutdown.
- Verification and tests.
- Cleanup and teardown.
- Known limitations.

Keep examples independently deployable. Do not introduce dependencies on
private files, internal systems, or another example's local state.

## Contribution Requirements

Keep each pull request focused on one feature, fix, documentation update, or
coordinated migration.

When applicable:

- Add or update tests for changed behavior.
- Update documentation when setup, configuration, policy, permissions, or
  user-visible behavior changes.
- Update [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES) when dependencies or
  distributed third-party content change.
- Preserve partner and community attribution.
- Use placeholders in public configuration and documentation.
- Do not commit secrets, populated `.env` files, private certificates, token
  caches, generated runtime state, or private workspace details.
- Do not add internal-only links to public documentation.
- Do not contact external systems or start live services during verification
  unless the change requires it and suitable credentials and authorization are
  available.

## Run Repository Checks

After committing your changes, run the repository-wide checks from the
repository root:

```bash
python3 scripts/check_license_headers.py --check
git fetch upstream main
git diff --check upstream/main...HEAD
```

If you have staged but uncommitted changes, also run:

```bash
git diff --cached --check
```

These checks do not replace example-specific validation. Run the setup, syntax,
unit, configuration, and teardown-safe checks documented by every example
modified in the pull request. Use the smallest stable check that demonstrates
the changed behavior.

In the pull request description, record:

- The exact commands you ran.
- Their results.
- Any verification you did not run and why.
- Any required live, hardware-specific, credentialed, or external-system
  validation that remains.

Do not describe a check as passing unless you ran it against the final relevant
change set.

## Add a New Example

Discuss the intended placement, name, and contributor or organizational
provenance with the maintainers before implementation.

A new example must document:

- Its purpose, intended users, and support boundary.
- Contributor or organizational provenance.
- Prerequisites and supported environments.
- Architecture and major components.
- Credentials and secret handling.
- Setup and configuration.
- Sandbox, network, and policy permissions.
- Startup behavior.
- Verification steps and expected results.
- Teardown and cleanup.
- Known limitations.
- Third-party dependencies and licensing obligations.

Add the example to the [reference examples](README.md#reference-examples).

## Move or Rename an Example

Before beginning a move:

- Search the repository and open pull requests for the old path and name.
- Identify affected pull requests and downstream documentation.
- Record the intended merge order.
- Coordinate rebases for dependent pull requests.
- Separate path changes from unrelated runtime or dependency changes.

The migration pull request must:

- Provide an old-to-new path table.
- Update links, commands, ownership, notices, and `.gitmodules` entries.
- Document compatibility-sensitive identifiers that retain an old name.
- Include instructions for existing clones when submodules move.
- Verify every moved example from its new location.
- Confirm that obsolete paths are gone after dependent branches are rebased.

## Sign Off Every Commit

Every commit in a pull request must include a
[`Signed-off-by:` trailer](https://developercertificate.org/) for Developer
Certificate of Origin (DCO) compliance. A sign-off in the pull request
description does not satisfy this requirement.

Create a signed-off commit with:

```bash
git commit -s -m "Describe the change"
```

Git appends a trailer in this form:

```text
Signed-off-by: Your Name <your.email@example.com>
```

Use your own name and email address. If you amend, rebase, squash, or
cherry-pick commits, confirm that every resulting commit still contains a valid
trailer. DCO sign-off is a commit-message declaration; it is separate from
cryptographic commit signing.

Commits without the required sign-off will not be accepted.

## Open a Pull Request

Complete [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md).

Your pull request should include:

- The problem and intended outcome.
- The examples or repository surfaces affected.
- Exact verification commands and results.
- An explanation for applicable checks that were not run.
- Documentation and dependency changes.
- Migration details and downstream follow-ups, when applicable.
- Confirmation that every commit includes DCO sign-off.

Submit all changes to `main` through a pull request. Maintainers merge only
after the DCO and license-header requirements are satisfied, review
conversations are resolved, and a maintainer approves the change.

Maintainers review and merge contributions according to
[GOVERNANCE.md](GOVERNANCE.md). Major scope, distribution, dependency, or
compliance changes may require additional review before merge.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
