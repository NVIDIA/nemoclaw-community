# Hermes + Omni on NemoClaw

> This is the upstream walkthrough preserved for detail. For the standardized
> repo layout in `nemoclaw-community`, start with `../README.md`; paths in this
> document may still refer to the original `nemoclaw-demos` checkout.

Build a local multimodal agent on a single Linux host. By the end you'll have a browser-based demo at `http://localhost:8765` where you can drop in a video, audio file, image, or PDF and ask questions about it. The agent runs inside a sandbox with a deny-by-default network policy.

Three pieces:

- **Nemotron 3 Nano Omni** — multimodal model (video, audio, image, text, reasoning), served by NVIDIA's hosted endpoint
- **Hermes Agent** (Nous Research) — picks the right skill for each question, holds context across turns
- **NemoClaw + OpenShell** — the sandbox runtime that wraps Hermes and enforces a declarative network policy

No GPU required. The model runs in NVIDIA's cloud; everything you run locally is the agent and the sandbox.

## What the demo does

| Modality | Try this |
|---|---|
| Short video | Drop in any clip ≤ 2 min and ask "what's happening?" |
| Long video | Use `chunk-upload.sh` for anything over 2 min, then ask "give me three takeaways" |
| Audio | Drop an MP3 — Omni hears it as audio, not transcribed text |
| PDF | Drop a PDF — pages render, all go to Omni in one call |
| Image | Drop a PNG — Omni describes what it sees |
| Jargon | "Look up FP8 per-tensor scaling on Wikipedia" — hits the proxy whitelist |
| Policy | "Try to fetch google.com" — sandbox returns 403 |

All five modalities run through one skill. The agent picks the tool. The sandbox checks every outbound call.

## Prerequisites

> **macOS is not supported.** The OpenShell sandbox container image is Linux-only and dies at build step ~51/57 with a symlink error on Darwin. `scripts/start.sh` bails immediately if `uname` reports `Darwin`. Use a Linux host (Brev, DGX, or any Docker-capable Linux box).

### Ubuntu/Debian host packages

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg poppler-utils lsof python3-venv
```

`ffmpeg` provides both `ffmpeg` and `ffprobe`. The UI startup script checks these commands up front and creates a local Python virtualenv for server dependencies, which avoids Ubuntu 24.04's externally-managed Python (`PEP 668`) error.

### Other Linux distros

Use your distro's equivalent for `ffmpeg`, `poppler-utils`, `lsof`, and the Python `venv` module. RHEL/Fedora: `dnf install ffmpeg poppler-utils lsof python3` (you may need RPM Fusion or EPEL for `ffmpeg`). Arch: `pacman -S ffmpeg poppler lsof python`. Alpine: `apk add ffmpeg poppler-utils lsof python3`.

| Requirement | Details |
|---|---|
| Linux host | Brev instance, DGX, or any Docker-capable Linux. No GPU needed. macOS not supported. |
| Docker | Installed and running. |
| NVIDIA API key | Starts with `nvapi-`, with Omni access. Get one at [build.nvidia.com](https://build.nvidia.com) → API Keys. |
| `ffmpeg` / `ffprobe` | Distro package (`apt`/`dnf`/`pacman`/`apk`). Needed for video upload transcoding, the synthetic test clip, and chunking long videos. |
| `poppler-utils` | Distro package. Needed for PDF rendering (`pdftoppm`). |
| `lsof` | Distro package. Used by `start.sh` to check whether the demo port is already in use. |
| Node 20+ and `npm` | Needed to build the web UI. The NemoClaw installer auto-installs Node via nvm if missing. |
| Python 3.10+ with `venv` | For the FastAPI backend. `scripts/start.sh` creates a local `.venv` so system Python is not modified. |

> **Tested with:** `nemoclaw v0.0.31`, `openshell 0.0.36`, Node 22, Python 3.11 on Ubuntu 22.04 (Brev cloud). Versions advance frequently; `nemohermes --version`, `nemoclaw --version`, and `openshell --version` may show newer values than what's in the example output below.

---

## Quickstart (6 steps, ~6 min)

Use this if you're starting from a fresh Brev/Ubuntu box. If NemoClaw and OpenShell are already installed, skip step 1 and continue with the clone/onboard steps. The quickstart still includes one interactive step: during onboarding, choose **NVIDIA Endpoints** as the inference provider. The longer walkthrough below explains each step.

```bash
# 1. install the NemoHermes/NemoClaw + OpenShell CLIs from NVIDIA, if needed
export NEMOCLAW_AGENT=hermes
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash && source ~/.bashrc

