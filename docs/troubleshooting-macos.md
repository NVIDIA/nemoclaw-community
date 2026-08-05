<!-- SPDX-FileCopyrightText: Copyright (c) 2026 munnamihir -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# macOS onboarding troubleshooting

Common failures when setting up NemoClaw examples on macOS, with the exact
error text and its fix. Run `scripts/preflight-macos.sh` first — it checks
for most of these before you install anything.

## Homebrew: `undefined method '[]' for nil` during `ca-certificates`

Symptom, while installing `node@22` or another formula:
==> Pouring ca-certificates--...bottle.tar.gz
Error: undefined method '[]' for nil
/opt/homebrew/Library/Homebrew/utils/bottles.rb:...:in 'Utils::Bottles.load_tab'
Homebrew's bottle metadata is stale. Reset and update it:

```bash
brew update-reset
brew update
```

Then retry the original `brew install`.

## Homebrew: `brew update` fails with `Symbol not found: _curl_global_trace`

Symptom:
dyld[...]: Symbol not found: _curl_global_trace
Referenced from: /opt/homebrew/Cellar/git/.../git-remote-http
error: git-remote-https died of signal 6
fatal: remote helper 'https' aborted session
Error: Fetching /opt/homebrew failed!
Homebrew's own `git` is linked against a newer `libcurl` than the system
provides, so it can't fetch. Bypass brewed git for the update:

```bash
HOMEBREW_FORCE_BREWED_GIT=0 brew update
```

Once that succeeds, reinstall git so it relinks cleanly:

```bash
brew reinstall git
```

## Installer: `Your Command Line Tools are too outdated`

Symptom, from the OpenShell or NemoClaw installer:
Error: Your Command Line Tools are too outdated.
Update them from Software Update in System Settings.
Reinstall the Command Line Tools:

```bash
sudo rm -rf /Library/Developer/CommandLineTools
sudo xcode-select --install
```

Wait for the popup to finish ("Software Installed"), then confirm:

```bash
xcode-select -p     # -> /Library/Developer/CommandLineTools
```

If `xcode-select -p` reports "unable to get active developer directory"
after the removal, the reinstall popup hasn't completed — run
`sudo xcode-select --install` again and wait for it.

## Node: `command not found` after a global npm install

Symptom: a globally installed CLI (e.g. via `npm install -g`) reports
`command not found`, even though the install succeeded.

The npm global bin directory isn't on your `PATH`. Find it and add it:

```bash
npm prefix -g
echo 'export PATH="'"$(npm prefix -g)"'/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

If you use `nvm` or `fnm`, make sure your shell rc sources it before this
line so the right Node version resolves first. Check for shadowing with:

```bash
which -a node
```

## Docker: CLI present but sandbox creation fails

Symptom: `docker --version` works, but creating a sandbox fails with a
daemon/connection error.

Docker Desktop isn't running. Start it and wait for the menu-bar whale to
settle:

```bash
open -a Docker
```

Then re-run `scripts/preflight-macos.sh` — the docker check should pass.
