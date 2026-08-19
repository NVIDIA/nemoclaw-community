<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# NemoClaw Community Writing Guide

Use this guide for clear, consistent, public communication. It uses the
plain-language principles in
[ASD-STE100 Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf),
but this project does not claim ASD-STE100 compliance.

## Scope

Apply this guide to changed explanatory text, including:

- Documentation and examples.
- User-facing messages and command help.
- Code comments and test descriptions.
- Issues, pull request descriptions, review comments, and commit messages.
- Contributor guidance and coding-agent output.

Do not rewrite literal commands, source identifiers, API fields, quoted output,
or official third-party names only to satisfy this guide. Explain an unfamiliar
literal value when readers need context.

## Protect Nonpublic Information

This is a public repository. Do not include secrets, credentials, or nonpublic
identifiers in repository content or GitHub discussions.

Replace internal jargon and private names with accurate public terms. Remove
private URLs, hostnames, paths, ticket identifiers, environment names, team
names, logs, screenshots, and configuration values before publication. Do not
use realistic secret values as examples.

Use obvious placeholders such as `<api-key>`, `<organization>`,
`example.internal`, or `/path/to/project`. Confirm that a sanitized example
cannot be mistaken for a working credential or a real private endpoint.

If an exact internal value is necessary to investigate a problem, use an
approved private channel. Do not add the value to a public issue or pull
request.

## Use Controlled Terms

Use one term for one concept. Choose the shortest familiar term that preserves
the technical meaning. Prefer terms already visible in the user interface,
command line, public documentation, and nearby code.

Use the
[controlled-word list](.agents/skills/_shared/controlled-words.md) for project
terms. If a required public term is missing, propose an update to the list in
the same pull request.

Do not use a controlled-word substitution when it would change a literal
identifier or an official product, protocol, API, or third-party name.

## Keep Claims Accurate

- Verify commands, defaults, and behavior against current source, tests, or
  scripts.
- Name the exact boundary for security, persistence, compatibility, and support
  claims.
- State the failure or fallback result for a conditional or best-effort control.
- Identify the credential type without including the credential value.
- Do not describe a change as safe, ready, supported, or tested without naming
  the condition or evidence that establishes the claim.

## Write Direct Sentences

- State the actor and the action.
- Use active voice when it makes the actor clearer.
- Put conditions before the action when the condition determines the result.
- Use short sentences. Split sentences that contain several independent ideas.
- Use concrete nouns and verbs.
- Use `must` for requirements, `can` for capability, and `may` for permission.
- Avoid vague modifiers such as `simple`, `easy`, `obvious`, `just`, and
  `usually` unless they add measurable information.
- Define an abbreviation the first time that you use it, unless the abbreviation
  is more familiar than its expanded form.

## Write Procedures

- Introduce the goal before the steps.
- Put one action in each numbered step.
- Show commands exactly as users must enter them.
- State where to run a command and what successful output means.
- Identify prerequisites before the procedure.
- Describe cleanup and any persistent changes.

## Review Changed Text

Before submission, confirm that changed text:

- Is understandable without private company context.
- Uses the controlled terms consistently.
- Contains no secrets, credentials, or nonpublic identifiers.
- Matches the implemented behavior and current user interface.
- Distinguishes requirements from recommendations.
- Uses placeholders for private or user-specific values.

Writing findings are normally review suggestions. Treat a finding as blocking
when ambiguity or disclosure can affect security, privacy, data safety,
behavior, testing, licensing, or release decisions.