# 2. clone this cookbook
git clone https://github.com/brevdev/nemoclaw-demos.git
cd nemoclaw-demos/hermes-omni-demo

# 3. onboard a sandbox
# interactive: choose "NVIDIA Endpoints", paste your nvapi key, pick name "my-hermes",
# pick the default Super model for now, then accept/skip optional presets
nemohermes onboard

# 4. configure the sandbox: switch to Omni, apply policy, install skills
openshell inference set --provider nvidia-prod \
    --model nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
SANDBOX=my-hermes bash scripts/setup.sh

# 5. smoke test — proves gateway → Omni works before bringing up the UI
ffmpeg -y -f lavfi -i "testsrc=duration=10:size=320x240:rate=15" \
       -f lavfi -i "sine=frequency=440:duration=10" \
       -c:v libx264 -pix_fmt yuv420p -shortest /tmp/smoke.mp4
openshell sandbox upload my-hermes /tmp/smoke.mp4 /tmp/
openshell sandbox exec -n my-hermes -- python3 \
    /sandbox/.hermes-data/workspace/omni-video-analyze.py \
    /tmp/smoke.mp4 "what is in this video?"
# Expected: a description of the test pattern + token count line.
# If this fails, fix the gateway/network issue here — the UI won't help.

# 6. build the UI and start the server
SANDBOX=my-hermes bash scripts/start.sh
```

Open `http://localhost:8765`. Drop a video into the chat. Ask a question.

---

## The walkthrough

Same flow as the Quickstart, broken into parts with the manual commands and what you should see at each step. The wrapper scripts are pointed out where they apply — they're shortcuts, not requirements.

### Part 1 — Install NemoHermes / NemoClaw

```bash
export NEMOCLAW_AGENT=hermes
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc
```

Verify:

```bash
nemohermes --version
nemoclaw --version
openshell --version
```

Expected:

```
nemohermes v0.x.y
nemoclaw v0.x.y
openshell 0.x.y
```

#### Installing over SSH (Brev / DGX / any non-interactive shell)

The installer prints a third-party-software license prompt and reads from `/dev/tty`, so a bare `curl | bash` over a non-interactive SSH session silently exits 1. Pass `--yes-i-accept-third-party-software` to bypass the prompt:

```bash
export NEMOCLAW_AGENT=hermes
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash -s -- --yes-i-accept-third-party-software
source ~/.bashrc
```

Use this form if you're running over `ssh -T`, `tmux`, `cron`, `systemd`, or any other context without an attached TTY.

### Part 2 — Onboard a sandbox

This step is interactive. You answer the prompts. **Do this manually — there is no script for it.** The choices below match the rest of the guide.

```bash
nemohermes onboard
```

The wizard prompts vary by NemoClaw version (recent versions added Brave web-search and messaging-channel prompts on top of the original five). Rather than listing every prompt — which goes stale between releases — here are **only the answers that matter for this cookbook**:

| Prompt asks about… | Answer |
|---|---|
| Inference provider | **NVIDIA Endpoints** (the option whose label says "NVIDIA Endpoints") |
| API key | Paste your `nvapi-...` key |
| Model | **Nemotron 3 Super 120B** — you'll swap this to Omni in Part 3 |
| Sandbox name | `my-hermes` |

For every *other* prompt the wizard shows (Brave Search API key, Telegram/Discord messaging channels, policy preset selection, etc.), **accept the default by hitting Enter or saying "no"/"skip"**. None of them are required for the demo, and you can wire them up later if you want.

The wizard takes ~1–2 min depending on how many optional integrations you skip. At the end you'll see:

```
✓ Sandbox 'my-hermes' created
✓ Hermes Agent gateway launched inside sandbox
```

Verify the sandbox is running:

