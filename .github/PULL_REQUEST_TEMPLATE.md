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

## Release And Compliance

- [ ] No secrets, local `.env` files, private certificates, snapshots, or token caches are included.
- [ ] Third-party dependency changes are reflected in `THIRD-PARTY-NOTICES`.
- [ ] Public documentation is free of internal-only links or private workspace details.
- [ ] Commits include DCO sign-off (`git commit -s`).
