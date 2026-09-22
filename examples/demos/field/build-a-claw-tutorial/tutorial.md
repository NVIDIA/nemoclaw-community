# OpenClaw and Hermes on NVIDIA DGX Spark with Qwen 3.6, Gemma 4, and Nemotron 3 Nano Omni

[TOC]

## Before you begin

> [!CAUTION]
> This guide contains executable host-administration and agent instructions.
> NemoClaw Community renders the guide but does not execute its commands or
> validate the complete workflow.

- **Target and evidence:** The intended target is NVIDIA DGX Spark running an
  Ubuntu-based DGX OS with a compatible CUDA toolchain. Repository verification
  covers catalog rendering, immutable release identities, an isolated OpenClaw
  package installation, and the pinned Hermes install and diagnostic sequence.
  It does not establish a supported DGX OS image or a live end-to-end result
  for the complete tutorial.
- **Host changes:** The commands install operating-system, Python, and global
  Node.js packages; compile CUDA software; create services; write under
  `~/.openclaw` and `~/.hermes`; and listen on ports `8000`, `8001`, and
  optionally `9222`. Run them on a dedicated or disposable host, not a shared
  workstation.
- **Downloads and services:** Model downloads are large and subject to their
  publishers' licenses. Optional steps contact GitHub, Hugging Face, npm,
  AgentMail, Telegram, LinkedIn, YouTube, and other public services. Those
  services can apply usage terms, collect connection data, or charge fees.
- **Secrets and permissions:** Never put API keys, bot tokens, or other secrets
  in this document, a prompt, or source control. Restrict configuration-file
  permissions. Browser, camera, email, Telegram, and agent execution steps can
  expose local data or perform external actions; enable only the capability you
  intend to demonstrate.
- **Backup and rollback:** Start from a snapshot or a fresh host. Back up any
  existing OpenClaw or Hermes configuration before continuing. Stop model
  servers and agent daemons after the session, revoke temporary credentials,
  and restore the snapshot when you need a complete rollback. The catalog does
  not provide an automated uninstall.
- **External media:** Images hosted outside this repository appear as outbound
  links. Embedded LinkedIn and YouTube media can contact those services when it
  enters the browser viewport.

# Part 1 — Serve a model

## Choose a serving backend

There are two tested ways to serve the models on the Spark.

**vLLM with NVFP4 checkpoints is our primary recommendation.**

**The llama.cpp + GGUF setup remains a fully tested and supported alternative**.

| | vLLM + NVFP4 (recommended) | llama.cpp + GGUF (tested alternative) |
| --- | --- | --- |
| Models tested here | Qwen 3.6, Gemma 4, Nemotron 3 Nano Omni | Qwen 3.6, Gemma 4, Nemotron 3 Nano Omni |

Both expose the same OpenAI-compatible API at `http://127.0.0.1:8000/v1`, so everything from Part 2 onward is identical either way.

The sections below list the configurations we have tested. Other model and backend combinations should work, but we have not verified them.

Set up and verify one model server before you install OpenClaw or Hermes.

Note that both backends default to port 8000, so only one of them can hold that port at a time.

## Serve with vLLM + NVFP4 (recommended)

This is the path we recommend for new setups. We have tested Qwen 3.6, Gemma 4, and Nemotron 3 Nano Omni here.

For more details on how to get going with speculative decoding, RTX PRO 6000 and Thor/Docker variants, and remote access over Tailscale, checkout this:
https://hackmd.io/ZvP9JnFETmuDuB0CQESukw

### Install uv and vLLM

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg

curl -LsSf https://astral.sh/uv/install.sh | sh
```

Create the environment.

```bash
uv venv unsloth-nvfp4-env --python 3.13

source unsloth-nvfp4-env/bin/activate
uv pip install "vllm==0.28.0" "flashinfer-python==0.6.16.post3" "nvidia-cutlass-dsl>=4.6.2" \
    --torch-backend=auto
```

If the install resolves to a broken combination, there are known-good `pip freeze` files here, including one for vLLM 0.28.0:
https://hackmd.io/fH95LfPuRi-gruvfn5FTrg

### Check the NVFP4 kernels before serving

Run this first. If it fails, vLLM will still start, but it silently falls back to marlin W4A16 and you lose the NVFP4 speedup without any obvious error.

```bash
python -c "
import torch; from vllm.utils.flashinfer import has_flashinfer_b12x_gemm as g, has_flashinfer_b12x_moe as m
cap = torch.cuda.get_device_capability(); print('cap', cap, '| b12x gemm', g(), '| b12x moe', m()); assert cap[0] == 12 and g() and m(), 'b12x unavailable: serving would degrade to marlin W4A16'"
```

### Download the models

Fetch the weights first, then serve. `vllm serve` will pull a missing model on its own, but doing it up front keeps a multi-gigabyte download out of your first launch.

```bash
source unsloth-nvfp4-env/bin/activate

