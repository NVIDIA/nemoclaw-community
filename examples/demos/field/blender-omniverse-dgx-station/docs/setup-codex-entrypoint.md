# Codex Entry-Point Setup

This optional guide adds Codex CLI as a general entry point for the Blender and
Omniverse environment created by the primary
[DGX Station ARM64 setup guide](setup-dgx-station-arm64.md). Complete and
validate that guide first. Codex then delegates specialized execution to the
existing NemoClaw Hermes agent instead of replacing it.

This path is designed for NVIDIA DGX Station running Ubuntu 24.04 ARM64.

## Process Summary

1. Install and authenticate Codex CLI.
2. Link the Codex Hermes-coaching skills and upstream OV add-on skills.
3. Validate direct Hermes execution through OpenShell.
4. Start Codex and ask it to coach Hermes through a Blender or OVPhysX task.

## Prerequisites

- The primary setup guide passes through its Blender, OVRTX, OVPhysX, vLLM,
  NemoClaw, OpenShell, Hermes, and Blender MCP validations.
- `$GUIDE_REPO`, `$OV_REPO`, and `$NEMOCLAW_SANDBOX_NAME` identify the same
  checkouts and sandbox used by the primary guide.
- An OpenAI account with Codex access, or an OpenAI Platform API key.
- Browser access for the default ChatGPT sign-in flow. Device-code or API-key
  authentication can be used on a headless system.
- Node.js 22 or newer with `npm`. The primary guide's validated DGX Station
  environment provides Node.js 22.

## 1. Restore Project Variables

### Command

```bash
export GUIDE_REPO="$HOME/work/nemoclaw-community/examples/demos/field/blender-omniverse-dgx-station"
export DEMO_ROOT="$HOME/work/ov-blender-hermes-demo"
export OV_MONOREPO="$DEMO_ROOT/omniverse-labs"
export OV_REPO="$OV_MONOREPO/projects/ov-blender-example"
export NEMOCLAW_SANDBOX_NAME="ov-blender-hermes"
export PATH="$HOME/.local/bin:$PATH"
```

### Validation

```bash
test -f "$GUIDE_REPO/README.md"
test -f "$OV_REPO/skills/manifest.json"
nemohermes "$NEMOCLAW_SANDBOX_NAME" status
```

The sandbox status must report `Hermes Agent: running`.

## 2. Install Codex CLI

### Command

Install the official Codex npm package into the user's local prefix. The
package publishes a native Linux ARM64 dependency and does not require root.

```bash
npm install --global --prefix "$HOME/.local" @openai/codex
export PATH="$HOME/.local/bin:$PATH"
```

Use the same command to update Codex later:

```bash
npm install --global --prefix "$HOME/.local" @openai/codex@latest
```

### Validation

```bash
command -v codex
codex --version
```

## 3. Authenticate Codex

> **Human step: sign in to Codex.** Run `codex login` and complete the browser
> flow with an account that has Codex access. On a headless SSH session, use
> `codex login --device-auth` instead.

API-key authentication is an alternative:

```bash
export OPENAI_API_KEY='sk-...'
printenv OPENAI_API_KEY | codex login --with-api-key
unset OPENAI_API_KEY
```

Do not commit credentials or place them in this repository.

### Validation

```bash
codex login status
```

## 4. Install the Codex and OV Skills

The installer creates symlinks in `$HOME/.agents/skills`. It links this
project's Hermes-coaching skills and every `SKILL.md` directory under the
official project's checked-out `skills` tree. The links keep Codex on the same
OV skill source as Hermes and automatically follow later `git pull` updates.

### Command

```bash
cd "$GUIDE_REPO"
git -C "$OV_MONOREPO" checkout main
git -C "$OV_MONOREPO" pull --ff-only origin main
./scripts/install_codex_skills.sh "$OV_REPO"
```

The installer refuses to overwrite an unrelated skill with the same name.

### Validation

```bash
test -L "$HOME/.agents/skills/coach-nemoclaw-hermes"
test -f "$HOME/.agents/skills/coach-nemoclaw-hermes/SKILL.md"
test -L "$HOME/.agents/skills/coordinate-nemoclaw-blender"
git -C "$OV_MONOREPO" rev-parse HEAD

expected="$(find "$OV_REPO/skills" -mindepth 2 -maxdepth 2 \
  -name SKILL.md | wc -l)"
installed="$(find "$OV_REPO/skills" -mindepth 2 -maxdepth 2 \
  -name SKILL.md -printf '%h\n' | while read -r skill; do
    test -f "$HOME/.agents/skills/$(basename "$skill")/SKILL.md" && echo ok
  done | wc -l)"
test "$installed" -eq "$expected"
echo "linked $installed upstream OV skills"
```