```bash
nemohermes my-hermes status
```

Expected (truncated):

```
Sandbox: my-hermes
  Model:    nvidia/nemotron-3-super-120b-a12b
  Phase:    Ready
  Agent:    Hermes Agent v2026.4.8
```

### Part 3 — Switch the gateway to Omni

The onboarding wizard only offers Super 120B. We need Omni so Hermes can handle video, audio, and images. Three things to update:

```bash
# 1. Runtime route — this is what actually executes model calls
openshell inference set \
    --provider nvidia-prod \
    --model nvidia/nemotron-3-nano-omni-30b-a3b-reasoning

# 2. Display label — updates the Hermes TUI banner
openshell sandbox exec -n my-hermes -- bash -c \
    "sed -i 's|nvidia/nemotron-3-super-120b-a12b|nvidia/nemotron-3-nano-omni-30b-a3b-reasoning|' \
     /sandbox/.hermes-data/config.yaml"

# 3. Display label — updates `nemoclaw list`
python3 -c "
import json, pathlib, sys
p = pathlib.Path.home() / '.nemoclaw' / 'sandboxes.json'
if not p.exists():
    sys.exit(f'host metadata not found at {p}; skipping (this is fine if you onboarded with a different NemoClaw layout)')
d = json.load(open(p))
sandboxes = d.get('sandboxes', {})
if 'my-hermes' not in sandboxes:
    sys.exit(f'no sandbox named my-hermes in {p}; available: {sorted(sandboxes)}. Substitute the right name.')
sandboxes['my-hermes']['model'] = 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning'
json.dump(d, open(p, 'w'), indent=4)
print('updated', p)
"
```

Verify:

```bash
openshell inference get
```

Expected:

```
Gateway inference:
  Provider: nvidia-prod
  Model:    nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
```

```bash
nemoclaw list
```

Expected:

```
my-hermes
  model: nvidia/nemotron-3-nano-omni-30b-a3b-reasoning  provider: nvidia-prod
```

Step 1 changes the runtime behavior — it points the gateway at the Omni model, determining which model the sandbox actually calls. If you skip step 1, the demo is still using the model selected during onboarding. Steps 2 and 3 only keep labels in sync: if you run step 1 but skip either label update, Omni may be running correctly while the Hermes TUI banner or `nemoclaw list` still shows the old Super model.

### Part 4 — Clone the cookbook, set the SANDBOX env var

```bash
git clone https://github.com/brevdev/nemoclaw-demos.git
cd nemoclaw-demos/hermes-omni-demo
export SANDBOX=my-hermes
```

The NVIDIA API key only needs to exist on the host where you ran `nemohermes onboard`. It lives in the OpenShell gateway's credential store. Scripts inside the sandbox reach Omni through the gateway and never see the key.

### Part 5 — Configure the sandbox

This part has a one-shot wrapper. Both paths produce the same end state.

**Shortcut:**

```bash
bash scripts/setup.sh
```

**Or do it by hand**, which is what the script does, in order:

1. Apply the Wikipedia + Dictionary policy blocks (so the jargon-lookup skill can do its job):

```bash
openshell policy get $SANDBOX --full > /tmp/raw-policy.txt
awk '/^---$/{seen=1; next} seen' /tmp/raw-policy.txt > /tmp/current-policy.yaml
cat policy/hermes-omni-lookup.yaml >> /tmp/current-policy.yaml
openshell policy set --policy /tmp/current-policy.yaml $SANDBOX
```

Expected:

```
✓ Policy version 7 submitted (hash: ...)
✓ Policy version 7 loaded (active version: 7)
```

2. Install the two skills:

```bash
nemohermes $SANDBOX skill install skills/video-analyze
nemohermes $SANDBOX skill install skills/jargon-lookup
```

Expected:

```
✓ Skill 'video-analyze' installed
✓ Skill 'jargon-lookup' installed
```

3. Upload the scripts and the agent's identity file:

```bash
openshell sandbox upload $SANDBOX scripts/omni-video-analyze.py /sandbox/.hermes-data/workspace/
openshell sandbox upload $SANDBOX scripts/lookup-jargon.py /sandbox/.hermes-data/workspace/
openshell sandbox exec -n $SANDBOX -- chmod +x \
    /sandbox/.hermes-data/workspace/omni-video-analyze.py \
    /sandbox/.hermes-data/workspace/lookup-jargon.py

# SOUL.md goes in two places — Hermes reads from both
openshell sandbox upload $SANDBOX memories/SOUL.md /sandbox/.hermes-data/memories/
openshell sandbox upload $SANDBOX memories/SOUL.md /sandbox/.hermes-data/
```

Verify the skills:

```bash
# Rich tables need a non-trivial width; bare `openshell sandbox exec` can report COLUMNS=1
# and print one character per line. Force a width (and height) for readable output.
openshell sandbox exec -n $SANDBOX -- env COLUMNS=120 LINES=40 hermes skills list
```

Expected:

```
              Installed Skills
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┓
┃ Name          ┃ Category ┃ Source ┃ Trust ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━┩
│ jargon-lookup │          │ local  │ local │
│ video-analyze │          │ local  │ local │
└───────────────┴──────────┴────────┴───────┘
```

### Part 6 — Smoke test

Make sure Omni is reachable from inside the sandbox before you bring up the UI.

```bash
ffmpeg -y -f lavfi -i "testsrc=duration=20:size=320x240:rate=15" \
    -f lavfi -i "sine=frequency=440:duration=20" \
    -c:v libx264 -pix_fmt yuv420p -shortest \
    /tmp/test-video.mp4

openshell sandbox upload $SANDBOX /tmp/test-video.mp4 /tmp/

openshell sandbox exec -n $SANDBOX -- python3 \
    /sandbox/.hermes-data/workspace/omni-video-analyze.py \
    /tmp/test-video.mp4 "What is in this video?"
```

Expected (last lines):

```
--- Omni Analysis ---
The video displays a television test pattern (specifically SMPTE color bars)
with a horizontal rainbow gradient bar running across the lower portion.
Inside a black box on the right side of the screen, a pixelated white number
counts up sequentially from 1 to 20.

[4176 tokens, 351KB payload]
```

If you see this, the gateway → Omni path is healthy.

### Part 7 — Bring up the web UI

**Shortcut:**

```bash
bash scripts/start.sh
```

The script checks the sandbox is Ready, verifies host helpers (`ffmpeg`, `ffprobe`, `pdftoppm`, `lsof`), builds the UI if `ui/dist` is missing, creates a local Python virtualenv at `.venv`, installs the server's Python deps there, and runs uvicorn on port 8765. The same uvicorn serves both the API (`/api/*`) and the built React app (`/`).

You should see:

```
→ sandbox: my-hermes
→ url:     http://localhost:8765

✓ sandbox Ready
✓ UI built at /path/to/ui/dist
✓ server deps ready

→ launching server
  open http://localhost:8765 in your browser
  Ctrl-C to stop

INFO:     Uvicorn running on http://0.0.0.0:8765
```

**Or by hand:**

```bash
# install UI deps and build the static bundle (~30s)
cd ui
npm install
npm run build
cd ..

# install server deps in a local venv (avoids system Python / PEP 668)
python3 -m venv .venv
. .venv/bin/activate
pip install -r server/requirements.txt

# run the server
cd server
SANDBOX=my-hermes python -m uvicorn server:app --host 0.0.0.0 --port 8765
```

Open `http://localhost:8765`. You should see:

- A header with a "Live · Nemotron 3 Nano Omni 30B" pill
- A flow diagram (You → Sandbox → Omni)
- A chat input at the bottom
- A bottom ticker showing live policy events as you exercise the agent

### Part 8 — Use the demo

In the browser:

1. **Drop a short video** onto the chat. Type *"What's happening in this clip?"*. Watch the flow diagram light up Hermes → Sandbox → Omni. The answer streams back.
2. **Ask a follow-up** that wasn't in the original answer ("what colors are in it?"). The diagram lights again — Hermes re-runs the script with the new question instead of answering from memory.
3. **Drop a PDF** (it gets rendered to per-page PNGs on the host, uploaded as a directory, and sent to Omni as a multi-image payload). Ask *"what's the main argument?"*.
4. **Click the mic icon** and speak a question. The browser records audio, the host transcodes it, Omni hears it as audio.
5. **Open the Memory drawer** to see the session log — every prompt, tool call, and attachment is indexed with full-text search.
6. **Open the Policy drawer** and click *Run Security Check*. Six destinations are tested; five blocked, one allowed. Then flip the `nvidia.com` toggle off and re-run — the policy hot-swaps in ~5 seconds.