hf download nvidia/Qwen3.6-35B-A3B-NVFP4
hf download unsloth/gemma-4-26B-A4B-it-NVFP4

# only needed if you want the vision subagent below
hf download nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4
```

These land in the shared Hugging Face cache, so the serve commands below resolve them by name with no extra path flags.

The serve commands below run in the foreground, so start them inside `screen` or `tmux` (for example `tmux new -s qwen`) and detach with `Ctrl-b d`. Closing the terminal or dropping an SSH session otherwise kills the server.

### Qwen 3.6 NVFP4

This is the tested Spark config. The first launch warms up for a few minutes.

```bash
#clear cache before we start! 
sudo sysctl -w vm.drop_caches=3

source unsloth-nvfp4-env/bin/activate

export CUTE_DSL_ARCH=sm_121a

# Required. Without this bound the first start exhausts host memory.
export MAX_JOBS=8

vllm serve nvidia/Qwen3.6-35B-A3B-NVFP4 --moe-backend flashinfer_b12x \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder \
    --reasoning-parser qwen3 \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1 \
    --trust-remote-code \
    --kv-cache-dtype fp8 \
    --attention-backend flashinfer \
    --gpu-memory-utilization 0.6 \
    --max-model-len 262144 \
    --max-num-seqs 4 \
    --max-num-batched-tokens 8192 \
    --enable-chunked-prefill \
    --async-scheduling \
    --enable-prefix-caching \
    --load-format fastsafetensors
```

### Gemma 4 NVFP4

Gemma 4 needs vLLM's tool-calling chat template. Same idea as the weights above: pull it in advance rather than mid-setup, pinned to the vLLM version installed here.

```bash
curl -L -o tool_chat_template_gemma4.jinja \
  https://raw.githubusercontent.com/vllm-project/vllm/v0.28.0/examples/tool_chat_template_gemma4.jinja
```

Then serve, from the directory you downloaded the template into:

```bash
source unsloth-nvfp4-env/bin/activate

export CUTE_DSL_ARCH=sm_121a
export MAX_JOBS=8

vllm serve unsloth/gemma-4-26B-A4B-it-NVFP4 \
  --moe-backend flashinfer_b12x \
  --gpu-memory-utilization 0.7 \
  --max-num-seqs 8 \
  --enable-prefix-caching \
  --max-num-batched-tokens 8192 \
  --tensor-parallel-size 1 \
  --enable-auto-tool-choice \
  --tool-call-parser gemma4 \
  --default-chat-template-kwargs '{"enable_thinking":true}' \
  --chat-template tool_chat_template_gemma4.jinja \
  --reasoning-parser gemma4
```

### Nemotron 3 Nano Omni NVFP4

This one is a vision subagent rather than a main driver, so it serves on port 8001 and leaves 8000 free for Qwen or Gemma.

```bash
source unsloth-nvfp4-env/bin/activate

export CUTE_DSL_ARCH=sm_121a
export MAX_JOBS=8

vllm serve nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4 \
  --port 8001 \
  --max-model-len 131072 \
  --max-num-seqs 8 \
  --tensor-parallel-size 1 \
  --trust-remote-code \
  --gpu-memory-utilization 0.8 \
  --kv-cache-dtype fp8 \
  --video-pruning-rate 0.5 \
  --limit-mm-per-prompt '{"video": 1, "image": 1, "audio": 1}' \
  --media-io-kwargs '{"video": {"fps": 2, "num_frames": 256}}' \
  --allowed-local-media-path / \
  --enable-prefix-caching \
  --max-num-batched-tokens 32768 \
  --reasoning-parser nemotron_v3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder
```

Verify it came up, in another terminal:

```bash
curl -sS http://127.0.0.1:8001/v1/models | python3 -m json.tool
```

Audio input needs packages that plain `vllm==0.28.0` does not install, so add them with `uv pip install "vllm[audio]"` if you want to feed it sound as well as images.

If you run this alongside Qwen or Gemma on port 8000, lower `--gpu-memory-utilization` on both and drop `--max-model-len` to 32768, since the Spark shares one memory pool between them.

## Serve with llama.cpp + GGUF (tested alternative)

This track is still fully tested, and it is a good fallback if the vLLM install does not resolve cleanly on your machine.

### Build llama.cpp


Install llama.cpp locally to run Qwen 3.6, Gemma 4 and Nemotron 3 Nano Omni models.

We'll first setup the models and once we verify we're able to serve them, we'll go ahead and install OpenClaw/Hermes.

Note: ensure that you do not close the terminal where you serve the model. Start it inside `screen` or `tmux` (for example `tmux new -s qwen`) and detach with `Ctrl-b d`, so the server survives a closed window or a dropped SSH session.

```bash
#based on this https://unsloth.ai/docs/models/gemma-4 

