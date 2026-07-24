# DGX Station ARM64 Setup Guide

This guide installs a local NemoClaw Hermes agent that controls a visible
Blender session, renders with OVRTX, and runs native OVPhysX simulations. It was
validated on an NVIDIA DGX Station running Ubuntu 24.04 ARM64 with one GB300 and
one RTX PRO 6000 Blackwell GPU.

## Process Summary

1. Clone NemoClaw Community and the NVIDIA OVRTX/OVPhysX Blender example.
2. Install Blender, the OV add-on, and its native runtime bundle.
3. Start Nemotron 3 Ultra locally with vLLM on the GB300.
4. Install NemoClaw, OpenShell, and the Hermes agent sandbox.
5. Install the specialized OV skills and permit Blender MCP access.
6. Start one visible Blender session from the NoMachine desktop.
7. Ask Hermes to render a scene or run the native OVPhysX stair-drop demo.

Commands run on the DGX Station unless a quoted **Human step** says otherwise.
Keep the environment variables from the first section in the same shell.

## Prerequisites

### Hardware and system

- NVIDIA DGX Station with Ubuntu 24.04 ARM64 (`aarch64`).
- One GB300 for Nemotron 3 Ultra and one RTX-capable GPU for OVRTX. The
  validated system uses an RTX PRO 6000 Blackwell as GPU 0 and GB300 as GPU 1.
- At least 600 GiB free for the model cache, build workspace, runtime artifacts,
  and outputs. A Blender source build can use another 100 GiB temporarily.
- An OS account with `sudo` access and permission to use Docker.
- A NoMachine client on the operator workstation and network access to the DGX
  Station desktop.

### Accounts and credentials

- Public internet access to the official Omniverse Labs repository and its
  release assets. GitHub authentication is not required.
- A Hugging Face read token with access to
  `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4`.
- Internet access to GitHub, Hugging Face, NVIDIA, Ubuntu package repositories,
  Blender, and the NoMachine download service.

No hosted LLM API key is required. Hermes uses the local vLLM endpoint.

## 0. Run the Read-Only Preflight

Run the preflight before installing or removing anything. It inventories the
guide's hardware, storage, packages, Docker runtime, credentials, network
names, ports, existing services, desktop software, and working directories.
It does not install packages, stop services, delete files, or print credential
values.

```bash
mkdir -p "$HOME/work"
git clone https://github.com/NVIDIA/nemoclaw-community.git \
  "$HOME/work/nemoclaw-community"
export COMMUNITY_REPO="$HOME/work/nemoclaw-community"
export GUIDE_REPO="$COMMUNITY_REPO/examples/demos/field/blender-omniverse-dgx-station"
cd "$GUIDE_REPO"
./scripts/preflight_dgx_station_arm64.sh
```

A fresh host normally reports `RESULT=not-ready` because Blender, NoMachine,
and other guide-installed components are still absent. Treat every `FAIL` as a
checklist item to resolve in the numbered section that owns it. Rerun the
preflight after host preparation and before starting the model download. Use
`--storage-path PATH` when the model cache and demo workspace intentionally use
a filesystem other than `$HOME`.

On a post-install rerun, a healthy `nemotron-ultra` endpoint or a complete
reusable target-model cache satisfies the initial storage and Hugging Face token
prerequisites. Active demo ports, the model container, and the sandbox remain
warnings so operators confirm they belong to this setup rather than deleting
working state.

## 1. Install Host Packages

### Command

```bash
sudo apt-get update
sudo apt-get install -y \
  ca-certificates curl git git-lfs jq unzip zip xz-utils file \
  python3 python3-pip python3-venv ffmpeg \
  nvidia-container-toolkit

if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get install -y docker.io
fi

sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
git lfs install
```

Log out and back in if the `docker` group was newly added.

### Validation

```bash
uname -m | grep -Eq '^(aarch64|arm64)$'
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader
id -nG | tr ' ' '\n' | grep -x docker
docker info >/dev/null && echo docker-ok
ffmpeg -version | head -1
```

## 2. Define Paths and Clone Repositories

### Command

```bash
mkdir -p "$HOME/work"
cd "$HOME/work"

export COMMUNITY_REPO="${COMMUNITY_REPO:-$HOME/work/nemoclaw-community}"
export GUIDE_REPO="$COMMUNITY_REPO/examples/demos/field/blender-omniverse-dgx-station"
export DEMO_ROOT="$HOME/work/ov-blender-hermes-demo"
export OV_MONOREPO="$DEMO_ROOT/omniverse-labs"
export OV_REPO="$OV_MONOREPO/projects/ov-blender-example"
export OV_ARTIFACT_DIR="$DEMO_ROOT/ov-artifacts"
export OV_GITHUB_REPO="NVIDIA-Omniverse/omniverse-labs"
export OV_PLATFORM="linux-aarch64"
export OV_RELEASE_TAG="ov-blender-example-$OV_PLATFORM"
export OV_RELEASE_URL="https://github.com/$OV_GITHUB_REPO/releases/tag/$OV_RELEASE_TAG"
export NEMOCLAW_SANDBOX_NAME="ov-blender-hermes"
export NEMOCLAW_GATEWAY_PORT="18081"

mkdir -p "$DEMO_ROOT" "$OV_ARTIFACT_DIR" "$DEMO_ROOT/out" "$DEMO_ROOT/scenes"
```

