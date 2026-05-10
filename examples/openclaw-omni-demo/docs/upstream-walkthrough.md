![NVIDIA](../../assets/nvidia_header.png)

# NemoClaw + Omni Vision Sub-Agent Setup

> This is the upstream walkthrough preserved for detail. For the standardized
> repo layout in `nemoclaw-community`, start with `../README.md`; paths in this
> document may still refer to the original root-level files.

Complete walkthrough for setting up a NemoClaw sandbox with the Nemotron-3 Nano
Omni reasoning model as a vision-capable sub-agent. The main agent (Nemotron
Super 120B, text-only) delegates image tasks to a `vision-operator` sub-agent
running the Omni model (text + image).

## Tested configuration

This recipe was last validated on 2026-05-05 with:

- Host: macOS arm64 on Apple Silicon with Docker Desktop
- NemoClaw CLI: `nemoclaw v0.0.34`
- OpenShell CLI and cluster image: `openshell 0.0.36`, `ghcr.io/nvidia/openshell/cluster:0.0.36`
- In-sandbox OpenClaw: `2026.4.24 (cbcfdf6)`
- Inference: hosted NVIDIA Endpoints, so no local GPU is required

Older `nemoclaw v0.0.24` failed against the current OpenClaw build during
onboarding with a Dockerfile patch error for
`writeConfigFile(params.nextConfig)`. If you hit that, update NemoClaw and
re-run onboarding rather than debugging the demo steps.

## Reviewer quickstart

For a fast end-to-end review, onboard a fresh sandbox, export a current NVIDIA
API key with Omni access, then run:

```bash
export SANDBOX=hclaw
export NVIDIA_API_KEY=nvapi-...
SEED_DEMO_IDENTITY=1 bash scripts/apply-omni-subagent.sh
SANDBOX="$SANDBOX" bash scripts/verify.sh
```

The smoke test fails fast if the key cannot call the `nvidia-omni` provider. A
`403 Authorization failed` at that step means the key lacks Omni access or has
expired; rotate the key and re-run the helper before debugging delegation.

## What's in this directory

| File | Purpose |
|------|---------|
| `openclaw.json` | Reference config with Omni provider + agents list (for comparison) |
| `AGENTS.md` | Workspace instructions that make the main agent delegate visual tasks |
| `TOOLS.md` | Workspace file that teaches the main agent to delegate image tasks |
| `policy.yaml` | Patched OpenShell network policy (with `node` in nvidia binaries) |
| `scripts/apply-omni-subagent.sh` | Repeatable helper that patches policy, `openclaw.json`, auth profiles, `AGENTS.md`, and `TOOLS.md` |
| `scripts/verify.sh` | End-to-end smoke test for config, gateway, direct vision, delegation, and missing-image behavior |
| `scripts/fix-spark-gateway.sh` | Recovery helper for DGX Spark/restricted netns gateway crashes |

## Known-good model IDs

Use the public NVIDIA catalog IDs below:

```text
Main text model:  nvidia/nemotron-3-super-120b-a12b
Omni model:       nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
```

Older demo notes used private or pre-release Omni IDs. If you see `model_not_found`
or `401` from the Omni provider, confirm the model ID and that your NVIDIA API key
has access to the Omni model.

## Step 1: Install NemoClaw

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc   # or source ~/.zshrc if you use zsh
```

Verify:

```bash
nemoclaw --version
openshell --version
```

Use `nemoclaw v0.0.34` or newer for this recipe. If your installed CLI is older,
rerun the installer before onboarding a fresh sandbox.

## Step 2: Onboard an OpenClaw sandbox

```bash
nemoclaw onboard
```

When prompted:

1. **Inference**: Choose `1` (NVIDIA Endpoints)
2. **API Key**: Paste your NVIDIA API key (starts with `nvapi-`)
3. **Model**: Choose `1` (Nemotron 3 Super 120B)
4. **Sandbox name**: Enter a name like `hclaw`
5. **Policy presets**: Choose "Balanced" and accept suggested `pypi` and `npm`

If you are running non-interactively, use `NEMOCLAW_SANDBOX_NAME` rather than
`--name` for older NemoClaw releases that do not expose `nemoclaw onboard --name`:

```bash
NEMOCLAW_SANDBOX_NAME=hclaw \
NEMOCLAW_NON_INTERACTIVE=1 \
NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 \
NVIDIA_API_KEY="$NVIDIA_API_KEY" \
nemoclaw onboard --fresh --non-interactive --yes-i-accept-third-party-software
```

Wait for the build + image upload to finish. Note the dashboard URL and token
command it prints.

If Docker Desktop is running but NemoClaw reports a stale Colima socket, point
NemoClaw at Docker Desktop explicitly before onboarding:

```bash
export DOCKER_HOST=unix://"$HOME"/.docker/run/docker.sock
docker info >/dev/null
nemoclaw onboard
```

Current NemoClaw prints the OpenClaw dashboard URL separately from the auth
token. Port `18789` must be forwarded before opening `http://127.0.0.1:18789/`.
If the local URL is not reachable, restart the gateway and dashboard
port-forward:

```bash
nemoclaw hclaw recover
```

Fetch the token with:

```bash
nemoclaw hclaw gateway-token --quiet
```

Replace `hclaw` with your sandbox name in both commands.

If the browser asks for auth, append `#token=<token>` to the local dashboard
URL. Use the dashboard for a visual control surface; use the OpenClaw CLI/TUI
commands below for repeatable validation.

## Step 3: Set variables

Everything below uses these — set them once:

```bash
export SANDBOX=hclaw
export DOCKER_CTR=openshell-cluster-nemoclaw
export NVIDIA_API_KEY=nvapi-...   # must have Omni access
```

> These are shell-local. If your SSH session drops or you open a new terminal
> partway through, re-run the `export` commands before continuing.

NemoClaw may not leave a plaintext `~/.nemoclaw/credentials.json` on current
releases, so do not rely on sourcing that file. Keep the key in your shell only
for the setup step. The helper streams it into the in-sandbox OpenClaw provider
config and writes the vision operator auth profile; it does not write the key to
the repo or the host-side `/tmp` backup config.

## Step 4: Apply the Omni sub-agent configuration

Run the helper from this directory:

```bash
bash scripts/apply-omni-subagent.sh
```

For fully scripted smoke tests, seed a small demo identity so the first OpenClaw
turn is not intercepted by the default `BOOTSTRAP.md` identity conversation:

```bash
SEED_DEMO_IDENTITY=1 bash scripts/apply-omni-subagent.sh
```

The helper performs the manual recipe steps safely and creates a backup directory
under `/tmp` with `UNDO.txt` instructions. It:

1. Exports the active policy, adds `/usr/local/bin/node` to the `nvidia` policy
   block if needed, and reloads the policy.
2. Patches `/sandbox/.openclaw/openclaw.json` to add:
   - provider `nvidia-omni` pointing at `https://integrate.api.nvidia.com/v1`
   - the `NVIDIA_API_KEY` value in the in-sandbox provider `apiKey` field
   - `main` + `vision-operator` entries in `agents.list`
   - the vision operator workspace at `/sandbox/.openclaw-data/workspace`
   - sub-agent limits and a longer timeout
   - sets `plugins.enabled=false` and disables enabled-by-default extensions
     this demo does not use, including browser, speech/media integrations, chat
     integrations, and unused model providers, so OpenClaw CLI checks do not
     spend minutes staging unrelated npm runtime dependencies
   - disables the default memory plugin slot and seeds runtime dependency
     sentinels for disabled bundled extensions so fresh gateway/agent startup
     does not block on unrelated npm installs
3. Recomputes `/sandbox/.openclaw/.config-hash`.
4. Creates and fixes ownership on the shared workspace, the vision operator
   session directory, both observed vision-operator agent directories, and the
   plugin runtime dependency cache path.
5. Writes the current OpenClaw auth profile format for the vision operator in
   both observed agent config paths. Current OpenClaw custom providers read the
   provider `apiKey` directly, but the auth profile is still written for
   compatibility with builds that consult per-agent auth stores:

   ```json
   {
     "version": 1,
     "profiles": {
       "nvidia-omni:default": {
         "type": "api_key",
         "provider": "nvidia-omni",
         "key": "<nvapi-key>",
         "displayName": "NVIDIA Omni"
       }
     },
     "order": {
       "nvidia-omni": ["nvidia-omni:default"]
     }
   }
   ```

6. Copies `AGENTS.md` and `TOOLS.md` into the workspace.
7. Creates `/sandbox/.openclaw/tasks -> /sandbox/.openclaw-data/tasks` for
   OpenClaw builds that expect a writable task-registry path.