sudo apt-get update
sudo apt-get install -y \
  build-essential \
  ca-certificates \
  cmake \
  curl \
  git \
  libcurl4-openssl-dev \
  pciutils \
  python3-pip \
  python3-venv \
  xz-utils

#this is for browser control and audio
sudo apt-get install chromium mpv

git clone https://github.com/ggml-org/llama.cpp


#currently locked to 5/4/2026 
git -C llama.cpp checkout b97ebdc98f6053604a19d861c08d8087601b96e0

cmake llama.cpp -B llama.cpp/build \
    -DBUILD_SHARED_LIBS=OFF -DGGML_CUDA=ON

cmake --build llama.cpp/build --config Release -j --clean-first --target llama-cli llama-mtmd-cli llama-server llama-gguf-split

cp llama.cpp/build/bin/llama-* llama.cpp

```

### Qwen 3.6 
We will first download Qwen3.6-35B-A3B model. (This is currently the top choice for demos focusing on coding capabilities and tool call following)

```bash
#install HF transfer if you don't have it
python3 -m venv venv
source venv/bin/activate
pip install huggingface_hub hf_transfer

hf download unsloth/Qwen3.6-35B-A3B-GGUF \
    --local-dir unsloth/Qwen3.6-35B-A3B-GGUF \
    --include "*mmproj-F16*" \
    --include "*UD-Q4_K_XL*" # Use "*UD-Q2_K_XL*" for Dynamic 2bit
```
Then, we can serve the model (warning: port 8000 is used across multiple models here and can cause conflicts if you're serving more than one model)
```bash
#use this if not enough memory
#sudo sysctl -w vm.drop_caches=3
./llama.cpp/llama-server \
--model unsloth/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf \
    --mmproj unsloth/Qwen3.6-35B-A3B-GGUF/mmproj-F16.gguf \
    --alias "unsloth/Qwen3.6-35B-A3B-GGUF" \
    --temp 0.6 \
    --top-p 0.95 \
    --ctx-size 262144 \
    --top-k 20 \
    --min-p 0.00 \
    --port 8000 \
    --checkpoint-every-n-tokens 2048 --ctx-checkpoints 64
    
#The extra checkpoints seems to reduce some lags due to misses.
#Do not enable this for demo, seems to create some corner cases where the 
#bot will not work like cron jobs will stuck
#--chat-template-kwargs '{"preserve_thinking":true}'
```

### Gemma 4
Download the Gemma 4 26B model.

```bash
source venv/bin/activate

hf download unsloth/gemma-4-26B-A4B-it-GGUF \
    --local-dir unsloth/gemma-4-26B-A4B-it-GGUF \
    --include "*mmproj-BF16*" \
    --include "*UD-Q4_K_XL*" # Use "*UD-Q2_K_XL*" for Dynamic 2bit
```

Serve the model:
```bash
#use this if not enough memory
#sudo sysctl -w vm.drop_caches=3
./llama.cpp/llama-server \
    --model unsloth/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf \
    --mmproj unsloth/gemma-4-26B-A4B-it-GGUF/mmproj-BF16.gguf \
    --temp 1.0 \
    --top-p 0.95 \
    --top-k 64 \
    --alias "unsloth/gemma-4-26B-A4B-it-GGUF" \
    --port 8000 \
    --cache-ram 0 --ctx-checkpoints 1 \
    --chat-template-kwargs '{"reasoning":"on"}'
```

### Nemotron 3 Nano Omni (Nemotron-3-Nano-30B-A3B-Omni)
Finally, Nemotron 3 Nano Omni 33B A3B.

Rather than using this as the main driver for OpenClaw, we recommend it for VLM use cases as a subagent. We're using port 8001 for this to avoid conflicts.
```bash
hf download unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF \
    --local-dir unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF \
    --include "*mmproj-BF16*" \
    --include "*UD-Q4_K_XL*"
```
Serving the model:
```bash
#use this if not enough memory
#sudo sysctl -w vm.drop_caches=3
./llama.cpp/llama-server \
    --model unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-UD-Q4_K_XL.gguf\
    --mmproj unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF/mmproj-BF16.gguf \
    --alias "unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF" \
    --prio 3 \
    --temp 1.0 \
    --top-p 1.0 \
    --port 8001
```
Now you have 3 top models ready to serve. Cheers!

## Test the server

The endpoint is OpenAI-compatible, so this is the same check on either backend. Use port 8000 for Qwen 3.6 and Gemma 4, or port 8001 for Nemotron 3 Nano Omni.

```bash
curl http://127.0.0.1:8000/v1/models
```

```bash
curl http://127.0.0.1:8000/v1/chat/completions   -H "Content-Type: application/json"   -d '{
    "messages": [
      { "role": "user", "content": "Hi" }
    ]
  }'
