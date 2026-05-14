# Contributing To NemoClaw Community

Thank you for your interest in improving NemoClaw Community.

## Ways To Contribute

- Improve NemoClaw example documentation.
- Fix setup, teardown, or sandbox lifecycle bugs.
- Add or improve agent skills inside an example.
- Improve source ETL, bridge, or policy configuration.
- Report reproducible issues with environment details.

## Developer Certificate Of Origin

All contributions must include a `Signed-off-by` line in each commit message, certifying that you wrote or have the right to submit the code under this project's open-source license. This is the [Developer Certificate of Origin](https://developercertificate.org/).

Add the sign-off automatically with:

```bash
git commit -s -m "Describe the change"
```

## Development Setup

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community
git checkout -b my-feature
```

For the current example, follow [examples/personal-community-sentiment-triage/README.md](examples/personal-community-sentiment-triage/README.md).

## Local Checks

Run the lightweight repository checks before opening a pull request:

```bash
python scripts/check_license_headers.py --check
git diff --check
bash -n examples/personal-community-sentiment-triage/scripts/*.sh
python -m py_compile $(find examples/personal-community-sentiment-triage -name '*.py' -print)
```

## Pull Request Guidelines

- Keep each pull request focused on one feature, fix, or documentation update.
- Update documentation when setup, configuration, policy, or user-visible behavior changes.
- Add third-party dependencies only when needed, and update [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).
- Do not commit secrets, local `.env` files, generated snapshots, private certificates, or token caches.
- Do not report security issues in public pull requests or issues. Follow [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