### Part 9 — Stop the demo

If `start.sh` is in the foreground, hit `Ctrl-C`.

If you backgrounded it (e.g. via `tmux` or `&`):

```bash
bash scripts/stop.sh
```

Expected:

```
→ stopping process(es) on port 8765: 1215884
✓ stopped
```

---

## Long videos

The single-call path tops out at ~9 MB after base64 encoding (gateway body cap), about 2 min of 480p video. For longer content, this cookbook ships a host-side helper that splits the video into chunks, uploads them as a directory, and lets the same skill loop over the chunks and synthesize one answer.

```bash
bash scripts/chunk-upload.sh /path/to/long-talk.mp4
# default chunks at 120s; pass a second arg for different segment length:
#   bash scripts/chunk-upload.sh /path/to/long-talk.mp4 90
```

Expected:

```
→ probing /path/to/long-talk.mp4
  duration: 397.184000s, chunking into 120s segments at 480p
→ writing chunks.json manifest
  4 chunks, 397.3s total, 7.4 MB on disk
→ uploading /tmp/long-talk-chunks into sandbox 'my-hermes'
✓ Upload complete
```

In the chat, paste:

```
Analyze the video at /tmp/long-talk-chunks — give me three takeaways.
```

The skill detects "directory of MP4 files" and runs Omni once per chunk with absolute timestamps in each prompt, then makes one synthesis call across all the chunk summaries. Cost is linear in source video length — roughly 11K tokens per minute of source.

## PDFs (also via host helper)

```bash
bash scripts/pdf-upload.sh /path/to/document.pdf
```

Expected:

```
→ rendering /path/to/document.pdf → /tmp/document-pages (150 dpi)
  12 pages, 8 MB on disk
→ uploading /tmp/document-pages into sandbox 'my-hermes'
✓ Upload complete
```

In the chat:

```
Read the document at /tmp/document-pages — what's the main argument?
```

Omni's per-request image cap is 8 images. The skill auto-batches PDFs longer than that — the same chunk-and-synthesize pattern as long videos. For an 8-page PDF, the skill makes one call. For 30 pages, it makes 4 batch calls plus one synthesis call. Cost is linear in page count (~few thousand tokens per page).

## See the policy block

In a second terminal:

```bash
openshell logs my-hermes --tail --source sandbox | grep --line-buffered -E "ALLOWED|DENIED"
```

Then in the chat:

```
Try to fetch https://google.com with curl so we can see NemoClaw block it.
```

In the logs terminal you'll see something like:

```
[OCSF] NET:OPEN [MED] DENIED /usr/bin/curl -> google.com:443 [policy:- engine:opa]
```

The agent reports the block in plain language. Every call to `integrate.api.nvidia.com` is `ALLOWED`; everything else is `DENIED`.

---

## Day-2 operations

### After a host reboot

```bash
nemohermes my-hermes status                # confirm Phase: Ready
SANDBOX=my-hermes bash scripts/start.sh  # bring the UI back up
```

If `Phase` is not `Ready`, the openshell gateway likely needs a kick:

```bash
openshell gateway status
openshell gateway start  # if it's not running
```

### Add a new skill

Drop a new directory under `skills/` with its own `SKILL.md`, then:

```bash
nemohermes $SANDBOX skill install skills/your-new-skill
openshell sandbox exec -n $SANDBOX -- env COLUMNS=120 LINES=40 hermes skills list
```

Restart `hermes chat` (or refresh the web UI) so Hermes picks up the new skill.

### Hermes TUI for debugging

The web UI is the demo path. The TUI is for poking at things:

```bash
nemohermes my-hermes connect
hermes chat
```