```

Run a couple of throwaway prompts before a live demo. The first few requests trigger JIT compilation and will spike latency.

# Part 2 — Pick your harness

Both harnesses drive the same model servers from Part 1, so nothing here is locked in and you can install both side by side.

| | OpenClaw | Hermes |
| --- | --- | --- |
| Config file | `~/.openclaw/openclaw.json` (JSON) | `~/.hermes/config.yaml` (YAML) |
| Interfaces | Web UI, terminal, Telegram | Terminal and UI dashboard |
| Add-ons covered in Part 4 | Telegram, browser control, TTS, AgentMail | Not covered |
| Minimum context window | Not enforced | 64,000 tokens |
| Imports the other's state | No | Yes, one-time OpenClaw import |

## OpenClaw setup

### Install OpenClaw

This tutorial uses one reproducible OpenClaw package version. Use a fresh host
or back up an existing OpenClaw installation before you continue, because step
2 removes any earlier installation.

```bash
# 1. Automated bootstrap. This installs core system dependencies.
curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard

# 2. Remove any earlier installation so that the pinned version is the one that runs.
openclaw uninstall --all --yes --non-interactive
npx -y openclaw uninstall --all --yes --non-interactive

# 3. Pin the package version.
npm install --global openclaw@2026.9.4

# 4. Install the global tool dependencies for the VLM and text-to-speech steps.
npm install --global sharp node-edge-tts

# 5. Report environment problems, create missing state directories, and migrate
#    an existing configuration.
openclaw doctor --fix
```

Confirm the installed version before you continue:

```bash
openclaw --version
```

The version command must identify OpenClaw `2026.9.4`.

`openclaw onboard` starts a user-level daemon and writes configuration under
`~/.openclaw`.

```bash
openclaw onboard --install-daemon
```

Now, set up vLLM as the provider. Here is an example screenshot.
![Screenshot from 2026-04-13 13-05-13](https://hackmd.io/_uploads/rkRqhpc2Wx.png)

### Reference openclaw.json

This is the tested setup for the recommended vLLM + NVFP4 track, running Qwen 3.6. The provider block lives under `models.providers` and is named `vllm`. Note that the key under `agents.defaults.models` carries the `vllm/` prefix, while the `id` inside the provider's own `models` list does not.

> [!WARNING]
> 1. Match the context size to the model, and keep `maxTokens` at 16000 or higher. A smaller value terminates tool calling and coding examples early. The config below uses the full **262144 context with 16000 max tokens**, which matches the serve command in Part 1. Dropping `contextWindow` to 131072 makes the demo more responsive if you do not need the whole window.

> 2. make sure adding "image to the input field (i.e., the "input":["text", "image"])

> 3. Replace `<your-username>` in the `workspace` path with your actual Linux user before applying the config.

```json
{
  "agents": {
    "defaults": {
      "timeoutSeconds": 300,
      "model": {
        "primary": "vllm/nvidia/Qwen3.6-35B-A3B-NVFP4"
      },
      "workspace": "/home/<your-username>/.openclaw/workspace",
      "models": {
        "vllm/nvidia/Qwen3.6-35B-A3B-NVFP4": {}
      }
    }
  },
  "models": {
    "providers": {
      "vllm": {
        "baseUrl": "http://127.0.0.1:8000/v1",
        "api": "openai-completions",
        "apiKey": "none",
        "models": [
          {
            "id": "nvidia/Qwen3.6-35B-A3B-NVFP4",
            "name": "nvidia/Qwen3.6-35B-A3B-NVFP4",
            "reasoning": true,
            "input": [ "text", "image" ],
            "cost": {
              "input": 0,
              "output": 0,
              "cacheRead": 0,
              "cacheWrite": 0
            },
            "contextWindow": 262144,
            "maxTokens": 16000
          }
        ]
      }
    }
  }
}
```

Apply it:

```bash
openclaw doctor --fix
openclaw gateway restart
```

### Switching or adding models

Every model uses the same config shape, so you never need to redo onboarding or write a second config from scratch.

To **switch** models, change the name in the three places it appears (`model.primary`, the key under `agents.defaults.models`, and the provider entry's `id` and `name`), then update `contextWindow` to match. To **add** a model alongside the current one, append another entry to the provider's `models` list instead of replacing the existing one. Either way, finish with `openclaw doctor --fix` and `openclaw gateway restart`.

The tested model names:

| Backend | Model name | `contextWindow` |
| --- | --- | --- |
| vLLM + NVFP4 | `nvidia/Qwen3.6-35B-A3B-NVFP4` | 262144 |
| vLLM + NVFP4 | `unsloth/gemma-4-26B-A4B-it-NVFP4` | 262144 |
| vLLM + NVFP4 | `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4` | 131072 |
| llama.cpp + GGUF | `unsloth/Qwen3.6-35B-A3B-GGUF` | 128000 |
| llama.cpp + GGUF | `unsloth/gemma-4-26B-A4B-it-GGUF` | 128000 |
| llama.cpp + GGUF | `unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF` | 128000 |

Nemotron 3 Nano Omni serves on port 8001, so it needs its own provider block pointing at `http://127.0.0.1:8001/v1` rather than an entry under `vllm`.