```bash
git clone --filter=blob:none --sparse \
  https://github.com/NVIDIA-Omniverse/omniverse-labs.git "$OV_MONOREPO"
git -C "$OV_MONOREPO" sparse-checkout set projects/ov-blender-example
git -C "$OV_MONOREPO" checkout main
git -C "$OV_MONOREPO" pull --ff-only origin main
```

### Validation

```bash
test -f "$GUIDE_REPO/README.md"
test -f "$OV_REPO/addon/ovrtx_blender_example/__init__.py"
test -f "$OV_REPO/skills/manifest.json"
git -C "$OV_MONOREPO" rev-parse HEAD
```

## 3. Install Blender 5.1

The OV add-on requires Blender 5.1.x. Blender does not publish an official
Linux ARM64 binary. The recommended DGX Station path installs the native
AArch64 Blender 5.1.0 build validated by this guide.

### Command

```bash
cd "$GUIDE_REPO"
./scripts/install_blender_5_1.sh
```

> **Third-party binary:** this build is published by the lfdevs community
> project rather than blender.org. It is the recommended path here because it
> is the version validated end to end on DGX Station ARM64. See Troubleshooting
> for the optional Blender 5.1.2 source-build path.

### Validation

```bash
blender --version | head -3
file "$(readlink -f "$(command -v blender)")" | grep -E 'ARM aarch64|ARM64'
"$GUIDE_REPO/scripts/verify_dgx_blender.sh" "$(command -v blender)"
```

## 4. Install NoMachine and Download the Demo Scene

### Command

```bash
curl -fL \
  https://download.nomachine.com/download/9.7/Arm/nomachine_9.7.3_1_arm64.deb \
  -o "$HOME/Downloads/nomachine_9.7.3_1_arm64.deb"
sudo apt-get install -y "$HOME/Downloads/nomachine_9.7.3_1_arm64.deb"
sudo /usr/NX/bin/nxserver --restart

curl -fL \
  https://download.blender.org/demo-files/archives/art-gallery/blender-splash-screens/blender-2-81/thejunkshopsplashscreen-35a35553b3dd4f8c8fb5a6ccc5065ff1.blend \
  -o "$DEMO_ROOT/scenes/thejunkshopsplashscreen.blend"
```

### Validation

```bash
sudo /usr/NX/bin/nxserver --status
/usr/NX/bin/nxserver --version
test -s "$DEMO_ROOT/scenes/thejunkshopsplashscreen.blend"
```

Do not start Blender yet. There is one visible Blender launch in section 10.

## 5. Download and Install the OV Add-on Runtime

### Command

The add-on and runtime must come from the same explicit public Release page.
Do not substitute a discovered “latest” release or mix assets from another
platform.

```bash
python3 "$GUIDE_REPO/scripts/download_ov_release.py" \
  --release-url "$OV_RELEASE_URL" \
  --platform "$OV_PLATFORM" \
  --output-dir "$OV_ARTIFACT_DIR"

export OV_ADDON_ZIP="$OV_ARTIFACT_DIR/ov-blender-example-${OV_PLATFORM}.zip"

blender --factory-startup --background \
  --command extension install-file -r user_default --enable "$OV_ADDON_ZIP"
```

Materialize the release runtime beside the installed extension:

```bash
export OV_EXTENSION_ROOT="$HOME/.config/blender/5.1/extensions/.user/user_default/ovrtx_blender_example"
export OV_RUNTIME_ROOT="$OV_EXTENSION_ROOT/runtimes/$OV_PLATFORM/current"

python3 "$GUIDE_REPO/scripts/materialize_runtime_from_artifacts.py" \
  --addon-zip "$OV_ADDON_ZIP" \
  --artifact-dir "$OV_ARTIFACT_DIR" \
  --storage-root "$OV_EXTENSION_ROOT"
```

The helper imports the runtime installer from the selected add-on ZIP and gives
it the complete paired artifact directory. This is the non-interactive form of
the add-on's documented **Install Runtime From** local-directory workflow.

Install this project's additive host helper:

```bash
export OV_NATIVE_DIR="$OV_RUNTIME_ROOT/native"
cd "$GUIDE_REPO"
./scripts/install_ovphysx_helpers.sh
```