You're now in the sandbox shell. Hermes runs in its TUI; type questions, watch tool calls, exit with `/exit` or `Ctrl-D`.

### Snapshots and starting over

```bash
# snapshot the sandbox before a destructive change
nemohermes my-hermes snapshot create

# nuke and start over
nemohermes my-hermes destroy --yes
nemohermes onboard
# repeat Parts 3-5
```

### After `nemohermes rebuild`

`nemohermes <name> rebuild` is **destructive to in-sandbox state**: SOUL.md, the uploaded scripts, and any custom policy blocks are wiped and replaced with the defaults from the new sandbox image. After every rebuild, re-run the configuration step:

```bash
SANDBOX=my-hermes bash scripts/setup.sh
```

`setup.sh` re-applies the policy, re-installs both skills, re-uploads the scripts and SOUL.md, fixes the display labels, and verifies SOUL.md is visible to Hermes through `/sandbox/.hermes/SOUL.md`. If any step silently failed in the past, the verification step at the end now fails loudly — you won't be left with green checks and a broken sandbox.

> **Why the rebuild wipes state:** the in-sandbox filesystem under `/sandbox/.hermes-data/` lives inside the sandbox container image, not on the host. A rebuild is a destroy-then-recreate of that image. There's no in-place "patch" mode that preserves your customizations — the cookbook treats rebuild as an "I want a clean state" operation followed by re-applying setup.sh.