## Hermes setup

You can alternatively install Hermes Agent and use the **same model servers described above**, on either backend. That means the Qwen 3.6, Gemma 4, and Nemotron 3 Nano Omni model loading steps do **not** need to be repeated here: point Hermes at the same local OpenAI-compatible endpoint already running from the earlier sections.

### Install Hermes

> [!NOTE]
> The installer can start a setup wizard that asks about optional
> integrations. This guide needs only the model provider, the endpoint URL,
> and the API key, all covered below. You can re-run `hermes setup` at any
> time, or edit `~/.hermes/config.yaml` directly.

Hermes package version `0.21.1` is published under release tag `v2026.9.7`.
The following sequence pins both the installer bytes and the repository
checkout to that release's commit. The installer replaces the code checkout
under `~/.hermes/hermes-agent`; back up local changes and configuration first.
Pinning the installer and checkout does not make the complete installation
hermetic: the installer obtains system, runtime, and Python packages from their
configured repositories when it runs.

```bash
HERMES_COMMIT=2237be355906fbe6065ce1815711eee52b2d646e
HERMES_INSTALLER_SHA256=5854b15670b51a8daae8f59ddfa917062de9f74be261eb73b4b8d719710f8968
HERMES_INSTALLER="$(mktemp)"
trap 'rm -f "${HERMES_INSTALLER}"' EXIT

curl --fail --location --silent --show-error \
  "https://raw.githubusercontent.com/NousResearch/hermes-agent/${HERMES_COMMIT}/scripts/install.sh" \
  --output "${HERMES_INSTALLER}"

printf '%s  %s\n' "${HERMES_INSTALLER_SHA256}" "${HERMES_INSTALLER}" |
  sha256sum --check

bash "${HERMES_INSTALLER}" \
  --branch main \
  --commit "${HERMES_COMMIT}" \
  --force-commit \
  --skip-setup \
  --skip-browser \
  --skip-computer-use

rm "${HERMES_INSTALLER}"
trap - EXIT
test "$(git -C "${HOME}/.hermes/hermes-agent" rev-parse HEAD)" = \
  "${HERMES_COMMIT}"

"${HOME}/.local/bin/hermes" --version
"${HOME}/.local/bin/hermes" doctor
```

The version command must identify Hermes Agent `0.21.1`. Start a new terminal
before the remaining Hermes commands so `~/.local/bin` is on `PATH`. Running
`hermes update` later intentionally moves the installation away from this
pinned revision.

Hermes will create its own config directory here:

```text
~/.hermes/
```

### Configure Hermes to use the same models as above

Run the setup wizard:

```bash
hermes setup
```

When prompted for the model provider, select:

```text
Custom OpenAI-compatible endpoint
```

Hermes supports any OpenAI-compatible API endpoint, including local vLLM and llama.cpp servers.

Use the same server URLs already used above:

- For **Qwen 3.6** or **Gemma 4** running on port 8000:

```text
http://127.0.0.1:8000/v1
```

- For **Nemotron 3 Nano Omni** running on port 8001:

```text
http://127.0.0.1:8001/v1
```

For the API key, use any non-empty string (e.g., "none"). The local vLLM or llama.cpp server ignores it, but Hermes requires a non-empty value.

Hermes saves the selected model and endpoint configuration in:

```text
~/.hermes/config.yaml
```

### Reference config.yaml

This is the tested vLLM + NVFP4 setup. Setting `context_window` and `max_tokens` explicitly matters for the same reason as in OpenClaw: without them, long tool-calling runs get cut short.

```yaml
terminal:
  backend: local
  cwd: "."
  home_mode: auto
  timeout: 300

model:
  provider: custom
  default: nvidia/Qwen3.6-35B-A3B-NVFP4
  base_url: "http://127.0.0.1:8000/v1"
  api_mode: chat_completions
  context_window: 262144
  max_tokens: 16000
```

Then check it loaded:

```bash
hermes doctor
```

### Switching or adding models

The shape is identical for every model. Change `default` to any name from the table in the OpenClaw section, set `context_window` to match, and point `base_url` at the port that model is serving on, 8001 for Nemotron 3 Nano Omni and 8000 for everything else. Re-run `hermes doctor` afterwards; you do not need to repeat `hermes setup`.

### Start Hermes

Once configured, start Hermes with:

```bash
hermes
```

At this point, Hermes is using the **same local model servers loaded above**, just with its own config and harness.

