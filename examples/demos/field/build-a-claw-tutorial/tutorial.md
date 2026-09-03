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
  AgentMail, Telegram, LinkedIn, YouTube, Ollama, and other public services.
  Those services can apply usage terms, collect connection data, or charge
  fees.
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

# Part 1 — Serve a model with llama.cpp

## Build llama.cpp for OpenClaw or Hermes


Install llama.cpp locally to run Qwen 3.6, Gemma 4, and Nemotron 3 Nano Omni
models.

Set up and verify one model server before you install OpenClaw or Hermes.

Note: ensure that you do not close the terminal where you serve the model. 

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

git clone https://github.com/ggml-org/llama.cpp

# Commit recorded by the tutorial author on 2026-05-04.
git -C llama.cpp checkout b97ebdc98f6053604a19d861c08d8087601b96e0

cmake llama.cpp -B llama.cpp/build \
    -DBUILD_SHARED_LIBS=OFF -DGGML_CUDA=ON

cmake --build llama.cpp/build --config Release -j --clean-first --target llama-cli llama-mtmd-cli llama-server llama-gguf-split

cp llama.cpp/build/bin/llama-* llama.cpp

```

## Qwen 3.6

Download the Qwen3.6-35B-A3B model. Review its license and available disk
space before you start the multi-gigabyte transfer.

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
    
# The extra checkpoints can reduce cache-miss latency. Disable them if they
# cause unexpected behavior in the workload that you are demonstrating.
#--chat-template-kwargs '{"preserve_thinking":true}'
```

Test the server in a new terminal tab, making sure you get a response.
```bash
curl http://127.0.0.1:8000/v1/chat/completions   -H "Content-Type: application/json"   -d '{
    "messages": [
      { "role": "user", "content": "Hi" }
    ]
  }'
```

## Gemma 4
Download the Gemma 4 26B model.

```bash
#install HF transfer if you don't have it
python3 -m venv venv
source venv/bin/activate
pip install huggingface_hub hf_transfer

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

Once again, you can test the server:
```bash
curl http://127.0.0.1:8000/v1/chat/completions   -H "Content-Type: application/json"   -d '{
    "messages": [
      { "role": "user", "content": "Hi" }
    ]
  }'

```

## Nemotron 3 Nano Omni (Nemotron-3-Nano-30B-A3B-Omni)
Finally, Nemotron 3 Nano Omni 33B A3B.

Use this model for vision-language model (VLM) work rather than as the primary
OpenClaw model. This configuration uses port `8001` to avoid a conflict with
the model server on port `8000`.
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
In another terminal window, test the server: 
```bash
curl http://127.0.0.1:8001/v1/chat/completions   -H "Content-Type: application/json"   -d '{
    "messages": [
      { "role": "user", "content": "Hi" }
    ]
  }'