> **Don't rebuild without `NVIDIA_API_KEY` in env**: if the credential isn't reachable to the rebuild step, the recreate phase fails AFTER the destroy already ran, leaving you with no sandbox. Always `export NVIDIA_API_KEY=nvapi-...` before `nemohermes rebuild`.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `hermes skills list` prints one letter per line (unreadable table) | Hermes uses Rich; `openshell sandbox exec` often exposes width 1. Run: `openshell sandbox exec -n $SANDBOX -- env COLUMNS=120 LINES=40 hermes skills list`. Or run `hermes skills list` after `nemohermes $SANDBOX connect` in a normal shell. |
| UI shows "Hermes produced no visible answer (exit 0)" | Run the skill directly to see the real error: `openshell sandbox exec -n my-hermes -- python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /tmp/<latest-upload> "test"` (find the upload with `openshell sandbox exec -n my-hermes -- ls -lt /tmp \| head -5`). The error message in the UI now includes the last 20 lines of Hermes output, which will tell you whether it's a payload-size, model-routing, or token-budget issue. |
| UI shows "Hermes produced no visible answer (exit 1)" with no detail | Hermes itself crashed. Check that `/sandbox/.hermes/SOUL.md` exists and is readable (it's a symlink to `/sandbox/.hermes-data/memories/SOUL.md` in current sandbox images). Re-run `bash scripts/setup.sh` — its final step verifies SOUL is visible to Hermes. |
| TUI banner / `nemoclaw list` shows Super 120B even after the swap | Display labels weren't updated. Run `openshell inference get` first; that shows the actual runtime model. If it shows Omni, re-run the two label-update commands in Part 3 so the TUI and `nemoclaw list` match runtime behavior. |
| `SSL EOF occurred in violation of protocol` from `omni-video-analyze.py` | Payload exceeded ~9 MB. Use `chunk-upload.sh` (Long Videos section), or trim with `ffmpeg -i big.mp4 -t 120 -c copy small.mp4`. |
| `'NoneType' object has no attribute 'strip'` mid-chunked-run | Old script. Re-upload the v3 from `scripts/omni-video-analyze.py`. |
| `Connection refused` on `inference.local` from inside the sandbox | Gateway lost its route. Re-run `openshell inference set ...` from Part 3. |
| Hermes says "I can't browse the web" when asked to look up a definition | SOUL.md didn't load or there are two stale copies. Re-run the two SOUL upload commands in Part 5, restart `hermes chat`. |
| `exit 126` when Hermes runs a script | Lost the executable bit. `openshell sandbox exec -n $SANDBOX -- chmod +x /sandbox/.hermes-data/workspace/*.py`. |
| Hermes hallucinates a name for the speaker on a long video | Omni has no face/voice grounding. Open recordings with a self-introduction, or add to the prompt: `Refer to the speaker as "the narrator" — do not assign a name unless they introduce themselves`. |
| `start.sh` says sandbox is not Ready | `nemohermes my-hermes status` to see the actual phase. If `Pending`, wait 30s and retry. If `Failed`, check `nemohermes my-hermes logs`. |
| Port 8765 already in use when `start.sh` runs | Another server is already on that port. `bash scripts/stop.sh` to kill it, or set `PORT=8766` and re-run. |
| UI loads but `/api/*` calls fail | The server didn't start cleanly. Check the terminal where `start.sh` is running — uvicorn errors will be visible there. |
| `openshell sandbox upload DEST` made a directory instead of putting the file | Trailing slash matters. `upload SRC /tmp/` puts the file in `/tmp/`. `upload SRC /tmp` makes a directory called `/tmp`. |
| `npm: command not found` when running `start.sh` over SSH or systemd | nvm is sourced from `~/.bashrc` only, which non-login shells don't read. The script now sources `~/.nvm/nvm.sh` at the top — make sure you're running the latest version of `scripts/start.sh`. |
| `curl \| bash` install hangs or exits 1 over SSH | License prompt needs `/dev/tty`. Use `bash -s -- --yes-i-accept-third-party-software` (see Part 1). |
| Hermes returns the previous file's analysis when you upload a new one | Multi-attachment session bleed. The UI now sends `new_session: true` automatically when a different file path is dropped — make sure you're running the latest UI build (`bash scripts/start.sh` will rebuild). If it still happens, click "New chat" before uploading. |
| `start.sh` exits with "macOS is not supported" | The sandbox image is Linux-only. Run on Brev / DGX / any Docker-capable Linux box. |
| `start.sh` exits with "Docker has a broken proxy set: HTTP_PROXY=gcp/" | Known broken Brev image. Run the override-conf snippet `start.sh` prints, then re-run. The proxy env breaks Docker registry pulls silently — not specific to this cookbook. |
| Hermes loses its skills/SOUL after `nemohermes rebuild` | Expected — rebuild wipes the in-sandbox filesystem. Re-run `SANDBOX=my-hermes bash scripts/setup.sh` to redeploy. See "After `nemohermes rebuild`" in Day-2 ops. |
| `nemohermes rebuild` exits with "requires local env var 'NVIDIA_API_KEY'" and the sandbox is gone | Rebuild ran the destroy phase and then failed at recreate. `export NVIDIA_API_KEY=nvapi-...` and run `nemohermes onboard` to recreate from scratch. |

## Tailing logs

```bash
# OCSF policy verdicts (most useful for debugging policy)
openshell logs my-hermes --tail --source sandbox | grep --line-buffered -E "ALLOWED|DENIED"

# Gateway-side events (tunnel, command exec)
openshell logs my-hermes --tail --source gateway
```

## Repo layout

```
hermes-omni-demo/
├── hermes-omni-guide.md         this file
├── policy/
│   └── hermes-omni-lookup.yaml  Wikipedia + Free Dictionary policy blocks
├── memories/
│   └── SOUL.md                  Hermes identity / steering
├── skills/
│   ├── video-analyze/SKILL.md   handles video, audio, image, PDF-pages, chunked dirs
│   └── jargon-lookup/SKILL.md   Wikipedia + Free Dictionary lookup
├── scripts/
│   ├── omni-video-analyze.py    the multimodal skill — runs inside the sandbox
│   ├── lookup-jargon.py         the jargon skill — runs inside the sandbox
│   ├── chunk-upload.sh          host helper — long video → chunks dir → upload
│   ├── pdf-upload.sh            host helper — PDF → page PNGs → upload
│   ├── setup.sh                 wraps Part 5 (policy + skills + scripts upload)
│   ├── start.sh                 build UI + run server on port 8765
│   └── stop.sh                  kill whatever's on the demo port
├── server/                      FastAPI backend
│   ├── server.py
│   └── requirements.txt
└── ui/                          React + Vite + Tailwind frontend
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── App.tsx
        ├── api/client.ts
        ├── components/{ChatPanel,FlowDiagram,PolicyDrawer,...}.tsx
        └── styles/index.css
```
