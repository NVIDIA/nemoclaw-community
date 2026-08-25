# Contributing to NemoClaw Community

Thank you for your interest in improving NemoClaw Community.

This repository contains NemoClaw examples and developer tools. You can deploy
each example independently.

By participating, you agree to follow our
[Code of Conduct](CODE_OF_CONDUCT.md).

Do not report security vulnerabilities in public issues or pull requests.
Follow [SECURITY.md](SECURITY.md) instead.

## Ways to Contribute

Use one of these methods to contribute:

- Improve an example or its documentation.
- Fix setup, checks, teardown, or sandbox lifecycle problems.
- Add or improve agent skills, policies, integrations, or developer tools.
- Contribute a new example.
- Report a reproducible problem.

For a problem report, identify the example. Give sanitized environment details.

Select an example from the [example catalog](examples/README.md). Read the
example's README. Follow all linked setup and check instructions.

Discuss each of these changes with maintainers before implementation:

- A major feature or scope change.
- A new dependency.
- A distribution change.
- Publication of a container image.
- A change to the project license or compliance requirements.

For more information, read [GOVERNANCE.md](GOVERNANCE.md).

## Classify Issues And Pull Requests

Use native GitHub Issue Type for issue classification. Select `Bug` for broken
behavior, `Enhancement` for a new capability, `Task` for maintainer work, and
`Documentation` for missing or incorrect documentation. Labels route work; they
do not replace native Issue Type.

Use a Conventional Commit-style title for issues and pull requests:

```text
<type>(<optional-scope>): <description>
```