Verify the config:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc \
  'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; \
   export OPENCLAW_TEST_ONLY_PROVIDER_PLUGIN_IDS=nvidia; \
   openclaw agents list'
```

Expected:

```text
Agents:
- main (default)
  Model: inference/nvidia/nemotron-3-super-120b-a12b
- vision-operator
  Model: nvidia-omni/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
```

Then verify the hot-reloaded config and filesystem paths directly:

```bash
docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- bash -lc '
python3 - <<PY
import json
import os
cfg = json.load(open("/sandbox/.openclaw/openclaw.json"))
agents = {agent["id"]: agent for agent in cfg["agents"]["list"]}
assert "nvidia-omni" in cfg["models"]["providers"]
assert cfg["models"]["providers"]["nvidia-omni"]["apiKey"].startswith("nvapi-")
assert agents["vision-operator"]["workspace"] == "/sandbox/.openclaw-data/workspace"
assert cfg["agents"]["defaults"]["timeoutSeconds"] >= 300
assert cfg["plugins"]["enabled"] is False
assert cfg["plugins"]["slots"]["memory"] == "none"
for path in [
    "/sandbox/.openclaw-data/workspace/AGENTS.md",
    "/sandbox/.openclaw-data/workspace/TOOLS.md",
    "/sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json",
    "/sandbox/.openclaw/agents/vision-operator/agent/auth-profiles.json",
    "/sandbox/.openclaw/plugin-runtime-deps",
]:
    assert os.path.exists(path), path
print("omni demo config ok")
PY'
```

`kubectl exec` may print `Defaulted container "agent"` on stderr. That is normal
Kubernetes noise for this pod and is not an error by itself.

`openclaw agents list` should normally return in seconds after the helper
finishes. If it prints `[plugins] ... staging bundled runtime deps` for browser,
Bedrock, Anthropic, ElevenLabs, Deepgram, document extraction, GitHub Copilot,
Microsoft, QQBot, or another unrelated extension, stop it and re-run the current
helper; those plugins are not needed for this demo and should be disabled by the
patched config.

## Step 5: Ensure the OpenClaw gateway is reachable

Check gateway health from inside the sandbox:

```bash
openshell sandbox exec -n "$SANDBOX" -- python3 - <<'PY'
import socket
with socket.create_connection(("127.0.0.1", 18789), timeout=5):
    print("Connectivity probe: ok")
PY
```

If the output says `Connectivity probe: ok`, continue.

This direct probe avoids loading the OpenClaw plugin registry during readiness
checks. `openclaw gateway status` can stage bundled runtime dependencies for
unrelated providers on a fresh sandbox, which makes a healthy gateway look stuck.

### DGX Spark / restricted netns recovery

On DGX Spark or other restricted network namespaces, a stale OpenClaw gateway can
exit with messages like:

```text
gateway closed (1006)
uv_interface_addresses returned Unknown system error
```

Run the recovery helper after `apply-omni-subagent.sh`:

```bash
bash scripts/fix-spark-gateway.sh
```

It uses the NemoClaw proxy/guard environment, starts a foreground-style sandbox
gateway in the background, and waits with the same direct TCP probe above. Logs
are in `/tmp/gateway-manual.log` inside the sandbox; the PID is in
`/tmp/gateway-manual.pid`.

## Step 6: Upload a test image

Use any JPG/PNG. This creates a tiny red test image without requiring external
URLs:

```bash
python3 - <<'PY'
import base64
from pathlib import Path
# 1x1 red PNG
png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z8BQDwAFgwJ/lk3Q3wAAAABJRU5ErkJggg=="
Path("red.png").write_bytes(base64.b64decode(png))
PY

openshell sandbox upload "$SANDBOX" red.png /sandbox/.openclaw-data/workspace/
```

If `openshell sandbox upload` does not place the file where expected, copy it
through the gateway pod directly:

```bash
docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- \
  tee /sandbox/.openclaw-data/workspace/red.png < red.png > /dev/null
```

## Step 7: Verify direct Omni vision

Run the vision operator directly:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc 'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; export OPENCLAW_TEST_ONLY_PROVIDER_PLUGIN_IDS=nvidia; openclaw agent --json --agent vision-operator --thinking off --message "Use the image tool to inspect /sandbox/.openclaw-data/workspace/red.png, retry the image tool once if it returns Request was aborted or Image failed, then describe it in one sentence. /no_think" --session-id direct-vision-test --timeout 300'
```

