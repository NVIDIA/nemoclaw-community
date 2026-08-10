<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# NemoClaw Community Controlled Words

Use these terms in changed explanatory text. This list improves consistency; it
does not detect every secret, credential, or nonpublic identifier. Review all
content before publication.

Keep literal commands, code identifiers, API fields, quoted output, and official
third-party names exact. Add a short explanation when a literal term is not
clear to a public reader.

Apply the list to changed text. Put unrelated terminology cleanup in a focused
follow-up pull request.

| Use | Avoid or clarify | Guidance |
| --- | --- | --- |
| NemoClaw | Nemoclaw, Nemo Claw | Use the official product name. |
| NemoClaw Community | community NemoClaw, community repo | Use for this project or repository. |
| OpenShell | Openshell, Open Shell | Use the official product name. |
| example | demo, sample | Use for an independently deployable contribution. Use `demo` only when demonstration is the explicit purpose. |
| recipe | workflow, example | Use for content under `examples/recipes/`. Do not use it as a synonym for every example. |
| contributor | developer, submitter | Use for a person who contributes a change. Use a more specific role when necessary. |
| maintainer | owner, administrator | Use for a project maintainer. Use `administrator` only for a system permission. |
| pull request | PR on first use | Write `pull request (PR)` before using `PR` in longer text. |
| repository | repo | Prefer `repository` in explanatory text. Literal names and commands can use `repo`. |
| setup | set up | Use `setup` as a noun or adjective. Use `set up` as a verb. |
| cleanup | clean up | Use `cleanup` as a noun or adjective. Use `clean up` as a verb. |
| sign in | log in, login | Use `sign in` as a verb. Preserve literal command and interface labels. |
| environment variable | env var | Use the full term on first use. |
| API key | token, credential | Use the precise credential type. Do not publish its value. |
| access token | API key, credential | Use the precise credential type. Do not publish its value. |
| secret | credential | Use `secret` for a value that must remain confidential. Use `credential` for authentication material. |
| certificate authority (CA) | certificate provider | Define `CA` on first use. |
| CA certificate | CA cert | Prefer the full term in explanatory text. |
| sandbox | container, virtual machine | Use the runtime's documented boundary. These terms are not interchangeable. |
| policy | configuration | Use `policy` for enforced permissions or restrictions. |
| allowlist | whitelist | Use inclusive terminology. |
| blocklist | blacklist | Use inclusive terminology. |
| primary | master | Use `primary` for a general role. Preserve the literal Git branch name. |

## Public Replacements

Do not add actual internal terms to this public list. Replace nonpublic details
with the most accurate generic term:

| Use | For |
| --- | --- |
| enterprise environment | A nonpublic development or deployment environment. |
| private service | A service that public contributors cannot access. |
| private endpoint | A nonpublic URL or hostname. |
| private certificate authority | A certificate authority that is not publicly available. |
| internal tracking system | A nonpublic issue or work-tracking system. |
| maintainer team | A nonpublic team or distribution-list name. |

Do not preserve the original nonpublic name in parentheses, examples, test data,
commit messages, or review comments.

## Maintain the List

Add an entry when it resolves recurring ambiguity, separates concepts whose
difference affects behavior, or preserves an official public name. Confirm the
term against current code, commands, tests, and public documentation.

Do not add every acceptable English word. Do not use this list to rename a
command, identifier, schema field, user-interface label, or third-party product.
Such a rename requires a separate interface decision.