Allowed types are `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, and
`perf`. Examples include `feat(gitlab): add policy-scoped read access`,
`fix(outlook): reuse the refresh-token cache`, and `docs: clarify setup`.

Read the canonical
[maintainer taxonomy](.agents/skills/nemoclaw-community-maintainer-policies/references/label-taxonomy.md)
before suggesting or applying labels. New example proposals and publication
pull requests also follow the repository's example-kind and provenance labels.

## Prerequisites

Install these tools before you run repository checks:

- Git.
- Python 3.10 or newer. Use the `python3` command.

Some examples require a newer Python version, additional software, credentials,
or external service access. The software can include Docker, `uv`, Helm, or
Bash.

Follow the prerequisites in the README for each example that you modify.

## Create a Fork and Branch

If you do not have write access to the NVIDIA repository, first create a fork
on GitHub.

Use these commands to clone your fork and create a branch:

```bash
git clone https://github.com/<your-github-user>/nemoclaw-community.git
cd nemoclaw-community
git remote add upstream https://github.com/NVIDIA/nemoclaw-community.git
git fetch upstream main
git checkout -b <short-branch-name> upstream/main
```

Use this command to push the branch to your fork:

```bash
git push -u origin <short-branch-name>
```

Before you open or update a pull request, refresh the upstream reference:

```bash
git fetch upstream main
```

### Update a Published Branch

NemoClaw Community does not allow force pushes. After you publish a branch or
use it for a pull request, do not run `git push --force` or
`git push --force-with-lease`.

Merge the current `main` branch into your published branch, then push the new
commits normally:

```bash
git checkout <short-branch-name>
git fetch upstream main
git merge upstream/main
git push origin <short-branch-name>
```

Resolve merge conflicts in the merge commit. Do not rebase a published branch
when pushing the result would rewrite remote history.

If a published branch contains a commit that must be removed or replaced,
create a new branch from the current `main` branch. Apply only the intended
changes to the new branch, push it, and open a new pull request. Close the old
pull request with a comment that identifies the replacement pull request.

Use the same process for branches in forks, even when the fork does not enforce
the repository rule.

If the example uses a Git submodule, initialize the submodule as specified in
the example's README. You do not need to initialize submodules for unrelated
examples.

## Work Within an Example

This repository does not have one shared runtime setup. Each example defines
its own development and verification workflow.

Follow the selected example's instructions for these items:

- Prerequisites and supported environments.
- Credentials and secret handling.
- Setup and configuration.
- Sandbox, network, and policy permissions.
- Startup and shutdown.
- Verification and tests.
- Cleanup and teardown.
- Known limitations.

Keep each example independently deployable. Do not make an example depend on
private files, internal systems, or local state from another example.

## Contribution Requirements

Limit each pull request to one feature, fix, documentation update, or
coordinated migration.

Apply these conditional requirements:

- When behavior changes, add or update tests.
- When setup, configuration, policy, permissions, or user-visible behavior
  changes, update the documentation.
- If the change does not require a third-party dependency, do not add one.
- When dependencies or distributed third-party content change, update
  [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).

Apply these requirements to all pull requests:

- Preserve partner and community attribution, including names and credits.
- Use placeholders for private values in public configuration and
  documentation.
- Do not commit secrets, local `.env` files, private certificates, token
  caches, generated snapshots, generated runtime state, or private workspace
  details.
- Do not add internal-only links to public documentation.

## Write for a Public Repository

Write all repository content for a public audience. This rule applies to issues,
pull requests, review comments, commit messages, code comments, documentation,
tests, logs, generated artifacts, and uploaded files.

Follow [WRITING.md](WRITING.md) for plain-language guidance. Use the approved
terms in the
[controlled-word list](.agents/skills/_shared/controlled-words.md). These rules
apply to content written by people and coding agents.

Before you publish content, remove or replace all nonpublic information,
including:

- Internal project, environment, profile, host, service, team, or distribution
  list names.
- Private URLs, repository paths, ticket identifiers, and workspace paths.
- Screenshots, logs, configuration values, or commands that expose nonpublic
  information.
- Company-specific shorthand that a public contributor cannot understand.

Use a public, generic description when the exact internal name is not required.
For example, use `enterprise environment`, `private certificate authority`, or
`internal tracking system` as appropriate. Do not publish the original value in
an example, quotation, test fixture, commit history, or pull request discussion.

If public text cannot describe the change safely, coordinate privately with a
maintainer before submission. Coding agents must inspect their proposed output
against these rules before they post or commit it. A human contributor remains
responsible for reviewing agent-generated content before merge. Automated
checks and controlled words do not replace these reviews.

Use these rules during checks:

- If the change does not require an external system for a check, do not contact
  that system.
- If the change does not require a live service for a check, do not start that
  service.
- Before you contact an external system or start a live service, confirm that
  you have the required credentials and authorization.

## Check Your Changes

After you commit your changes, run these commands from the repository root:

```bash
python3 scripts/check_license_headers.py --check
git fetch upstream main
git diff --check upstream/main...HEAD
```

If you have unstaged changes, also run this command:

```bash
git diff --check
```

If you have staged but uncommitted changes, also run this command:

```bash
git diff --cached --check
```

These commands do not replace example-specific verification. For each changed
example, run the checks that its README specifies.

Catalog pull requests include a preview artifact. Merges to `main` deploy
automatically through GitHub Pages. Maintainers can use the
[catalog deployment runbook](docs/catalog-deployment.md) for setup and
verification.

Run the documented setup, syntax, unit, configuration, and teardown-safe checks.
A stable check gives the same result when its inputs do not change. A
teardown-safe check does not leave services or temporary resources active.

Use the smallest stable check that shows the changed behavior.

In the pull request description, include this check information:

- The exact commands that you ran.
- The result of each command.
- The verification that you did not complete and the reason.
- The required live, hardware-specific, credentialed, or external-system
  verification that remains.

Before you report that a check passed, run it after the last change that can
affect its result.

When adding, moving, or renaming an example, follow the
[example taxonomy and naming policy](.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md)
and its linked restructure checklist.

## Add a New Example

Before implementation, discuss the example's location, name, and provenance
with the maintainers. Provenance identifies the example's origin, history,
contributors, and contributor organizations.

Use the canonical [example README template](#example-readme-template) for the
top-level README. The template defines the required opening information. Keep
the expanded sections appropriate for the example and its deployment paths.

Document this information for a new example:

- Its purpose, intended users, and support boundary.
- Its contributor or organizational provenance.
- Its prerequisites and supported environments.
- Its architecture and major components.
- Its credential and secret handling.
- Its setup and configuration.
- Its sandbox, network, and policy permissions.
- Its startup behavior.
- Its verification steps and expected results.
- Its teardown and cleanup.
- Its known limitations.
- Its third-party dependencies and license obligations.

Add the example to the [example catalog](examples/README.md).

## Example README Template

Use this template as the required information contract for each new example.
The opening gives a reader the information needed to decide whether to run or
adapt the example. The expanded headings are flexible, but applicable
credential, external-data, permission, cost, destructive-action, and security
disclosures are required.

### Before You Draft

Before drafting, read this entire template, this contributor guide, the
[writing guide](WRITING.md), the [support policy](SUPPORT.md), the
[example taxonomy](.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md),
and the complete example directory. Inspect its implementation, scripts,
configuration, tests, and existing documentation. Also read one strong README
for a similar example type.

Have your coding agent read the same sources. Ask it to draft from that
evidence, not from an issue description alone. The agent must not invent
commands, results, compatibility, support, security, or performance claims.
Remove secrets and nonpublic information, and use obvious placeholders for
private values. A human contributor must review and correct the draft before
submission.

### Evidence Levels

Choose the lowest level that fully matches the completed verification:

- `live end-to-end`: The intended user workflow completed in the documented
  target environment, including its required live services or hardware.
- `integration`: Multiple connected components were exercised, but the full
  intended workflow or target environment was not.
- `local/static`: Verification was limited to local, unit, syntax,
  configuration, documentation, or other non-live checks.

Do not infer a higher evidence level from intended architecture, partial
results, or unverified contributor claims.

### Copyable Template

````markdown
<!--
Before drafting, read CONTRIBUTING.md, WRITING.md, the example taxonomy, and
the complete example directory. Replace every placeholder and remove all
authoring comments before submission.
-->

# [Replace with a recognizable example name]

[For an intended user, this example performs a concrete job so they can obtain
an observable result.]

## Screenshot

![Describe the visible workflow or result and its relevant context](path-to-current-sanitized-screenshot-or-gif)

[Explain what the screenshot demonstrates and what the reader should notice.]

<!--
The screenshot or GIF must show the actual workflow, generated artifact, or
observable result. A logo, branding banner, or architecture diagram alone does
not satisfy this requirement.

For a command-line example, show representative terminal-result evidence and
also preserve the essential expected output as searchable text.
-->

## At A Glance

| Question | Answer |
| --- | --- |
| Category | [Choose one: NVIDIA Recipe, Partner Recipe, Community Recipe, Field Demo, Launchable, or Developer Tool] |
| Contributor or provenance | [Name the person or organization responsible for the example.] |
| Use this when | [Name the specific user, scenario, or operational need.] |
| You will get | [Name the observable workflow, output, artifact, or result.] |
| Runs on | [Name the required host, platform, operating system, or hardware.] |
| Requires | [List the software, services, credentials, and prerequisite state.] |
| Verified on | [Give the exact environment and versions covered by completed evidence, or state "Not yet verified."] |
| Evidence level | [Choose one: live end-to-end, integration, or local/static.] |
| Support and maturity | [State the documented maturity and support boundary; otherwise state "Best-effort community support" and link to the repository support policy.] |
| External access, data, and actions | [Name external destinations, data transmitted, write actions, costs, or state "None."] |
| Start here | [Link to the recommended or lowest-risk start path.] |
| Confirm success | [Link to verification instructions and expected results.] |

<!--
Use the canonical category exactly. Keep category separate from contributor
provenance.

Use "verified on" only when completed evidence supports the exact environment.
Do not substitute "supported on" unless there is an actual support commitment.
Evidence level describes completed verification; it does not establish support
or maturity. Use the definitions in CONTRIBUTING.md and choose the lowest level
that fully matches the completed verification.
-->

## [Choose: Start Here, Quickstart, Or Setup]

[Provide the shortest verified path to the first useful result, or link to the
canonical deployment-specific instructions.]

[When multiple paths exist, identify the recommended or lowest-risk path first,
then link the alternatives.]

## [Choose: Verification Or Confirm Success]

**Evidence level:** [Choose: live end-to-end, integration, or local/static.]

[Give the exact command or action used to verify the example.]

**Expected result:**

```text
[Show the observable success result.]
```

**This verifies:** [State exactly what the check proves.]

**This does not verify:** [State material boundaries, skipped live systems, or
remaining validation.]
````

### Required Authoring Rules

- Put material credential, data-sharing, permission, cost, write, or
  destructive-action warnings before the command that triggers them.
- Keep the example name recognizable. Put the audience, job, and result in the
  sentence immediately below it.
- Use the canonical category independently from contributor or organizational
  provenance.
- Preserve partner and community attribution.
- Distinguish `required`, `designed for`, `verified on`, and `supported`. These
  terms are not interchangeable.
- Use the lowest evidence level that fully matches the completed verification.
- Include expected results as text even when a screenshot shows them.
- Use obvious placeholders for credentials and private values.
- Do not include secrets, internal links, tenant details, private paths, or
  nonpublic environment names.
- Do not use unqualified claims such as "secure," "safe," "production-ready,"
  "easy," or "fast."
- A logo, header graphic, or architecture diagram does not replace the required
  result screenshot.
- Quickstart and verification may link to deployment-specific guides instead of
  duplicating them.
- Remove unused placeholders, authoring comments, and optional sections before
  submission.

### Optional Expanded Sections

Add these sections when they improve the example:

- What this example does.
- Architecture and major components.
- Prerequisites and supported or verified environments.
- Credentials and secret handling.
- Security, data, permissions, network policy, and external side effects.
- Setup and configuration.
- Startup and operation.
- Verification and expected results.
- Teardown and cleanup.
- Troubleshooting.
- Known limitations.
- Provenance, attribution, and support.
- Third-party dependencies and license obligations.

The headings are optional. Applicable credentials, external-data, permissions,
cost, destructive-action, and security disclosures are not optional and must
appear before the relevant action.

## Move or Rename an Example

Before you move or rename an example, complete these steps:

- Search the repository for the old path and name.
- Search open pull requests for the old path and name.
- Identify affected pull requests and downstream documentation.
- Record the merge order.
- Coordinate the update sequence with owners of dependent pull requests.
- Keep path changes separate from unrelated runtime or dependency changes.

In the pull request for the move, complete these steps:

- Add a table that maps each old path to its new path.
- Update links, commands, ownership, notices, and `.gitmodules` entries.
- List identifiers that must keep an old name for compatibility.
- Give instructions for existing clones if a submodule moves.
- Verify each moved example from its new location.
- Remove obsolete paths.

After the migration merges, owners of dependent pull requests must fetch the
updated `main` branch from `upstream`. Then, each owner must merge
`upstream/main` into the pull request branch and push normally.

After each branch update, confirm that the pull request does not restore an
obsolete path.

## Sign Off Every Pull Request

Every pull request description must include a
[`Signed-off-by:` declaration](https://developercertificate.org/) for Developer
Certificate of Origin (DCO) compliance. The pull request author must add the
declaration before requesting review.

Add this line to the pull request description:

```text
Signed-off-by: Your Name <your.email@example.com>
```

Use your own name and email address. Individual commits may also include
sign-off trailers, but the required check validates the declaration in the pull
request description. The example name and email address do not satisfy the
required check.

DCO sign-off is separate from cryptographic commit signing.

Maintainers do not accept pull requests without the required declaration.

## Open a Pull Request

Complete [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md).

Your pull request should include:

- The problem and expected result.
- The examples and repository areas that the change affects.
- The exact check commands and results.
- An explanation for checks that you did not run.
- The documentation and dependency changes.
- For a migration, its details and downstream follow-up work.
- Your DCO sign-off declaration.

Submit all changes to `main` through a pull request.

Do not rewrite the history of a published pull request branch. If a branch
cannot be corrected with new commits or a merge from `main`, replace it with a
new branch and pull request as described in
[Update a Published Branch](#update-a-published-branch).

Maintainers merge a pull request only when all these conditions are true:

- The pull request description satisfies the DCO requirement.
- The pull request satisfies the license-header requirements.
- The pull request has no unresolved review conversations.
- A maintainer approves the pull request.

Maintainers review and merge contributions according to
[GOVERNANCE.md](GOVERNANCE.md).

Maintainers may require NVIDIA internal open-source review for these changes:

- A major scope change.
- A new dependency.
- A distribution scope change.
- Publication of a container image.
- A material change to the project license or compliance surface.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