Expected: the JSON response should contain `status: ok` and text describing a
solid red image. If it falls back to the text-only Super model or says it cannot
see the image, re-check the `nvidia-omni` auth profile and model ID.

On a cold sandbox, the first image-tool call can hit OpenClaw's internal image
request timeout and print `Image failed` or `Request was aborted`. Retry the same
command once; the immediate retry should use the warmed Omni endpoint and return
the red-image description.

## Step 8: Verify main-agent delegation

Ask `main` to delegate to `vision-operator` and write a result file:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc 'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; export OPENCLAW_TEST_ONLY_PROVIDER_PLUGIN_IDS=nvidia; openclaw agent --agent main --thinking off --message "Use agents_list to confirm vision-operator is available, then delegate to vision-operator with sessions_spawn. In the sub-agent message, tell it: Use the image tool to inspect /sandbox/.openclaw-data/workspace/red.png, retry the image tool once if it returns Request was aborted or Image failed, return exactly one sentence describing it, use --thinking off behavior if available, and include /no_think. Write the final one-sentence description to /sandbox/.openclaw-data/workspace/image-description.md and tell me what you wrote." --session-id main-vision-delegation-test --timeout 420'
```

Confirm the file was written. Sub-agent completion is push-based, so the CLI can
return a short `completed` marker before the final write is visible; wait until
the file appears:

```bash
for _ in $(seq 1 180); do
  if openshell sandbox exec -n "$SANDBOX" -- test -s /sandbox/.openclaw-data/workspace/image-description.md; then
    openshell sandbox exec -n "$SANDBOX" -- cat /sandbox/.openclaw-data/workspace/image-description.md
    break
  fi
  sleep 1
done
```

If the first run reports a pending device scope upgrade, approve the local CLI
request and retry:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc 'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; openclaw devices list --json'

openshell sandbox exec -n "$SANDBOX" -- bash -lc 'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; openclaw devices approve <requestId> --json'
```

## Step 9: Run the smoke test

After the helper has run once, you can repeat the full validation flow without
keeping the NVIDIA API key in the host shell:

```bash
SANDBOX=hclaw bash scripts/verify.sh
```

The smoke test checks config, policy, raw `nvidia-omni` provider auth,
`openclaw agents list`, gateway connectivity, direct `vision-operator` image
analysis with one retry for the cold image-tool path, main-agent delegation to
`image-description.md`, and a missing-image negative test that must not create a
phantom output file.

## Troubleshooting

### Docker works, but NemoClaw reports a Colima socket

If `docker info` succeeds but `nemoclaw debug --quick` points at
`~/.colima/default/docker.sock`, export the active Docker Desktop socket before
running `nemoclaw onboard`:

```bash
export DOCKER_HOST=unix://"$HOME"/.docker/run/docker.sock
```

### Onboarding fails while patching OpenClaw during the Docker build

If the build fails around `writeConfigFile(params.nextConfig)`, your NemoClaw
CLI is too old for the current OpenClaw base image. Update NemoClaw, confirm
`nemoclaw --version` is at least the tested version above, and onboard a fresh
sandbox.

### `EACCES` creating vision-operator sessions or workspace

Use the current helper. It creates and `chown`s the shared workspace plus both
observed vision-operator agent/session directories before writing config files.
For a sandbox patched with an older helper, recover with:

```bash
docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- bash -lc '
mkdir -p \
  /sandbox/.openclaw-data/workspace \
  /sandbox/.openclaw-data/agents/vision-operator/agent \
  /sandbox/.openclaw-data/agents/vision-operator/sessions \
  /sandbox/.openclaw/agents/vision-operator/agent \
  /sandbox/.openclaw/agents/vision-operator/sessions &&
chown -R sandbox:sandbox \
  /sandbox/.openclaw-data/workspace \
  /sandbox/.openclaw-data/agents/vision-operator \
  /sandbox/.openclaw/agents/vision-operator'
```

### Config invalid: `Unrecognized key: "systemPrompt"`

OpenClaw `2026.4.24` does not accept `agents.list[].systemPrompt`. Keep core
demo instructions in workspace files instead; the helper copies `AGENTS.md` and
`TOOLS.md` into `/sandbox/.openclaw-data/workspace/`.

### `401` / `403 status code` from `nvidia-omni`

Usually one of:

- `NVIDIA_API_KEY` does not have access to the Omni model
- the key has expired or was revoked after the sandbox was patched
- the in-sandbox provider `apiKey` is still the placeholder from the reference
  config instead of the exported `NVIDIA_API_KEY`
