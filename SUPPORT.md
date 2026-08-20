# Support

NemoClaw Community is an example-oriented open-source repository. Support is best-effort unless a specific NVIDIA product agreement says otherwise.

## Questions And Issues

- Use GitHub Issues for reproducible bugs and feature requests.
- Include your OS, Docker version, NemoClaw version, OpenShell version, example path, command output, and relevant sanitized configuration.
- Do not include secrets, tokens, private certificates, tenant IDs, or private workspace content.

## macOS onboarding (Apple Silicon)

Examples target a Linux + Docker host. Contributors on macOS often fail before the first example starts. Run this read-only doctor first:

```bash
bash scripts/preflight-macos.sh
```

Known signatures:

| Error text | Likely cause | Fix |
|---|---|---|
| `undefined method '[]' for nil` in `Utils::Bottles.load_tab` while pouring `ca-certificates` | Stale Homebrew tap metadata | `brew update-reset` |
| `Symbol not found: _curl_global_trace` from Homebrew git | Brewed git vs system libcurl | `brew reinstall git` after `brew update-reset` |
| `Command Line Tools are too outdated` from the OpenShell installer | Stale CLT package | `sudo rm -rf /Library/Developer/CommandLineTools && sudo xcode-select --install` |
| `command not found: node` after a global npm install | nvm/fnm/brew PATH order | Open a new shell; confirm `command -v node` is Node 22+ |

The doctor does not install software, write credentials, or mutate PATH.

## Security

Do not report vulnerabilities through GitHub Issues. Follow [SECURITY.md](SECURITY.md).

## Maintainer Response

Maintainers prioritize issues that include clear reproduction steps, expected behavior, actual behavior, and a minimal sanitized configuration.