### Troubleshooting
If Hermes can't connect, verify the model server is running  with:

```bash
curl http://127.0.0.1:8000/v1/models
```

If the server is down, restart it from the terminal where you launched the model server.



### Migrating from OpenClaw

If Hermes asks whether you want to migrate from OpenClaw, you can choose yes if you want it to import your existing OpenClaw persona, memory, and some skills as a starting point. This is a one-time import, not a live sync.

## Starting a new session or resetting

If an agent feels slow or “bogged down,” the session context has probably grown too large. Starting a new session clears that context and usually restores speed.

### OpenClaw

**New session.** Type this in chat, on the web UI, terminal, or Telegram:

```text
/new
```

**Reset session.** There are times when Qwen 3.6 or Gemma 4 starts to run long or fails to execute on tasks. Type this in the chat to clear the context. It helps when a demo carries a dependency, such as code, from a prior conversation.

```text
/reset
```

### Hermes

Hermes creates a new session whenever you start it without resuming an old one.

**New session.** After you exit the previous session, run:

```bash
hermes
```

You can also select "New session" in the Hermes dashboard for a clean conversation that carries no prior history.

# Part 3 — Run the demos

## How to use these prompts

Now it's time to have fun! Please keep in mind, the prompts below are only samples, feel free to edit them as you'd like.

Qwen 3.6 handles game building well. It does take a while to finish, since it often tries to build a near perfect game in one pass.

Be mindful about copyright: these experiments are purely a fun attempt to replicate some classic games, all locally.

## Games and interactive apps

### Make a ping-pong game and save it