```

You now have three model-server configurations. Qwen 3.6 and Gemma 4 both use
port `8000`, so run only one of those configurations at a time.

# Part 2 — Pick your harness

## OpenClaw setup

This tutorial uses one reproducible OpenClaw package version. The package
installation and CLI startup were checked on 2026-09-03 in an isolated Debian
Bookworm container with Node.js `24.15.0`. That check did not exercise DGX
Spark, onboarding, the daemon, or model connectivity. Use a fresh host or back
up an existing OpenClaw installation before you continue.

```bash
npm install --global openclaw@2026.7.1-2
openclaw --version
```

Expected version output:

```text
OpenClaw 2026.7.1-2 (0790d9f)
```

Inspect the environment before onboarding. `openclaw onboard` installs and
starts a user-level daemon and writes configuration under `~/.openclaw`.

```bash
openclaw doctor
openclaw onboard --install-daemon
```

Now, set up vLLM as the provider. Here is an example screenshot.
![Screenshot from 2026-04-13 13-05-13](https://hackmd.io/_uploads/rkRqhpc2Wx.png)

You can switch between these three llama.cpp model configurations.
```text
unsloth/gemma-4-26B-A4B-it-GGUF
unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF
unsloth/Qwen3.6-35B-A3B-GGUF
```


Use the following `openclaw.json` fragments as configuration references.

> [!WARNING]
> Match the context window to the selected model. These examples use a
> 128,000-token context window and a 16,000-token output limit. A lower output
> limit can stop long tool or coding tasks before completion. For a VLM, also
> include `"image"` in the model's `input` array.

And you can replace the models by replacing the names (e.g., from "unsloth/gemma-4-26B-A4B-it-GGUF" to "unsloth/Qwen3.6-35B-A3B-GGUF" vice versa).

For example, use this reference fragment for Qwen 3.6:

```text
{
  "agents": {
    "defaults": {
      "timeoutSeconds": 300,
      "model": {
        "primary": "vllm/unsloth/Qwen3.6-35B-A3B-GGUF"
      },
      "workspace": "/home/nvidia/.openclaw/workspace",
      "models": {
        "unsloth/Qwen3.6-35B-A3B-GGUF": {}
      }
    }
  },
  ...
  
      "vllm": {
        "baseUrl": "http://127.0.0.1:8000/v1",
        "api": "openai-completions",
        "apiKey": "VLLM_API_KEY",
        "models": [
          {
            "id": "unsloth/Qwen3.6-35B-A3B-GGUF",
            "name": "unsloth/Qwen3.6-35B-A3B-GGUF",
            "reasoning": true,
            "input": [
              "text", "image"
            ],
            "cost": {
              "input": 0,
              "output": 0,
              "cacheRead": 0,
              "cacheWrite": 0
            },
            "contextWindow": 128000,
            "maxTokens": 16000
          }
        ]
      }
    }
 ...
```

Use this reference fragment for Gemma 4:

```text
{
  "agents": {
    "defaults": {
      "timeoutSeconds": 300,
      "model": {
        "primary": "vllm/unsloth/gemma-4-26B-A4B-it-GGUF"
      },
      "workspace": "/home/nvidia/.openclaw/workspace",
      "models": {
        "vllm/unsloth/gemma-4-26B-A4B-it-GGUF": {}
      }
    }
  },
  ...
  
      "vllm": {
        "baseUrl": "http://127.0.0.1:8000/v1",
        "api": "openai-completions",
        "apiKey": "VLLM_API_KEY",
        "models": [
          {
            "id": "unsloth/gemma-4-26B-A4B-it-GGUF",
            "name": "unsloth/gemma-4-26B-A4B-it-GGUF",
            "reasoning": true,
            "input": [
              "text", "image"
            ],
            "cost": {
              "input": 0,
              "output": 0,
              "cacheRead": 0,
              "cacheWrite": 0
            },
            "contextWindow": 128000,
            "maxTokens": 16000
          }
        ]
      }
    }
 ...
```

## Hermes setup

You can alternatively install Hermes Agent and use the **same llama.cpp
model servers described above**. That means the Qwen 3.6, Gemma 4, and Nemotron 3 Nano
Omni model loading steps do **not** need to be repeated here — just point Hermes at the
same local OpenAI-compatible endpoint already running from the earlier sections.

### Install Hermes

Hermes package version `0.20.2` is published under release tag `v2026.8.16`.
The following sequence pins both the installer bytes and repository checkout to
that release's commit. The installer replaces the code checkout under
`~/.hermes/hermes-agent`; back up local changes and configuration first. This
exact install, checkout assertion, version check, and diagnostic sequence was
checked on 2026-09-03 in an isolated Ubuntu 24.04 ARM64 container. It has not
been verified on DGX Spark or against the tutorial's model servers.
Pinning the installer and checkout does not make the complete installation
hermetic: the installer obtains system, runtime, and Python packages from their
configured repositories when it runs.

```bash
HERMES_COMMIT=df4b65147d7ddd74dd449f9067aabbca5aef0ec7
HERMES_INSTALLER_SHA256=f88d88dfc54f907bd8352f1b37afccda6f383081ddc456375baac3eb77fc4188
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

The version command must identify Hermes Agent `0.20.2`. Start a new terminal
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

Hermes supports any OpenAI-compatible API endpoint, including local llama.cpp servers.

Use the same server URLs already used above:

- For **Qwen 3.6** or **Gemma 4** running on port 8000:

```text
http://127.0.0.1:8000/v1
```

