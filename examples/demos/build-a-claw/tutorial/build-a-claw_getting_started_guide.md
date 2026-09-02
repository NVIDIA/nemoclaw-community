# OpenClaw/Hermes on NVIDIA Spark with Qwen 3.6 / Gemma 4 / Nemotron 3 Nano Omni

[TOC]

# Part 1 — Serve a model with llama.cpp

## Llama.cpp x Openclaw manual setup


Install llama.cpp locally to run Qwen 3.6, Gemma 4 and Nemotron 3 Nano Omni models.

We'll first setup the models and once we verify we're able to serve them, we'll go ahead and install OpenClaw/Hermes. 

Note: ensure that you do not close the terminal where you serve the model. 

```bash
#based on this https://unsloth.ai/docs/models/gemma-4 

sudo apt-get update
sudo apt-get install pciutils build-essential cmake curl libcurl4-openssl-dev -y python3-pip python3-venv

#this is for browser control and audio
sudo apt-get install chromium mpv

git clone https://github.com/ggml-org/llama.cpp

#lock to the version on 4/26 tested by Ray for GTC Taipei 
#git -C llama.cpp checkout 5594d132244aeb1bae54dd431e7efbc908f5e3b8

#locked today 5/4/2026 :-- very stable so far
git -C llama.cpp checkout b97ebdc98f6053604a19d861c08d8087601b96e0

cmake llama.cpp -B llama.cpp/build \
    -DBUILD_SHARED_LIBS=OFF -DGGML_CUDA=ON

cmake --build llama.cpp/build --config Release -j --clean-first --target llama-cli llama-mtmd-cli llama-server llama-gguf-split

cp llama.cpp/build/bin/llama-* llama.cpp

```

## Qwen 3.6 
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

Here, we rather than for OpenClaw, we recommend using this for vlm use cases as a subagent. We're using port 8001 for this to avoid conflicts.
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

Now you have 3 models top models ready to serve. Cheers!

# Part 2 — Pick your harness

## Openclaw Setup

```bash
curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard

#if you have version too new you can install with this
#to avoid demo failure that's been tested -- uninstall and reinstall
#OpenClaw 2026.5.4 (325df3e) — latest stable

openclaw uninstall --all --yes --non-interactive
npx -y openclaw uninstall --all --yes --non-interactive
#npm install -g openclaw@2026.5.7 #current one mostly used
#seems stable.
npm install -g openclaw@2026.5.12

#image processing for vlm
npm install -g sharp
#tts feature
npm install -g node-edge-tts
```

```bash
openclaw onboard --install-daemon
```

NOTE: Currently testing 2026.7.1:
```bash
# 1. Automated bootstrap (installs core system dependencies)
curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard

# 2. Pin to the tested 2026.7.1-2 stable release
npm install -g openclaw@2026.7.1-2

# 3. Global tool dependencies for VLM & TTS features
npm install -g sharp node-edge-tts

# 4.Verify environment health, create missing state directories, and migrate existing configs (if needed) 
openclaw doctor --fix
```

```bash
openclaw onboard --install-daemon
```

