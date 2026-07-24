# Contributing To NemoClaw Community

Thank you for your interest in improving NemoClaw Community.

## Ways To Contribute

- Improve NemoClaw example documentation.
- Fix setup, teardown, or sandbox lifecycle bugs.
- Add or improve agent skills inside an example.
- Improve source ETL, bridge, or policy configuration.
- Report reproducible issues with environment details.

## Signing Your Work 

* We require that all contributors "sign-off" on their commits. This certifies that the contribution is your original work, or you have rights to submit it under the same license, or a compatible license. Any contribution which contains commits that are not Signed-Off will not be accepted.
  
* To sign off on a commit you simply use the `--signoff` (or `-s`) option when committing your changes:
  
  ```bash
  $ git commit -s -m "Add cool feature."
  ```
  
  This will append the following to your commit message:
  
  ```
  Signed-off-by: Your Name <your@email.com>
  ```
  
* Full text of the DCO (https://developercertificate.org/):
  
  ```
    Developer Certificate of Origin
    Version 1.1
    Copyright (C) 2004, 2006 The Linux Foundation and its contributors.
    Everyone is permitted to copy and distribute verbatim copies of this
    license document, but changing it is not allowed.
    Developer's Certificate of Origin 1.1
    By making a contribution to this project, I certify that:
    (a) The contribution was created in whole or in part by me and I
        have the right to submit it under the open source license
        indicated in the file; or
    (b) The contribution is based upon previous work that, to the best
        of my knowledge, is covered under an appropriate open source
        license and I have the right under that license to submit that
        work with modifications, whether created in whole or in part
        by me, under the same open source license (unless I am
        permitted to submit under a different license), as indicated
        in the file; or
    (c) The contribution was provided directly to me by some other
        person who certified (a), (b) or (c) and I have not modified
        it.
    (d) I understand and agree that this project and the contribution
        are public and that a record of the contribution (including all
        personal information I submit with it, including my sign-off) is
        maintained indefinitely and may be redistributed consistent with
        this project or the open source license(s) involved.
  ```

## Development Setup

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community
git checkout -b my-feature
```

Choose an example from the [example catalog](examples/README.md) and follow its
README and verification guide.

## Local Checks

Run the lightweight repository checks before opening a pull request:

```bash
python scripts/check_license_headers.py --check
git diff --check
bash -n examples/recipes/nvidia/developer-community-chief-of-staff/scripts/*.sh
python -m py_compile $(find examples/recipes/nvidia/developer-community-chief-of-staff -name '*.py' -print)
```

## Pull Request Guidelines

- Keep each pull request focused on one feature, fix, or documentation update.
- Update documentation when setup, configuration, policy, or user-visible behavior changes.
- Add third-party dependencies only when needed, and update [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).
- Do not commit secrets, local `.env` files, generated snapshots, private certificates, or token caches.
- Do not report security issues in public pull requests or issues. Follow [SECURITY.md](SECURITY.md).

When adding, moving, or renaming an example, follow the
[example taxonomy and naming policy](.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md)
and its linked restructure checklist.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