- For **Nemotron 3 Nano Omni** running on port 8001:

```text
http://127.0.0.1:8001/v1
```

For the API key, use any non-empty string (e.g., "none"). The local llama-server ignores it, but Hermes requires a non-empty value.    

Hermes saves the selected model and endpoint configuration in:

```text
~/.hermes/config.yaml
```

### Example Hermes config for Qwen 3.6

```yaml
 model:                                                                        
    default: unsloth/Qwen3.6-35B-A3B-GGUF                                       
    provider: custom                                                            
    base_url: http://127.0.0.1:8000/v1                                          
    api_mode: chat_completions   
```

### Example Hermes config for Gemma 4

If using Gemma 4 with VLM enabled from the llama.cpp setup above, include image input too:

```yaml
  model:                                                                        
    default: unsloth/gemma-4-26B-A4B-it-GGUF                                    
    provider: custom                                                            
    base_url: http://127.0.0.1:8000/v1                                          
    api_mode: chat_completions  
```

### Example Hermes config for Nemotron 3 Nano Omni

```yaml
  model:                                                                        
    default: unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF         
    provider: custom                                                            
    base_url: http://127.0.0.1:8001/v1                                          
    api_mode: chat_completions  
```

### Start Hermes

Once configured, start Hermes with:

```bash
hermes
```

At this point, Hermes is using the **same local model servers loaded above**, just with its own config and harness.

#### Troubleshooting: 
If Hermes can't connect, verify the model server is running  with: 

```bash
curl http://127.0.0.1:8000/v1/models
```

If the server is down, restart it from the terminal where you launched llama.cpp.     



### Note

If Hermes asks whether you want to migrate from OpenClaw, you can choose yes if you want it to import your existing OpenClaw persona, memory, and some skills as a starting point. This is a one-time import, not a live sync.

## Starting a new session or resetting

If an agent feels slow or “bogged down,” the session context has probably grown too
large. Starting a new session clears that context and usually restores speed.

### OpenClaw

- **New session:**

  In chat (web UI / terminal / Telegram):

```text
/new
```

- **Reset session:**

  There are times when Qwen3.6 or Gemme 4 starts to run long or failed to execute on tasks. You can reset session by typing this command in the chat. This will clear out the context, and will help when some demos may have dependencies such as coding from prior conversations.

```text
/reset
```

### Hermes

Hermes creates a new session whenever you start it without resuming an old one.

- **New session:**

  After you exit the previous session:

```bash
hermes
```

  Or use “New session” in the Hermes UI / dashboard for a clean conversation
  without carrying over prior history.

# Part 3 — Run the demos

## Fun prompts
Now it's time to have fun! Please keep in mind, the prompts below are only samples, feel free to edit them as you'd like. 

### 1. Make a ping-pong game and save it