- auth profile uses the old `providers`/`apiKey` shape instead of the current
  `version` + `profiles` + `key` shape
- provider/model names do not line up (`nvidia-omni/<model-id>` in the agent,
  provider key `nvidia-omni` in `models.providers`)
- auth profile was written only to the legacy data path while this OpenClaw
  build uses `/sandbox/.openclaw/agents/vision-operator/agent`

Re-run:

```bash
NVIDIA_API_KEY=nvapi-... bash scripts/apply-omni-subagent.sh
```

Then check both auth-profile paths exist:

```bash
docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- bash -lc '
python3 - <<PY
import json
cfg = json.load(open("/sandbox/.openclaw/openclaw.json"))
assert cfg["models"]["providers"]["nvidia-omni"]["apiKey"].startswith("nvapi-")
print("provider apiKey present")
PY
test -s /sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json
test -s /sandbox/.openclaw/agents/vision-operator/agent/auth-profiles.json'
```

If the smoke test stops at `nvidia-omni provider probe failed` with
`Authorization failed`, the gateway and agent configuration may still be correct;
rotate to a key with Omni access and re-run `apply-omni-subagent.sh`.

### `LLM request timed out.` / `Connection error.`

Verify the `nvidia` policy block includes `/usr/local/bin/node`:

```bash
openshell policy get "$SANDBOX" --full | sed -n '/^  nvidia:/,/^  [a-z]/p'
```

Re-run the helper if `node` is missing.

For Omni image prompts, use `--thinking off`, include `/no_think`, and explicitly
tell the sub-agent to use the `image` tool. The reasoning checkpoint can
otherwise spend the request budget in `reasoning_content` and leave the CLI with
no final answer.

On a freshly-created sandbox, the first `image` tool call may also fail with
`Image failed` / `Request was aborted` while the Omni endpoint is cold. Retry the
same direct vision command once before debugging deeper. If the retry still
fails, confirm the provider path independently:

```bash
docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- bash -lc '
node -e "const fs=require(\"fs\");
const cfg=JSON.parse(fs.readFileSync(\"/sandbox/.openclaw/openclaw.json\",\"utf8\"));
const key=cfg.models.providers[\"nvidia-omni\"].apiKey;
console.log(\"provider apiKey present=\" + String((key || \"\").startsWith(\"nvapi-\")))"'
```

If the CLI keeps printing `Waiting for agent reply...` and then times out, check
the gateway log for the real provider error:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc \
  'tail -n 160 /tmp/openclaw-*/openclaw-*.log | grep -E "401 status|nvidia-omni|FailoverError|stuck session" || true'
```

### `gateway closed (1006)` or `uv_interface_addresses`

Run:

```bash
bash scripts/fix-spark-gateway.sh
```

Then approve any pending local CLI device scope upgrade and retry the command.

### The agent asks "Who am I?" instead of analyzing the image

The default OpenClaw workspace still has `BOOTSTRAP.md`. Either finish the
first-run identity flow in the TUI, or run:

```bash
SEED_DEMO_IDENTITY=1 bash scripts/apply-omni-subagent.sh
```

### Agent reads wrong path / EISDIR error

Use `/sandbox/.openclaw-data/workspace/`, not `/sandbox/.openclaw/workspace`.
`TOOLS.md` repeats this for both agents.

### OpenClaw CLI stalls while staging plugin runtime deps

Older versions of this helper did not prepare
`/sandbox/.openclaw/plugin-runtime-deps` or disable unrelated bundled plugins.
On a fresh sandbox, OpenClaw CLI checks such as `openclaw agents list` or
`openclaw gateway status` could then spend several minutes trying to install
browser, speech/media, chat, or unused model-provider dependencies before
returning.

Re-run the current helper:

```bash
SEED_DEMO_IDENTITY=1 bash scripts/apply-omni-subagent.sh
```

Then retry:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc \
  'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; \
   export OPENCLAW_TEST_ONLY_PROVIDER_PLUGIN_IDS=nvidia; \
   openclaw agents list'
```

For gateway readiness, use the direct TCP probe in Step 5 instead of
`openclaw gateway status`.

## Starting over

```bash
nemoclaw "$SANDBOX" destroy --yes
NEMOCLAW_SANDBOX_NAME="$SANDBOX" nemoclaw onboard
# Repeat steps 3-8
```