Now, set up vLLM as the provider. Here is an example screenshot.
![Screenshot from 2026-04-13 13-05-13](https://hackmd.io/_uploads/rkRqhpc2Wx.png)

Again, you can switch between these 3 models with llama.cpp.
```
unsloth/gemma-4-26B-A4B-it-GGUF
unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF
unsloth/Qwen3.6-35B-A3B-GGUF
```


You can use this openclaw.json file as the reference setup:
> WARNING: !! IMPORTANT READS 
> 1. Please make sure you match the context size for the model correctly (i.e., 256k max), and increase the maxToken to at least 16k or higher. Otherwise the tool calling or coding examples will break because of early terminations. I have chosen **128k and 16k max token for performance reason** for faster responding demo.

> 2. make sure adding "image to the input field (i.e., the "input":["text", "image"]) 

And you can replace the models by replacing the names (e.g., from "unsloth/gemma-4-26B-A4B-it-GGUF" to "unsloth/Qwen3.6-35B-A3B-GGUF" vice versa).

e.g., for Qwen 3.6.
```
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

or for Gemma 4:
```
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

## Hermes Setup

You can alternatively install Hermes Agent and use the **same llama.cpp
model servers described above**. That means the Qwen 3.6, Gemma 4, and Nemotron 3 Nano
Omni model loading steps do **not** need to be repeated here — just point Hermes at the
same local OpenAI-compatible endpoint already running from the earlier sections.

### Install Hermes

Run this on the Spark:

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
git -C ~/.hermes/hermes-agent checkout v0.20.2
source ~/.bashrc
hermes doctor
```
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

```
Can you write a simple ping pong game html app. Save it in the Desktop folder.
```
![image](https://hackmd.io/_uploads/rkRkzDQ3Wx.png)


### 2. Get the latest event information and plan for you!

```
Do a full research and find all source code around openclaw, find the painpoints, and save them at the Desktop openclaw-pain folder. (Document in both English and Korean)
```


### 3. Upgrade the pong game, and make it better!

![image](https://hackmd.io/_uploads/Hyu_svmhbe.png)

```
Read the ping pong file on my Desktop, and refine and make it 10 x better! Make it exciting. Save the results back on Desktop and report back to me.
```

This prompt may fail depends if you have approved the sessions (when it ask for spawn): Run the following command to approve them before re-running it.

```bash
openclaw devices approve
```
![Neon-Cyber-Pong-04-07-2026_10_49_PM](https://hackmd.io/_uploads/H1XA2wQn-g.jpg)

or ask to change the theme: 
```
Build me a pong with cat inspired theme, and make it fun. 
```
![image](https://hackmd.io/_uploads/BymGCOnCZg.png)


### Mario inspired like games

![ezgif-6308e0899a999740](https://hackmd.io/_uploads/B1NAbOan-x.gif)

```
Build a mario inspired game in HTML, and make sure it follows basic physics.
```

And you can keep improving it by asking it to improve it continuously with some features.


```
Add lots of details including hands, arms, legs, and more eyes to the character.
```


![ezgif-6575d5bc1c1b972d](https://hackmd.io/_uploads/H1ZiLOT2-g.gif)



## Qwen 3.6 Prompts

Qwen 3.6 has been doing great at game building. It does however take a while to complete it's task, since it often trys to create a near perfect game. 
```
Let's make a mario game, save the work ~/Desktop/Code and code it with html5 and js.

```

![ezgif-2d9e77bf4feddb18](https://hackmd.io/_uploads/rJ4tZQeAbl.gif)


Of course, we should be mindful about copyright. Keep in mind that these experiments are purely a fun attempt to replicate some classic games, all locally. 

### Draw something in 3D
```
Draw a spinning 3D cube with HTML5 and Three.js
```
![image](https://hackmd.io/_uploads/SkI19qGCWx.png)

### Go Crazy with 3D Graphics or Game

```
Let's write a 3D mario kart game in html5 and three.js and save that here: ~/Desktop/Code/mario_kart
```
![ezgif-4541ee106b2a91ab](https://hackmd.io/_uploads/S1Nhc9MC-e.gif)

### Use Isaac Sim and build quick Physics Demo

You can prompt the engine to read documentations from github (download locally), and use that to drive a simple 3D simluation demo.

<iframe src="https://www.linkedin.com/embed/feed/update/urn:li:ugcPost:7455469512369393664?collapsed=1" height="542" width="504" frameborder="0" allowfullscreen="" title="Embedded post"></iframe>

### Meditation application in HTML + Three.js + Audio
![image](https://hackmd.io/_uploads/HJ146qzA-l.png)
```
yea, build something great for mediation, keep the graphics smooth and simple. And add music to background with nice whitenoise.

```
<iframe width="560" height="315" src="https://www.youtube.com/embed/aQugGIV44VI?si=kDMMNvzQ_V13XPNV" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>

<iframe width="560" height="315" src="https://www.youtube.com/embed/a0kidEChjB4?si=WTJflrh2BFm3Guls" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>

### Solve CV problems and write highly efficient app

You can prompt the model to solve classical CV tasks like face detection with a webcam.

```
Build me a python application that can do face detection on a webcam. hint: use mediapipe
```

![Screenshot from 2026-05-08 11-09-26](https://hackmd.io/_uploads/Sk9ivsiAZe.jpg)

Now we can have openclaw to manage a programmable edge device that can be tuned to different CV applications with your own prompt!

### Lobster Cam! 
You can make fun apps with the CV skills above. Here's a sample of making OpenClaw onboard a new fun skill. 


![Image from iOS](https://hackmd.io/_uploads/SJgc0WuxMe.jpg)

First download the skill as a zip file, unzip it. 

https://drive.google.com/drive/folders/1oByz-oT3-Rp1hvJQrqGg8blHlTOdOYhj?usp=sharing

Then, tell Openclaw to read and learn this skill

```
Read the lobstercam skill in ~/Download/lobstercam and run it
```

And ask it to remember or install this skill. 

```
install the lobstercam skill
```

# Part 4 — Optional add-ons (OpenClaw)

## Enable VLM! 

You can enable VLM by modifying the `openclaw.json`. You need to add "image" as part of the input.

```
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

Cconnect this to your webcam with fswebcam with (`apt-get install fswebcam`). Then, you can setup a prompt to do something like a cron job with webcam easily with the VLM.

![image](https://hackmd.io/_uploads/Skze3E6Tbg.png)

## Email your game to your friends

1. Setup Agentmail 

Create an account https://agentmail.to, and then create an inbox.
Get the API Key, save it in .env file under .openclaw directory. 

```bash
npx clawhub@latest install agentmail

#then restart gateway
openclaw gateway restart

#When you are ready, prompt in the chat to setup your email address before asking to send email.
```

Talk to the Openclaw chatbot, give it instructions and will finalize the setup. 
```
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

Done. :+1:  You can now text the chatbot, and you will see a new session under telegram.

## Control your web browser and Do anything!

Enable control with debugging on Chromium
```bash
/snap/bin/chromium  --remote-debugging-port=9222   --remote-debugging-address=127.0.0.1 
```

Update the openclaw.json file.
```
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

```
use the built-in browser skill to open the browser and search for nvidia
```

```
open amazon and find me the engine oil 5w-30 for my BMW
```

<iframe width="560" height="315" src="https://www.youtube.com/embed/GfxS5SkQxKw?si=gon32oqPnSrj9WAv" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>

## Podcast style, turn content into speech on webchat

Ask openclaw to install a local tts tool, like node-edge-tts.
```
can you install node-edge-tts 

#openclaw should trigger this, if not you can do it manually
#npm install node-edge-tts
```

Once it's all installed and we can play it back with mpv via the TTS. mpv is installed above, if not install it with `apt-get install mpv`
```
Try this: 
npx node-edge-tts -t "Hello from NVBot" -f /tmp/test.mp3 && mpv /tmp/test.mp3 & 
```

```
ok find today's news and play it back that way
```

Then you should save the skill to make it runs faster the next time (minimizing the discovery steps)

```
save this skill
```

Openclaw will create a skill file, which means that the next time you ask for a podcast, it will know what to do quickly. 

![Screenshot from 2026-05-14 20-19-07](https://hackmd.io/_uploads/rkJpeMVJGe.png)

This is the fully workaround to get TTS working on Webchat interface. 

If you have Telegram, you can just use the default TTS built-in skill, and should just work out of the box without using mpv. 

```
\tts on
```

This will turn on TTS, and you can see the audio files pop up as media attachment each time you talk to the agent.

https://docs.openclaw.ai/tools/tts

# Part 5 — Reference and troubleshooting

## Alternative Serving to Try Next

We can also simplify the onboarding with Ollama (given the risk I explained above). I have had lots of headaches due to timeout, or tool calling got stopped randomly! So use this if and only if you are only using it for testing or quick validations. There are workarounds on timeout but needed further investigations.

To run on Spark, you can start a quick install of the latest Ollama. Please make sure you run from this script and check the GPU is activated.

```bash
# Install latest (YOLO/FOMO way -- up to you)
curl -fsSL https://ollama.com/install.sh | sh

# or install with locked version (safe for demo)
#curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.23.1 sh


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

You should be able to see the new model in the list of available models at Openclaw. And you can revert it back to vllms with this command.

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

2. Ollama seems to always quit early or never finish the tasks when it's long. Tool calling seems to be broken, and was patched in 0.20.3 but still not good enough for Openclaw demo. Please check before switching to Ollama. 

3. Long tool calling has proven to be challenging, so when we run a demo continue to provide additional instructions like "continue working".

### Models and harness

1. Gemma 4:26b still have the issues in tool calling with openclaw, and there are times it will stop early without warning. Please plan your demo carefully when you are using Gemma 4. Will update on this thread next.
2. Qwen 3.6-35b is amazing at coding, but also takes a long while to complete the job (it seems love to make things perfect on one shot). I will recommend starting with simplier prompt with more directions, to avoid the model go all-in with a single prompt for more responsive demo.
3. nemotron3:33b model is not designed for openclaw. It is great for subagent tasks like VLMs and reasoning things in a scene or world.

Ollama is giving bad output for gemma4, and you can see in the coding example with extra space and typos.
![image](https://hackmd.io/_uploads/r1_12XtAWg.png)

### Workarounds and Findings

1. Avoid long open ended tasks. The agent does not have limits on its capabilities, thus it can go try do things impossible within some timeframes. For example, 'process 10000 images with VLM'. This will create a long running loop that may eventually failed. We do not have guardrails for this behavior yet (maybe a good use case for Nemoclaw?).


2. VLMs and multiple models. Nemotron-3-Nano-Omni got better throughput for VLM, but not as great for using as the main driver for openclaw. The workaround now is to enable Nemotron-3-Nano-Omni as subagent tasks, and ideally create custom APIs access to the serving. This it our TODO.

## Some benchmarks to consider in token/s (ollama) and tokens to answers

Prompt used: "why is the sky blue?" 
This will trigger reasoning by default.
A good starter reference.

`ollama run gemma4:26b --verbose`
```
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
```
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
```
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
```
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