Codex detects skill changes automatically. If an already-running Codex session
does not show them, exit and start a new session.

## 5. Validate the Delegation Path

First call Hermes directly through OpenShell. This isolates the existing
specialist path from Codex setup.

### Command

```bash
openshell sandbox exec \
  --name "$NEMOCLAW_SANDBOX_NAME" \
  --timeout 1200 --no-tty -- \
  hermes chat -Q --max-turns 30 -q \
  "Render the current scene as a beauty shot with OVRTX. Preserve the scene and report the host PNG path."
```

The validated wrapper form is equivalent:

```bash
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 1200 -- \
  hermes chat -Q --max-turns 30 -q \
  "Render the current scene as a beauty shot with OVRTX. Preserve the scene and report the host PNG path."
```

### Validation

Hermes must reach Blender MCP, render through OVRTX, and report a non-empty host
PNG. Fix this path using the primary guide's troubleshooting section before
involving Codex.

## 6. Use Codex as the Entry Point

Start Codex from the shared work directory so it can inspect the guide, OV
checkout, and host output paths.

### Command

```bash
cd "$HOME/work"
codex
```

Then send this example coaching request:

```text
Use $coach-nemoclaw-hermes. Coach Hermes through this task: render the current
Blender scene as an OVRTX beauty shot. Delegate the Blender and OVRTX work to
Hermes, avoid overlapping Hermes runs, allow it enough time to finish, and
verify the resulting host PNG. Do not control Blender directly unless I
authorize fallback execution.
```

For an example native-physics task:

```text
Use $coach-nemoclaw-hermes. Coach Hermes through this task: run the configured
native OVPhysX stair-drop simulation and create a GIF of the blocks falling
down the stairs. Delegate runtime work to Hermes, prevent overlapping runs,
allow it enough time to iterate, and verify the native receipt and host GIF.
Do not control Blender directly unless I authorize fallback execution.
```

For another task, replace only the sentence after `Coach Hermes through this
task:`. Keep the delegation, timing, overlap, validation, and fallback language.

Codex may ask for permission before its first `nemohermes` or `openshell`
command. Approve only the displayed command and scope needed for the task.

### Validation

For rendering, Codex must identify a non-empty host PNG produced through
Hermes. For physics, require:

- `native_status: pass-real`;
- `physics_source: native-ovphysx-readback`;
- a non-empty host GIF;
- a clear distinction between native simulation and Blender replay rendering.

Codex should report its coordination and validation separately from Hermes's
Blender and OV runtime execution.

## Troubleshooting

### Standalone installer reports GitHub HTTP 403

The standalone installer at `https://chatgpt.com/codex/install.sh` resolves its
release through GitHub's unauthenticated API. A DGX Station behind a shared
public IP can exhaust GitHub's 60-request hourly allowance even when `gh` is
authenticated, because the installer does not use the `gh` credential.

Use the npm installation command from section 2. To confirm this specific
failure mode:

```bash
curl -sS -D /tmp/codex-github-headers \
  https://api.github.com/repos/openai/codex/releases/latest \
  -o /tmp/codex-github-response.json
grep -i '^x-ratelimit-' /tmp/codex-github-headers
jq -r '.message // .tag_name' /tmp/codex-github-response.json
```

### Codex does not list the new skills

Confirm the links and start a new Codex process:

```bash
find "$HOME/.agents/skills" -maxdepth 2 -name SKILL.md -print
readlink -f "$HOME/.agents/skills/coordinate-nemoclaw-blender"
readlink -f "$HOME/.agents/skills/coach-nemoclaw-hermes"
```

### Codex can run Hermes but Hermes cannot reach Blender

The Codex layer is working. Return to the primary guide and check the visible
Blender process, ports 9876 and 9877, Blender MCP policy, and Hermes MCP entry.

```bash
nemohermes "$NEMOCLAW_SANDBOX_NAME" status
ss -ltnp | grep -E ':(9876|9877)'
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- hermes mcp list
```

### An upstream OV skill changed

Update the OV checkout. Symlinks require no reinstall unless upstream adds or
renames a skill directory:

```bash
git -C "$OV_MONOREPO" pull --ff-only origin main
"$GUIDE_REPO/scripts/install_codex_skills.sh" "$OV_REPO"
```