```text
Can you write a simple ping pong game html app. Save it in the Desktop folder.
```
![image](https://hackmd.io/_uploads/rkRkzDQ3Wx.png)

### Upgrade the pong game, and make it better!

![image](https://hackmd.io/_uploads/Hyu_svmhbe.png)

```text
Read the ping pong file on my Desktop, and refine and make it 10 x better! Make it exciting. Save the results back on Desktop and report back to me.
```

This prompt can fail if the session has not been approved yet, since it will ask when it tries to spawn. Approve the device, then re-run it.

```bash
openclaw devices approve
```
![Neon-Cyber-Pong-04-07-2026_10_49_PM](https://hackmd.io/_uploads/H1XA2wQn-g.jpg)

or ask to change the theme:
```text
Build me a pong with cat inspired theme, and make it fun. 
```
![image](https://hackmd.io/_uploads/BymGCOnCZg.png)

### Mario inspired like games

![ezgif-6308e0899a999740](https://hackmd.io/_uploads/B1NAbOan-x.gif)

```text
Build a mario inspired game in HTML, and make sure it follows basic physics.
```

You can keep iterating by asking for more features.

```text
Add lots of details including hands, arms, legs, and more eyes to the character.
```

![ezgif-6575d5bc1c1b972d](https://hackmd.io/_uploads/H1ZiLOT2-g.gif)

### Build a game from scratch

```text
Let's make a mario game, save the work ~/Desktop/Code and code it with html5 and js.
```

![ezgif-2d9e77bf4feddb18](https://hackmd.io/_uploads/rJ4tZQeAbl.gif)

## 3D graphics and simulation

### Draw something in 3D
```text
Draw a spinning 3D cube with HTML5 and Three.js
```
![image](https://hackmd.io/_uploads/SkI19qGCWx.png)

### Go Crazy with 3D Graphics or Game

```text
Let's write a 3D mario kart game in html5 and three.js and save that here: ~/Desktop/Code/mario_kart
```
![ezgif-4541ee106b2a91ab](https://hackmd.io/_uploads/S1Nhc9MC-e.gif)

### Use Isaac Sim and build quick Physics Demo

You can prompt the engine to read documentation from GitHub (downloaded locally), and use that to drive a simple 3D simulation demo.

<iframe src="https://www.linkedin.com/embed/feed/update/urn:li:ugcPost:7455469512369393664?collapsed=1" height="542" width="504" frameborder="0" allowfullscreen="" title="Embedded post"></iframe>

### Meditation application in HTML + Three.js + Audio
![image](https://hackmd.io/_uploads/HJ146qzA-l.png)
```text
Build something great for meditation, keep the graphics smooth and simple. And add music to background with nice whitenoise.
```
<iframe width="560" height="315" src="https://www.youtube.com/embed/aQugGIV44VI?si=kDMMNvzQ_V13XPNV" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>

<iframe width="560" height="315" src="https://www.youtube.com/embed/a0kidEChjB4?si=WTJflrh2BFm3Guls" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>

## Research and writing

### Deep research, written up in two languages

```text
Do a full research and find all source code around openclaw, find the painpoints, and save them at the Desktop openclaw-pain folder. (Document in both English and Korean)
```

## Vision and CV

### Solve CV problems and write highly efficient app

You can prompt the model to solve classical CV tasks like face detection with a webcam.

```text
Build me a python application that can do face detection on a webcam. hint: use mediapipe
```

![Screenshot from 2026-05-08 11-09-26](https://hackmd.io/_uploads/Sk9ivsiAZe.jpg)

OpenClaw can now use the programmable edge device for computer-vision tasks
that you explicitly authorize.

### Lobster Cam! 
You can build on top of the CV skills above. This one shows OpenClaw onboarding a new skill.

![Image from iOS](https://hackmd.io/_uploads/SJgc0WuxMe.jpg)

First download the skill as a zip file, unzip it.

https://drive.google.com/drive/folders/1oByz-oT3-Rp1hvJQrqGg8blHlTOdOYhj?usp=sharing

Then, tell Openclaw to read and learn this skill

```text
Read the lobstercam skill in ~/Download/lobstercam and run it
```

And ask it to remember or install this skill.

```text
install the lobstercam skill
```

# Part 4 — Optional add-ons (OpenClaw)

## Enable VLM! 

Vision is switched on by the `"input": ["text", "image"]` field in the model entry, which the reference `openclaw.json` in Part 2 already sets. If you started from an older config that lists only `"text"`, add `"image"` there, then run `openclaw doctor --fix` and `openclaw gateway restart`.

Nothing extra needs to be started on the vLLM + NVFP4 track, since the vision tower ships inside the checkpoint. On llama.cpp the server must have been launched with `--mmproj`, which the serve commands in Part 1 already do.

![image](https://hackmd.io/_uploads/HJXyXt3TZl.png)
![image](https://hackmd.io/_uploads/SJ2SmYha-e.png)

Install `fswebcam` if you choose to connect a camera. Camera capture exposes
device data to the agent, so review each prompt and scheduled action before you
enable it.

![image](https://hackmd.io/_uploads/Skze3E6Tbg.png)

## Email your game to your friends

1. Setup Agentmail

Create an account https://agentmail.to, and then create an inbox. Get the API Key, save it in .env file under .openclaw directory.

```bash
npx clawhub@latest install agentmail

#then restart gateway
openclaw gateway restart

#When you are ready, prompt in the chat to set up your email address before asking to send email.
```

Talk to the Openclaw chatbot, give it instructions and will finalize the setup.
```text
You have access to AgentMail — an Email API for Agents.
The llms.txt file is a very good starting point. Read it first, then go from there based on what the user needs.

llms.txt (overview + all doc links): https://docs.agentmail.to/llms.txt
llms-full.txt (complete reference with inline code examples): https://docs.agentmail.to/llms-full.txt
```
![image](https://hackmd.io/_uploads/HJU98lU3be.png)

![Screenshot 2026-04-08 at 1.15.01 PM](https://hackmd.io/_uploads/HJtIPVVhZe.png)

![image](https://hackmd.io/_uploads/r1e0O4V2Wg.png)

## Add Telegram

Create the Bot: Open Telegram, message @BotFather, and use the /newbot command. Follow instructions to name your bot and receive the API token.


Then on your Spark, go to terminal and type this
```bash
openclaw configure --section channels
```

Then go to Telegram and type `/start` in your bot.

Then, go back to terminal
```bash
openclaw pairing list telegram
openclaw pairing approve telegram <pairing token>
```

You can now message the bot, and a new session appears under Telegram.

## Control your web browser and Do anything!

Enable control with debugging on Chromium. Use a dedicated profile for remote
debugging, and keep that profile free of sensitive logins or browsing data.

```bash
CHROMIUM_DEBUG_PROFILE="$HOME/snap/chromium/common/openclaw-debug-profile"
install -d -m 700 "$CHROMIUM_DEBUG_PROFILE"
/snap/bin/chromium \
  --user-data-dir="$CHROMIUM_DEBUG_PROFILE" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222
```

Update the openclaw.json file.
```json
  "browser": {
    "cdpUrl": "http://127.0.0.1:9222",
    "attachOnly": true,
    "profiles": {
      "chrome": {
        "cdpUrl": "http://127.0.0.1:9222",
        "attachOnly": true,
        "color": "#4285F4"
      }
    }
  }
```

Lastly restart openclaw.
```bash
openclaw gateway restart
openclaw browser start
```

Then, tell openclaw to try controlling your browser, and will figure it out itself

```text
use the built-in browser skill to open the browser and search for nvidia
```

```text
open amazon and find me the engine oil 5w-30 for my BMW
```

<iframe width="560" height="315" src="https://www.youtube.com/embed/GfxS5SkQxKw?si=gon32oqPnSrj9WAv" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>

## Podcast style, turn content into speech on webchat

Ask openclaw to install a local tts tool, like node-edge-tts.
```text
can you install node-edge-tts 

#openclaw should trigger this, if not you can do it manually
#npm install node-edge-tts
```

Once it's all installed and we can play it back with mpv via the TTS. mpv is installed above, if not install it with `apt-get install mpv`
```text
Try this: 
npx node-edge-tts -t "Hello from NVBot" -f /tmp/test.mp3 && mpv /tmp/test.mp3 & 
```

```text
ok find today's news and play it back that way
```

Then you should save the skill to make it runs faster the next time (minimizing the discovery steps)

```text
save this skill
```

OpenClaw will create a skill file so a later podcast request can reuse the
procedure.

![Screenshot from 2026-05-14 20-19-07](https://hackmd.io/_uploads/rkJpeMVJGe.png)

This is the fully workaround to get TTS working on Webchat interface.

If you have Telegram, you can just use the default TTS built-in skill, and should just work out of the box without using mpv.

```text
\tts on
```

This will turn on TTS, and you can see the audio files pop up as media attachment each time you talk to the agent.

https://docs.openclaw.ai/tools/tts

# Part 5 — Reference and troubleshooting

## Known Issues:

### Model serving (vLLM + NVFP4)

1. Warm-up matters. The first few requests trigger Triton JIT compilation and produce visible latency spikes:

```text
(EngineCore pid=157707) WARNING 08-18 21:17:24 [jit_monitor.py:135] Triton kernel JIT compilation during inference: _compute_slot_mapping_kernel. This causes a latency spike; consider extending warmup to cover this shape/config.
```

Run a couple of throwaway prompts before going live.

2. Run the kernel check before serving. If `b12x` is unavailable, vLLM still starts but falls back to marlin W4A16, so you quietly lose the NVFP4 speedup with no error.

3. NVFP4 checkpoints are not interchangeable even when they share a model name. Qwen 3.6 tested better from NVIDIA, Gemma 4 tested better from Unsloth. Measure rather than assume.

4. On GPUs other than the Spark you may hit a KV cache error like the one below. Lower `--max-model-len` or raise `--gpu-memory-utilization`.

```text
ValueError: To serve at least one request with the model's max seq len (262144), (3.04 GiB KV cache is needed, which is larger than the available KV cache memory (1.89 GiB). Based on the available memory, the estimated maximum model length is 153216.
```

### Model serving (llama.cpp)

A few known issues:

1. The cache-ram and ctx checkpoints will burn the ram, make sure you add these (reported on 4/6/2026)
https://www.reddit.com/r/LocalLLaMA/comments/1sdqvbd/comment/oekiv3j/
https://www.reddit.com/r/openclaw/comments/1sb3ezf/ollamagemma4_is_completely_useless_for_openclaw/

You can also experiment with the RAM size and checkpoints for additional performance.
```bash
    --cache-ram 2048 --ctx-checkpoints 2
```

2. Long tool calling has proven to be challenging, so when we run a demo continue to provide additional instructions like "continue working".

### Models and harness

1. Gemma 4:26b still have the issues in tool calling with openclaw, and there are times it will stop early without warning. Please plan your demo carefully when you are using Gemma 4.
2. Qwen 3.6-35b is amazing at coding, but also takes a long while to complete the job (it seems love to make things perfect on one shot). I will recommend starting with simplier prompt with more directions, to avoid the model go all-in with a single prompt for more responsive demo.
3. Nemotron 3 Nano Omni is not designed to be the main driver for openclaw. It is great for subagent tasks like VLMs and reasoning things in a scene or world.

### Workarounds and Findings

1. Avoid long open ended tasks. The agent does not have limits on its capabilities, thus it can go try do things impossible within some timeframes. For example, 'process 10000 images with VLM'. This will create a long running loop that may eventually failed. We do not have guardrails for this behavior yet.


2. VLMs and multiple models. Nemotron-3-Nano-Omni got better throughput for VLM, but not as great for using as the main driver for openclaw. The workaround now is to enable Nemotron-3-Nano-Omni as subagent tasks.

## Clean Up before Cloning Checklist

- [ ] Remove Ollama Private Key (important)
- [ ] Remove .ssh folder private key (important)
- [ ] Openclaw Session History (use /reset)
- [ ] Delete firefox cookies and caches
- [ ] Delete chrome cookies and caches
- [ ] Clean up Desktop any temp files
- [ ] ~/.openclaw/identity/device-auth.json (OpenClaw tokens)
- [ ] ~/.openclaw/devices/paired.json (paired device tokens)
- [ ] ~/.openclaw/exec-approvals.json (exec socket token)
- [ ] ~/.openclaw/openclaw.json (rename token per machine)
- [ ] Remove chromium lock file `rm ~/snap/chromium/common/chromium/Singleton*`
- [ ] Clear Hermes session history / active chats
- [ ] Review `~/.hermes/config.yaml` and `~/.hermes/.env` for local secrets or personal identifiers