### Validation

```bash
test -f "$HOME/.config/blender/5.1/extensions/user_default/ovrtx_blender_example/blender_manifest.toml"
grep -E '^version|^platforms' \
  "$HOME/.config/blender/5.1/extensions/user_default/ovrtx_blender_example/blender_manifest.toml"
test -x "$OV_RUNTIME_ROOT/bin/ovrtx-bridge-server"
test -x "$OV_RUNTIME_ROOT/bin/ovphysx-bridge-server"
file "$OV_NATIVE_DIR/grpc/_cython"/cygrpc*.so | grep -E 'ARM aarch64|ARM64'
file "$OV_NATIVE_DIR/google/_upb"/_message*.so | grep -E 'ARM aarch64|ARM64'
test -x "$HOME/.local/share/nemoclaw-blender/ovphysx_host_helper.py"
cat "$HOME/.config/nemoclaw-blender/ovphysx-helper.json" | jq .
```

## 6. Start Nemotron 3 Ultra with vLLM

Initial startup can download roughly 328 GiB and then load, compile, and warm
the model. Allow at least 20 minutes for a cold start. The launcher follows the
[NVIDIA Nemotron 3 Ultra DGX Station deployment](https://docs.nvidia.com/nemotron/nightly/deployment-guides.html)
pattern with CPU expert offload and an NVFP4 inference backend.

> **Human step: provide Hugging Face access.** Export your read token in the
> host shell. Do not commit it or add it to this repository.

### Command

```bash
export HF_TOKEN='hf_...'
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader

# Validated topology: RTX PRO is GPU 0 and GB300 is GPU 1.
export VLLM_GPU_DEVICE=1
export VLLM_IMAGE='vllm/vllm-openai:v0.22.0'

docker pull "$VLLM_IMAGE"
"$GUIDE_REPO/scripts/start_nemotron_ultra_vllm_station.sh"
docker logs -f nemotron-ultra-vllm
```

Stop following logs with `Ctrl-C`; that does not stop the container.

### Validation

```bash
curl -fsS http://127.0.0.1:8000/v1/models | jq \
  '.data[] | {id, root, max_model_len}'
export VLLM_MODEL_ID="$(
  curl -fsS http://127.0.0.1:8000/v1/models | jq -er '.data[0].id'
)"
curl -fsS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg model "$VLLM_MODEL_ID" \
    '{model:$model,messages:[{role:"user",content:"Return exactly INFERENCE_OK"}],max_tokens:64}')" | \
  jq -r '.choices[0].message.content'
docker ps --filter name=nemotron-ultra-vllm
```

The model ID must be read from `/v1/models`; deployments may expose the full
repository model ID instead of the launcher's short alias. The completion probe
must return `INFERENCE_OK`. A healthy `/v1/models` response alone is
insufficient because the model endpoint can be registered while its first
generation request still fails.

## 7. Install NemoClaw, OpenShell, and Hermes

The vLLM endpoint must be healthy before running the stock NemoClaw installer.
The installer performs Hermes onboarding on DGX Station.

### Command

```bash
export NEMOCLAW_AGENT=hermes
export NEMOCLAW_SANDBOX_NAME="ov-blender-hermes"
export NEMOCLAW_GATEWAY_PORT="18081"
export NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR="$HOME/.local/state/nemoclaw/openshell-docker-gateway-$NEMOCLAW_GATEWAY_PORT"
export NEMOCLAW_PROVIDER=vllm
export NEMOCLAW_VLLM_LOCAL_TOKEN=none_needed
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
unset NEMOCLAW_VLLM_MODEL

curl -fsSL https://www.nvidia.com/nemoclaw.sh | \
  NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash

NODE_BIN="$(dirname "$(bash -lc 'command -v node')")"
export PATH="$HOME/.local/bin:$NODE_BIN:$PATH"
```

Use a login shell or explicitly export the same `PATH`,
`NEMOCLAW_GATEWAY_PORT`, and `NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR` for every
later non-interactive SSH command. Otherwise SSH can resolve a different system
OpenShell CLI or the status preflight can inspect a stale default-gateway
runtime marker. Do not add a systemd override during normal setup.

### Validation

```bash
bash -lc 'command -v nemohermes; nemohermes --version'
bash -lc 'command -v openshell; openshell --version'
bash -lc 'nemohermes ov-blender-hermes status'
curl -fsS http://127.0.0.1:8000/v1/models >/dev/null
nemohermes ov-blender-hermes exec --timeout 300 -- \
  hermes chat -Q --max-turns 2 -q \
  'Return exactly INFERENCE_OK and do not call any tool.'
```

The sandbox status must report `Hermes Agent: running`.

## 8. Install Agent Context, Specialized Skills, and Network Policy

### Command

```bash
export PATH="$HOME/.local/bin:$PATH"
cd "$GUIDE_REPO"
./scripts/install_hermes_context.sh "$NEMOCLAW_SANDBOX_NAME"
./scripts/install_public_skills.sh "$NEMOCLAW_SANDBOX_NAME" "$OV_REPO"
./scripts/install_blender_api_reference.sh "$NEMOCLAW_SANDBOX_NAME"

export HOST_IP="$(hostname -I | awk '{print $1}')"
sed "s/HOST_IP_PLACEHOLDER/$HOST_IP/g" \
  "$GUIDE_REPO/policies/blender-mcp-host.yaml" \
  > "$DEMO_ROOT/blender-mcp-host.yaml"

nemohermes "$NEMOCLAW_SANDBOX_NAME" policy-add \
  --from-file "$DEMO_ROOT/blender-mcp-host.yaml" --yes
```

The installer fetches the official project's `skills` tree from upstream
`main` and installs every skill into Hermes. Set `OV_SKILLS_REF=current` only
when intentionally testing the checkout's current skill files without fetching
upstream.

Skill installation messages may suggest restarting the agent gateway. A new
Hermes chat session loads the skills; do not restart the OpenShell gateway.
The API reference command downloads about 92 MB once from Blender's official
documentation site, caches it on the host, and extracts it inside the sandbox.
The SOUL installer is idempotent and preserves NemoClaw's existing instructions.

### Validation

```bash
nemohermes "$NEMOCLAW_SANDBOX_NAME" status
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -f /sandbox/.hermes/skills/ovphysx-host-runtime-boundary/SKILL.md
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -f /sandbox/.hermes/skills/blender-python-api-verification/SKILL.md
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -f /sandbox/.hermes/skills/blender-python-api-verification/scripts/search_blender_api.py
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -f /sandbox/.hermes/skills/blender-host-sandbox-boundary/SKILL.md
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  grep -q nemoclaw-blender-host-boundary /sandbox/.hermes/SOUL.md
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -f /sandbox/reference/blender-python-api-5.1/index.html
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -f /sandbox/reference/blender-python-api-5.1/api-search.sqlite3
```

The API reference command downloads about 92 MB once from Blender's official
documentation site, caches it on the host, extracts it inside the sandbox, and
builds a compact SQLite full-text index. It does not give Hermes unrestricted
web access.

## 9. Prepare Blender MCP

### Command

```bash
mkdir -p "$DEMO_ROOT/blender-mcp" "$DEMO_ROOT/venvs"
curl -fL https://raw.githubusercontent.com/ahujasid/blender-mcp/main/addon.py \
  -o "$DEMO_ROOT/blender-mcp/blender_mcp_addon.py"

python3 -m venv "$DEMO_ROOT/venvs/host-tools"
. "$DEMO_ROOT/venvs/host-tools/bin/activate"
pip install --upgrade pip uv
export PATH="$DEMO_ROOT/venvs/host-tools/bin:$PATH"

nohup uvx mcp-proxy --host 0.0.0.0 --port 9877 uvx blender-mcp \
  > "$DEMO_ROOT/out/blender-mcp-proxy.log" 2>&1 </dev/null &
echo $! > "$DEMO_ROOT/out/blender-mcp-proxy.pid"
sleep 5
```

Start the bounded workflow MCP proxy and create two explicit Hermes profiles:
`blenderraw` for exploratory Blender/OVRTX/OVPhysX tasks and `blenderhandoff`
for scene inventory, USD export, USD inspection, and artifact receipts:

```bash
"$GUIDE_REPO/scripts/install_blender_workflow_mcp.sh" \
  "$NEMOCLAW_SANDBOX_NAME" "$HOST_IP"
```

The `blenderhandoff` profile clones the configured model credentials and
skills, disables terminal/file/code-execution tools and the mutable skills
toolset in that profile only, and enables a small typed Blender/Workflow MCP
set. Its wrapper preloads the read-only host/sandbox boundary skill for every
chat. This prevents `skill_manage` from becoming an unintended file-write
escape hatch. The profile does not register the raw Blender MCP because Hermes
can surface MCP resource and prompt helpers through deferred discovery even
when ordinary tools are allowlisted. It also disables the cloned API-server
surface and removes any other inherited MCP servers. The separate `blenderraw`
profile exposes raw Blender MCP without editing the integrity-protected base
Hermes configuration. The installer selects `blenderraw` as Hermes' sticky
default, so plain TUI commands and the machine dashboard automatically target
it; the `blenderraw` alias remains available for explicit selection. Do not run
`configure_hermes_blender_mcp.py` without a named profile or add the
unauthenticated HTTP endpoint to the base config.

> **Security:** The two `mcp-proxy` listeners do not provide application-layer
> authentication. Keep ports 9877 and 9878 restricted to the trusted DGX host
> network and the exact sandbox policy in this repository. Do not expose them
> through public ingress, and stop the proxies when the demo is no longer in
> use.

### Validation

```bash
kill -0 "$(cat "$DEMO_ROOT/out/blender-mcp-proxy.pid")"
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 5 \
  http://127.0.0.1:9877/mcp
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 5 \
  http://127.0.0.1:9878/mcp
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- hermes mcp list
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  hermes mcp test blender
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  /sandbox/.local/bin/blenderhandoff mcp test blender-workflow
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  /sandbox/.local/bin/blenderhandoff tools list
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -f /sandbox/.hermes/profiles/blenderhandoff/skills/blender-host-sandbox-boundary/SKILL.md
```

An unauthenticated `GET /mcp` normally returns HTTP `406`, which confirms each
proxy is listening. Plain `hermes mcp list` must resolve the sticky
`blenderraw` profile and discover the raw Blender tools. The integrity-protected
base profile remains unchanged, and the isolated `blenderhandoff` profile must
list only the five `blender-workflow` tools.

## 10. Start the Visible Blender Session

> **Human step: launch Blender from the NoMachine desktop.** Connect with the
> NoMachine client, select the GDM or local physical desktop, log in as the OS
> user, and open a terminal inside that desktop. Run the command below there.
> Keep this single Blender window open while using Hermes. The launch helper
> selects the `OVRTX Example` render engine automatically; no Preferences or
> Render Properties clicks are required. If the connection is black with only
> an X-shaped cursor, use
> [NoMachine connects but the Linux desktop is black](#nomachine-connects-but-the-linux-desktop-is-black)
> before launching Blender.

### Command

```bash
export GUIDE_REPO="$HOME/work/nemoclaw-community/examples/demos/field/blender-omniverse-dgx-station"
export DEMO_ROOT="$HOME/work/ov-blender-hermes-demo"
rm -rf /tmp/ov-blender-example

env \
  BLENDER_MCP_ADDON="$DEMO_ROOT/blender-mcp/blender_mcp_addon.py" \
  BLENDER_MCP_HOST=127.0.0.1 \
  BLENDER_MCP_PORT=9876 \
  CUDA_VISIBLE_DEVICES=0 \
  OVRTX_ACTIVE_CUDA_GPUS=0 \
  blender "$DEMO_ROOT/scenes/thejunkshopsplashscreen.blend" \
  --python "$GUIDE_REPO/scripts/start_visible_blender_mcp.py" \
  > "$DEMO_ROOT/out/visible-blender-mcp.log" 2>&1 </dev/null &
```

### Validation

Run these from any host shell:

```bash
grep -q BLENDER_MCP_READY "$DEMO_ROOT/out/visible-blender-mcp.log"
python3 "$GUIDE_REPO/scripts/verify_visible_blender_ovrtx.py" --wait 120
python3 "$GUIDE_REPO/scripts/render_visible_blender_ovrtx_smoke.py" \
  --output "$DEMO_ROOT/out/ovrtx-render-smoke.png" --timeout 900
file "$DEMO_ROOT/out/ovrtx-render-smoke.png"
```

Expected results are `Runtime is installed`, OVRTX and OVPhysX `SERVING`,
preflight `pass`, and a non-empty PNG.

## 11. Run the Demo

### Command

First verify the bounded host/sandbox route without changing the scene:

```bash
export HANDOFF_SMOKE="$DEMO_ROOT/out/handoff-smoke"
export HANDOFF_PROMPT="Use only typed blender-workflow MCP tools. Probe capabilities. Inventory the active scene to $HANDOFF_SMOKE/scene-inventory.json, verify that exact file with artifact_receipts, and return HANDOFF_SMOKE_PASS only if it is present and non-empty with a SHA-256 receipt."
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 600 -- \
  /sandbox/.local/bin/blenderhandoff chat -Q --max-turns 12 \
  -q "$HANDOFF_PROMPT"
```

Start with a simple direct-Hermes rendering test:

```bash
export PATH="$HOME/.local/bin:$PATH"
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 1200 -- \
  hermes chat -Q --max-turns 30 -q \
  "Render the current scene as a beauty shot with OVRTX. Preserve the scene, save the PNG to $DEMO_ROOT/out/hermes-beauty-shot.png, and report the host path."
```

Then test native physics:

```bash
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 1200 -- \
  hermes chat -Q --max-turns 30 -q \
  "Run the configured native OVPhysX stair-drop demo. Create a GIF of the blocks falling down the stairs and report the native simulation status and host GIF path."
```

These prompts intentionally describe outcomes rather than implementation. The
installed skills provide the Blender, OVRTX, and OVPhysX procedure. For more
direct-Hermes examples, see
[`prompts/demo-prompts.md`](../prompts/demo-prompts.md).

The Hermes machine dashboard aligns its profile switcher with the sticky
`blenderraw` profile on load, so its Chat and MCP pages use the same raw Blender
configuration as plain TUI commands. Confirm `blenderraw` appears in the
dashboard profile switcher before running a demo prompt.

### Validation

```bash
file "$DEMO_ROOT/out/hermes-beauty-shot.png"
jq '{scene_path, object_count, material_count, rigid_body_count}' \
  "$DEMO_ROOT/out/handoff-smoke/scene-inventory.json"
sha256sum "$DEMO_ROOT/out/handoff-smoke/scene-inventory.json"
jq . "$DEMO_ROOT/out/stair-drop/status.json"
jq . "$DEMO_ROOT/out/stair-drop/replay-status.json"
file "$DEMO_ROOT/out/stair-drop/starting-scene.png"
file "$DEMO_ROOT/out/stair-drop/ovphysx-replay.gif"
pgrep -af '^blender '
```

Required evidence:

- The bounded smoke returns `HANDOFF_SMOKE_PASS`; its inventory exists and has
  a host-measured SHA-256.
- `native_status` is `pass-real`.
- `physics_source` is `native-ovphysx-readback`.
- `render_class` is `blender-replay`.
- The GIF exists and Blender remains running.

## 12. Optional: Add Codex as an Entry Point

The NemoClaw-first installation is complete. To use Codex as a general
intelligence layer that delegates Blender and Omniverse work to this Hermes
agent, continue with the supplementary
[Codex entry-point setup](setup-codex-entrypoint.md).

## Troubleshooting

### Optional Blender 5.1.2 source build

Building Blender 5.1.2 from source is not the recommended demo setup. The
upstream dependency superbuild compiles LLVM and USD with limited parallelism,
can take several hours, and currently requires ARM64-specific build and harvest
fixes. Use this only when validating Blender itself:

```bash
"$GUIDE_REPO/scripts/build_blender_5_1_2_arm64.sh"
```

The source-build helper remains experimental and is not part of the validated
zero-to-demo path.

### GitHub clone or release download returns 404

The official repository and releases are public. A `404` usually means the
project path, platform tag, or paired asset name was changed. Confirm the exact
documented locations and rerun the public-access preflight without adding a
GitHub credential:

```bash
git ls-remote --exit-code \
  https://github.com/NVIDIA-Omniverse/omniverse-labs.git refs/heads/main
curl -fsSL -o /dev/null "$OV_RELEASE_URL"
python3 "$GUIDE_REPO/scripts/download_ov_release.py" \
  --release-url "$OV_RELEASE_URL" \
  --platform "$OV_PLATFORM" \
  --output-dir "$OV_ARTIFACT_DIR"
```

See the official
[ov-blender-example project](https://github.com/NVIDIA-Omniverse/omniverse-labs/tree/main/projects/ov-blender-example)
and [Release page](https://github.com/NVIDIA-Omniverse/omniverse-labs/releases)
before changing the tag or asset names.

### Docker access fails

Check the login session's groups. A shell created before `usermod` will not see
the new membership:

```bash
id -nG
docker info
```

Log out of both SSH and the desktop, then log back in. For a short-lived
diagnostic only, `sudo setfacl -m u:"$USER":rw /var/run/docker.sock` can prove
that socket access is the blocker.

### NoMachine connects but the Linux desktop is black

A black window with an X-shaped cursor means the NX transport is connected but
the Linux desktop image is not rendering. NoMachine tracks this as an open v9
physical-desktop issue on Linux. First use the page peel in the upper-right
corner of the client window, then select **Display**, **Change settings**,
**Modify**, and **Disable client-side hardware decoding**. Disconnect and
reconnect. See NoMachine's
[client decoding instructions](https://kb.nomachine.com/AR07U01202) and
[Linux physical-desktop issue](https://kb.nomachine.com/TR03X11742).

If the screen remains black, confirm that the physical display contains only
the GDM greeter before stopping it. Do not stop GDM when another user has a
graphical session or unsaved desktop work:

```bash
who
loginctl list-sessions --no-legend
systemctl status gdm.service --no-pager
```

Disconnect NoMachine, stop the unused greeter, and verify it is inactive:

```bash
sudo systemctl stop gdm
systemctl is-active gdm
```

Reconnect. If NoMachine reports that the local display is unavailable, check
whether virtual display creation is disabled and whether `nxnode` is disabled:

```bash
/usr/NX/bin/nxserver --status
grep -n -E 'CreateDisplay|DisplayOwner' /usr/NX/etc/server.cfg
```

Back up the server configuration, enable a virtual display owned by the setup
user, and restart NoMachine. Replace `nvidia` when the OS username differs:

```bash
if [ ! -e /usr/NX/etc/server.cfg.before-virtual-display ]; then
  sudo cp /usr/NX/etc/server.cfg \
    /usr/NX/etc/server.cfg.before-virtual-display
fi

sudo sed -i \
  -e 's/^#CreateDisplay 0/CreateDisplay 1/' \
  -e 's/^#DisplayOwner ""/DisplayOwner "nvidia"/' \
  /usr/NX/etc/server.cfg

grep -E '^(CreateDisplay|DisplayOwner)' /usr/NX/etc/server.cfg
sudo /usr/NX/bin/nxserver --restart
```

Expected configuration is `CreateDisplay 1` and `DisplayOwner "nvidia"`.
Reconnect and let NoMachine create the virtual GNOME display. This follows
NoMachine's [headless Linux guidance](https://kb.nomachine.com/AR03P00973).

Open the terminal from inside the NoMachine desktop and confirm it inherited a
display before launching Blender:

```bash
test -n "$DISPLAY" && echo "display=$DISPLAY"
```

Do not launch visible Blender from a separate SSH shell. If the log reports
`unable to connect to display`, rerun the command in the NoMachine terminal.
As a diagnostic only, identify the active virtual display with
`ls /tmp/.X11-unix`; the display number is assigned dynamically and must not be
hard-coded in the guide.

To restore the original configuration and physical GDM display:

```bash
sudo cp /usr/NX/etc/server.cfg.before-virtual-display \
  /usr/NX/etc/server.cfg
sudo systemctl start gdm
sudo /usr/NX/bin/nxserver --restart
```

### OpenShell differs between login and non-login shells

Run the diagnostic below before modifying services:

```bash
echo "non-login: $(command -v openshell)"
openshell --version
bash -lc 'echo "login: $(command -v openshell)"; openshell --version'
systemctl --user is-system-running || true
docker info >/dev/null && echo docker-ok
```

For non-interactive SSH automation, export the selected gateway and rebuild a
login-equivalent command path explicitly:

```bash
export NEMOCLAW_GATEWAY_PORT=18081
export NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR="$HOME/.local/state/nemoclaw/openshell-docker-gateway-$NEMOCLAW_GATEWAY_PORT"
NODE_BIN="$(dirname "$(bash -lc 'command -v node')")"
export PATH="$HOME/.local/bin:$NODE_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
```

The clean installation validated by this guide uses OpenShell CLI and gateway
`0.0.72`. Use `bash -lc` or explicitly prepend `~/.local/bin` so SSH commands
resolve the NemoClaw-installed CLI. Do not replace or override the gateway when
the CLI and gateway already agree.

If onboarding stopped after installing the CLI, preserve the partial sandbox
and resume:

```bash
export PATH="$HOME/.local/bin:$PATH"
nemohermes onboard --resume --non-interactive \
  --yes --yes-i-accept-third-party-software
```

Only inspect or override `openshell-gateway.service` when logs prove that a
user service, rather than NemoClaw's standalone gateway, is active. The normal
guide does not require a systemd override.

### User systemd reports degraded

Identify the failed unit before associating it with OpenShell:

```bash
systemctl --user --failed --no-pager
systemctl --user status openshell-gateway.service --no-pager
```

On the validated host, `update-notifier-crash.service` caused the degraded
state and was unrelated to NemoClaw.

### vLLM does not become ready

```bash
docker ps -a --filter name=nemotron-ultra-vllm
docker logs --tail 300 nemotron-ultra-vllm
nvidia-smi
df -h "$HOME/.cache/huggingface"
```

Model loading and CUDA graph capture are long-running. Do not restart or remove
the container while weights are still loading.

Use the launcher in this repository with GB300 alone (`VLLM_GPU_DEVICE=1`,
tensor parallel size 1, CPU expert offload). Do not combine the RTX rendering
GPU and GB300 in a heterogeneous tensor-parallel vLLM container. In validation,
that competing topology consumed both GPUs and failed its first real request in
FlashInfer even though `/v1/models` was healthy. Stop or rename any competing
model container before starting `nemotron-ultra-vllm`.

### Blender exits with `Unable to initialize GHOST`

Launch the visible Blender command from a terminal opened inside the active
NoMachine desktop, not from a Mac SSH terminal. Verify that the desktop shell
has a non-empty display before launching:

```bash
echo "$DISPLAY"
loginctl list-sessions
```

The display number is session-specific (for example, `:1002` during one QA
run); do not hard-code it in the guide. An empty or stale SSH `DISPLAY` can
leave the NoMachine desktop visible while Blender exits immediately.

### A failed run prints an OpenRouter policy hint

The local profile uses `https://inference.local/v1`. Hermes may still attempt
an optional OpenRouter model-metadata lookup, and an interrupted or failed run
can print a generic egress-policy hint for that lookup. Before changing policy,
verify the configured provider/base URL and run the real `INFERENCE_OK`
completion probe above. Treat the OpenRouter hint as causal only when the
actual configured model route uses OpenRouter.

### Blender MCP reports 502 or disabled

```bash
pgrep -af '^blender '
ss -ltnp | grep -E ':(9876|9877|9878)'
tail -100 "$DEMO_ROOT/out/blender-mcp-proxy.log"
tail -100 "$DEMO_ROOT/out/blender-workflow-mcp.log"
tail -100 "$DEMO_ROOT/out/visible-blender-mcp.log"
```

Restart the detached proxy if port 9877 is absent. If either profile or the
bounded workflow server is missing, rerun the idempotent installer:

```bash
"$GUIDE_REPO/scripts/install_blender_workflow_mcp.sh" \
  "$NEMOCLAW_SANDBOX_NAME" "$HOST_IP"
```

Do not replace the typed tools with long inline Python inside
`execute_blender_code`. Use `blenderhandoff mcp test blender-workflow` and the
proxy log to diagnose the owning surface.

### Sandbox start loses demo-installed assets

After `nemohermes <sandbox> stop` followed by `start`, verify the guide-owned
state instead of relying only on the container phase:

```bash
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -f /sandbox/reference/blender-python-api-5.1/api-search.sqlite3
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -x /sandbox/.local/bin/blenderraw
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 30 -- \
  test -x /sandbox/.local/bin/blenderhandoff
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 60 -- \
  hermes mcp test blender
```

If any check fails, rerun section 8 in order and then rerun
`install_blender_workflow_mcp.sh`. The profile installers refresh each profile
with the current default skill set and reselect `blenderraw` as the sticky
default on every run. Do not restore raw MCP by editing
`/sandbox/.hermes/config.yaml`; current NemoClaw validates that file against its
persisted MCP intent and can quarantine the Hermes gateway on drift.

### OVRTX render reports an invalid USD export context

Current validated add-on source does not require a context patch. Only for the
specific error `bpy.ops.wm.usd_export.poll() failed, context is incorrect`,
apply the fallback to the installed add-on and restart Blender:

```bash
python3 "$GUIDE_REPO/scripts/patch_ovrtx_render_context.py" \
  --extension-package \
  "$HOME/.config/blender/5.1/extensions/user_default/ovrtx_blender_example/ovrtx_blender_example"
```

> **Temporary patch:** this fallback is for older add-on builds. Do not patch
> the upstream checkout, and remove this workaround when all supported releases
> carry the corrected export context.

### Repeated physics runs or renders fail

Use a new Hermes chat request so it loads the current specialized skill. The
project helper uses a dedicated fixture scene and restores its imported
transforms between runs. Do not manually delete all scene objects or re-import
the fixture between `preview` and `replay`.

For retained OVRTX state, restart the single visible Blender process and rerun
the scripted smoke render before starting another Hermes request.

## Validated Component Matrix

The following versions completed host setup, visible OVRTX scene rendering,
NemoClaw sandbox setup, skill installation, and Blender MCP registration on
July 18, 2026. The native OVPhysX workflow was also validated on this platform
in the preceding installation; repeat it after each clean install using the
prompt in the validation section above.

| Component | Validated version or identity |
| --- | --- |
| Platform | NVIDIA DGX Station, Ubuntu 24.04.4 LTS, ARM64 |
| Kernel | `6.17.0-1022-nvidia-64k` |
| RTX GPU | NVIDIA RTX PRO 6000 Blackwell Max-Q, 97,887 MiB, GPU 0 |
| LLM GPU | NVIDIA GB300, 256,703 MiB, GPU 1 |
| NVIDIA driver | `610.43.03` |
| Blender | `5.1.0`, native AArch64, embedded Python 3.13 |
| OV add-on | `ovrtx Blender Example 0.1.0` |
| OV source | commit `7d2bfcff616a824d6dec9ec5f0efeb3ffae108bc` from `main` |
| OV runtime platform | `linux-aarch64` |
| OV runtime manifest SHA-256 | `75868aecc5f54921f4f6a68523644f6084d2cdccc4d36d8f5fc6349414016d55` |
| vLLM | `vllm/vllm-openai:v0.22.0` |
| Model | `nvidia/nemotron-3-ultra-550b-a55b` as advertised by `/v1/models` |
| Model context | 262,144 tokens |
| NemoHermes | `0.0.83` |
| Hermes Agent | `0.18.0` (`2026.7.1`) |
| OpenShell CLI and gateway | `0.0.72` |
| Docker | `29.2.1` |
| NoMachine | `9.7.3` |
| FFmpeg | `6.1.1` |

The recommended path uses the native community Blender 5.1.0 binary. The
Blender 5.1.2 source-build helper is retained only for experimental Blender
build validation and is not part of the zero-to-demo path.