```text
Can you write a simple ping pong game html app. Save it in the Desktop folder.
```
![image](https://hackmd.io/_uploads/rkRkzDQ3Wx.png)


### 2. Get the latest event information and plan for you!

```text
Do a full research and find all source code around openclaw, find the painpoints, and save them at the Desktop openclaw-pain folder. (Document in both English and Korean)
```


### 3. Upgrade the pong game, and make it better!

![image](https://hackmd.io/_uploads/Hyu_svmhbe.png)

```text
Read the ping pong file on my Desktop, and refine and make it 10 x better! Make it exciting. Save the results back on Desktop and report back to me.
```

This prompt may fail depends if you have approved the sessions (when it ask for spawn): Run the following command to approve them before re-running it.

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

And you can keep improving it by asking it to improve it continuously with some features.


```text
Add lots of details including hands, arms, legs, and more eyes to the character.
```


![ezgif-6575d5bc1c1b972d](https://hackmd.io/_uploads/H1ZiLOT2-g.gif)



## Qwen 3.6 Prompts

Qwen 3.6 can take time to complete a detailed game-building task.

```text
Let's make a mario game, save the work ~/Desktop/Code and code it with html5 and js.

```

![ezgif-2d9e77bf4feddb18](https://hackmd.io/_uploads/rJ4tZQeAbl.gif)


Of course, we should be mindful about copyright. Keep in mind that these experiments are purely a fun attempt to replicate some classic games, all locally. 

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

You can prompt the engine to read documentations from github (download locally), and use that to drive a simple 3D simluation demo.

<iframe src="https://www.linkedin.com/embed/feed/update/urn:li:ugcPost:7455469512369393664?collapsed=1" height="542" width="504" frameborder="0" allowfullscreen="" title="Embedded post"></iframe>

### Meditation application in HTML + Three.js + Audio
![image](https://hackmd.io/_uploads/HJ146qzA-l.png)

```text
yea, build something great for mediation, keep the graphics smooth and simple. And add music to background with nice whitenoise.

```
<iframe width="560" height="315" src="https://www.youtube.com/embed/aQugGIV44VI?si=kDMMNvzQ_V13XPNV" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>

<iframe width="560" height="315" src="https://www.youtube.com/embed/a0kidEChjB4?si=WTJflrh2BFm3Guls" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>

### Solve CV problems and write highly efficient app

You can prompt the model to solve classical CV tasks like face detection with a webcam.

```text
Build me a python application that can do face detection on a webcam. hint: use mediapipe
```

![Screenshot from 2026-05-08 11-09-26](https://hackmd.io/_uploads/Sk9ivsiAZe.jpg)

OpenClaw can now use the programmable edge device for computer-vision tasks
that you explicitly authorize.

# Part 4 — Optional add-ons (OpenClaw)

## Enable VLM! 

You can enable VLM by modifying the `openclaw.json`. You need to add "image" as part of the input.

```json
"vllm": {
        "baseUrl": "http://127.0.0.1:8000/v1",
        "api": "openai-completions",
        "apiKey": "VLLM_API_KEY",
        "models": [
          {
            "id": "unsloth/gemma-4-26B-A4B-it-GGUF",
            "name": "unsloth/gemma-4-26B-A4B-it-GGUF",
            "reasoning": false,
            "input": [
              "text", "image"
            ],
            "cost": {
              "input": 0,
              "output": 0,
              "cacheRead": 0,
              "cacheWrite": 0
            },
            "contextWindow": 128000,
            "maxTokens": 8192
          }
        ]
      }

```

![image](https://hackmd.io/_uploads/HJXyXt3TZl.png)
![image](https://hackmd.io/_uploads/SJ2SmYha-e.png)

Install `fswebcam` if you choose to connect a camera. Camera capture exposes
device data to the agent, so review each prompt and scheduled action before you
enable it.

![image](https://hackmd.io/_uploads/Skze3E6Tbg.png)

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

Done. :+1:  You can now text the chatbot, and you will see a new session under telegram.

## Control your web browser and Do anything!

Enable control with debugging on Chromium
```bash
/snap/bin/chromium  --remote-debugging-port=9222   --remote-debugging-address=127.0.0.1 
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

## Alternative Serving to Try Next

We can also simplify the onboarding with Ollama (given the risk I explained above). I have had lots of headaches due to timeout, or tool calling got stopped randomly! So use this if and only if you are only using it for testing or quick validations. There are workarounds on timeout but needed further investigations.

The following optional path uses Ollama's external installer. Inspect that
script before running it and confirm that Ollama detects the DGX Spark GPU.

```bash
# Request the tutorial's recorded Ollama version from the external installer.
curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.23.1 sh


#pull all models are great starter for openclaw experiences
#main driver
ollama pull qwen3.6:35b

#vlm and subagents
ollama pull nemotron3:33b

#long reasoning
ollama pull nemotron-3-super

#coding and well-rounded
ollama pull gemma4:26b

```

That script above will provide a simple chatbot interface on terminal and you can see it in action. 

```bash
ollama ps
```

Also, make sure you check the model is running 100% on GPU. If there are any issues. Try repeating steps here and debug:

https://build.nvidia.com/spark/open-webui/sync

When the model is all ready. Now you can run this command to switch the primary/default model. Or simply follow the onboarding here to install openclaw with Ollama together (do not do that if you have openclaw pre-installed). 

https://docs.ollama.com/integrations/openclaw

```bash
openclaw models set ollama/qwen3.6:35b
openclaw gateway restart
```

Confirm that the new model appears in OpenClaw. You can then switch back to the
llama.cpp server with these commands.

```bash
openclaw models set vllm/unsloth/Qwen3.6-35B-A3B-GGUF
openclaw gateway restart
```

## Known Issues:

### Model serving (llama.cpp)

A few known issues:

1. The cache-ram and ctx checkpoints will burn the ram, make sure you add these (reported on 4/6/2026)
https://www.reddit.com/r/LocalLLaMA/comments/1sdqvbd/comment/oekiv3j/
https://www.reddit.com/r/openclaw/comments/1sb3ezf/ollamagemma4_is_completely_useless_for_openclaw/

Also, we should experiment with the RAM size and checkpoints to see if we can get any performance gain. 
```bash
    --cache-ram 2048 --ctx-checkpoints 2
```

2. The tutorial author observed early termination during some long Ollama
   tasks. Recheck tool calling before you use Ollama in a live demonstration.

3. Long tool calling has proven to be challenging, so when we run a demo continue to provide additional instructions like "continue working".

### Models and harness

1. Gemma 4:26b still have the issues in tool calling with openclaw, and there are times it will stop early without warning. Please plan your demo carefully when you are using Gemma 4. Will update on this thread next.
2. Qwen 3.6-35b is amazing at coding, but also takes a long while to complete the job (it seems love to make things perfect on one shot). I will recommend starting with simplier prompt with more directions, to avoid the model go all-in with a single prompt for more responsive demo.
3. nemotron3:33b model is not designed for openclaw. It is great for subagent tasks like VLMs and reasoning things in a scene or world.

Ollama is giving bad output for gemma4, and you can see in the coding example with extra space and typos.
![image](https://hackmd.io/_uploads/r1_12XtAWg.png)

### Workarounds and Findings

1. Avoid open-ended tasks without a time, cost, or item limit. A request such as
   `process 10000 images with VLM` can create a long-running loop that fails
   before completion. This tutorial does not add a NemoClaw policy boundary.


2. VLMs and multiple models. Nemotron-3-Nano-Omni got better throughput for VLM, but not as great for using as the main driver for openclaw. The workaround now is to enable Nemotron-3-Nano-Omni as subagent tasks, and ideally create custom APIs access to the serving. This it our TODO.

## Some benchmarks to consider in token/s (ollama) and tokens to answers

Prompt used: "why is the sky blue?" 
This will trigger reasoning by default.
A good starter reference.

`ollama run gemma4:26b --verbose`
```text
total duration:       22.044060213s
load duration:        157.290371ms
prompt eval count:    22 token(s)
prompt eval duration: 58.758482ms
prompt eval rate:     374.41 tokens/s
eval count:           1177 token(s)
eval duration:        21.322907413s
eval rate:            55.20 tokens/s
```

`ollama run qwen3.6:35b --verbose`
```text
total duration:       25.762780738s
load duration:        128.753395ms
prompt eval count:    16 token(s)
prompt eval duration: 93.703548ms
prompt eval rate:     170.75 tokens/s
eval count:           1328 token(s)
eval duration:        25.176357481s
eval rate:            52.75 tokens/s
```
`ollama run nemotron-3-super --verbose`
```text
total duration:       1m1.157069916s
load duration:        93.651335ms
prompt eval count:    23 token(s)
prompt eval duration: 235.60176ms
prompt eval rate:     97.62 tokens/s
eval count:           1028 token(s)
eval duration:        1m0.652425495s
eval rate:            16.95 tokens/s
```

`ollama run nemotron3:33b --verbose`
```text
total duration:       6.498845722s
load duration:        94.549186ms
prompt eval count:    23 token(s)
prompt eval duration: 91.564899ms
prompt eval rate:     251.19 tokens/s
eval count:           359 token(s)
eval duration:        6.134583631s
eval rate:            58.52 tokens/s
```


https://hackmd.io/ZvP9JnFETmuDuB0CQESukw

## Clean Up before Cloning Checklist

- [ ] Remove Ollama Private Key (important)
- [ ] Remove .ssh folder private key (important)
- [ ] OpenClaw session history (use `/reset`)
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
