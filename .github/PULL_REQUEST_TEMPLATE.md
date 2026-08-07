<!--
Use a Conventional Commit title:
feat(scope), fix(scope), docs, chore(scope), refactor(scope), test(scope),
ci(scope), or perf(scope).
-->

## Related Issue

Closes #

## Description

Describe what changed and why.

## Verification

- [ ] `python3 scripts/check_license_headers.py --check`
- [ ] `python3 scripts/check_label_taxonomy.py --check` when governance metadata changes
- [ ] `git diff --check`
- [ ] Relevant example setup or syntax checks

## Documentation Writer Review

<!--
Required for code and documentation changes after implementation and applicable
validation are complete. Record changed documentation paths as evidence. For
`no-docs-needed`, explain why users are not affected. A blocked result is not
ready to merge.
-->
- [ ] Documentation writer review completed for the final changes
- Result: `docs-updated` | `no-docs-needed` | `blocked`
- Evidence or justification:
- Reviewer:
- [ ] Changed user-facing text follows the
  [writing guide](https://github.com/NVIDIA/nemoclaw-community/blob/main/WRITING.md)
  and
  [controlled-word list](https://github.com/NVIDIA/nemoclaw-community/blob/main/.agents/skills/_shared/controlled-words.md).
- [ ] A public contributor can understand the changed text without internal
  company context.
- [ ] I reviewed any agent-generated text before submission.

## Release And Compliance

- [ ] No secrets or credentials are included, including API keys, access tokens,
  passwords, local `.env` files, private certificates, or token caches.
- [ ] No nonpublic project names, environment names, hostnames, URLs, ticket
  identifiers, workspace paths, logs, screenshots, or configuration values are
  included.
- [ ] Third-party dependency changes are reflected in `THIRD-PARTY-NOTICES`.
- [ ] Public content uses sanitized examples and placeholders instead of private
  values.
- [ ] I added my DCO sign-off declaration to this pull request description.

<!-- Replace the example values and add an uncommented line in this format: Signed-off-by: Your Name <your.email@example.com> -->
