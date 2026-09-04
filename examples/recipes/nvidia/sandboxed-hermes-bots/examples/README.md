# Two more bots: one that can see, one that can watch video

The default swarm is two text-only bots. These two are what we added when a
colleague asked whether the example could do more than text. You don't need them.
They're here because the way they work is the point of the whole repository, made
visible: only one bot's model accepts images, only one bot's egress reaches
the video model, and everyone else gets there by asking in plain language
across a sandbox boundary.

| Bot | What it can do that the others can't | What it needs |
|---|---|---|
| `nemoclaw-vision` | its model accepts images; a picture attached in Desktop reaches it as pixels | a vision-capable model on your endpoint |
| `nemoclaw-vss` | watches a video clip through NVIDIA RT-VLM and reports timestamped findings | an RT-VLM container it is allowed to reach |

Everything in this directory is picked up by name. `swarm add nemoclaw-vision`
finds `examples/souls/nemoclaw-vision.md`; `swarm add nemoclaw-vss` finds its
soul, `examples/policies/nemoclaw-vss.yaml`, `examples/plugins/vss/`,
`examples/skills/vss-video/`, and the clips in `examples/videos/`. Nothing
here touches the two default bots.

## The vision bot

Three steps. Same endpoint and key as the other bots; only the model differs.

**1. Name the model.** Uncomment these two lines in `swarm.env`. The second
one matters: Hermes strips image parts before they reach any model it can't
find on models.dev, which is every model behind a custom endpoint, so a
vision model has to be declared. Without it the bot says "I cannot see the
attached image" and means it.

```bash
INFERENCE_MODEL_NEMOCLAW_VISION=nvidia/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
INFERENCE_VISION_NEMOCLAW_VISION=on
```

**2. Add the bot.** Creates the sandbox, meshes it with the others, and tells
every other bot's soul that this one can see.

```bash
./swarm add nemoclaw-vision
```

**3. Try it.** Same path Desktop uses.

```bash
hermes -p nemoclaw-vision chat --image photo.jpg -q "What is in this picture?"
```

Any model that takes `image_url` parts and calls tools will do. On the NVIDIA
inference API we tested `nemotron-3-nano-omni-30b-a3b-reasoning` (works; it is
a reasoning model, keep `INFERENCE_MAX_TOKENS` at 8192 or the answer ends up
in the reasoning field). `nemotron-nano-12b-v2-vl` sees images but rejects
`tool_choice: auto`, so it cannot be a bot.

## The VSS bot

The bot is text-only. What it has that the others don't is two tools,
`vss_describe_video` and `vss_ask_video`, that put a clip in front of NVIDIA
RT-VLM and return text, plus a skill that says when to use which. RT-VLM is
the vision model from the [Video Search and Summarization blueprint](https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization);
we run only that container, not the full blueprint.

Seven steps, on the host with the GPU. One container, one GPU, an NGC key
for the model weights.

**1. Store your NGC key.** Prompts with echo off, saves mode 600. It is only
ever read by `docker compose` on the host; no sandbox sees it.

```bash
./swarm key vss
```

**2. Make the RT-VLM config.** The defaults bind to the OpenShell bridge
address on GPU 1. Edit `VSS_GPU` if that is not the free one.

```bash
cp examples/vss/.env.example examples/vss/.env
```

**3. Start RT-VLM.** The image is public and pinned by digest to the build we
tested. The first start downloads about 16 GB of model weights with your NGC
key into a named Docker volume, 10 to 20 minutes. The container gets the key,
one GPU, host IPC, and the bridge port; read `compose.yml` before you run it.

```bash
NGC_API_KEY=$(cat ~/.secrets/ngc.key) docker compose -f examples/vss/compose.yml up -d
```

**4. Wait for it.** Ready when this prints the model name. It binds to the
bridge address, not `0.0.0.0`, so sandboxes can reach it if their policy
says so and nothing off the host can.

```bash
curl -s http://172.18.0.1:8018/v1/models | jq -r '.data[].id'
```

**5. Tell swarm where it is.** Uncomment this line in `swarm.env`.

```bash
VSS_BASE_URL=http://host.openshell.internal:8018
```

**6. Add the bot.** Installs the two tools and the skill into that one
sandbox, applies a policy that allows egress to the port in `VSS_BASE_URL` on
the bridge and nothing else, copies the clips from `examples/videos/` to
`/sandbox/videos`, and updates the other bots so they know a teammate can
watch video. Their policies do not change; `curl` to that port from the
reviewer's sandbox gets a 403. If you changed `VSS_PORT` in step 2, use the
same port in step 5; the policy is rendered from it.

```bash
./swarm add nemoclaw-vss
```

**7. Try it.**

```bash
hermes -p nemoclaw-vss chat -q "What happens in forklift-training.mp4?"
```

Your own footage, three ways:

- **Drop it in the chat.** Drag a clip into any bot's Desktop chat and ask.
  Desktop stages the file on the host; a small host-side plugin (installed in
  every bot's shim when a vss bot exists) uploads it into the vss sandbox's
  `/sandbox/videos` before the turn is forwarded and tells the bot the name.
  So `what happens in this clip?` with `dock-inspection.mp4` attached
  works, from the reviewer or anyone else. Videos only, 200 MB cap, one
  target sandbox, and the file's bytes are never read on the host.
- **Ship it with the bot.** Put files in `examples/videos/` (or point
  `VSS_VIDEOS_DIR` elsewhere) and run `./swarm up`.
- **Link it.** Give the bot an `http(s)` URL the RT-VLM container can fetch.

Clips up to about a minute and 40 MB travel to RT-VLM inline; longer ones
need a URL.

## The demonstration

Make a group chat with `nemoclaw-reviewer`, `nemoclaw-vision`, and
`nemoclaw-vss`. Both prompts go to the reviewer, the bot that can neither see
nor watch, because the moment worth showing is a bot saying so and asking a
teammate that can.

**Video.** The vss bot watches the clip and answers with timestamps; the
reviewer relays them with attribution and adds its own read. About 20 seconds.

```
@nemoclaw-reviewer what happens in warehouse-ppe.mp4? Ask nemoclaw-vss, then give me your security read.
```

**Image.** Attach any photo (the paperclip in the composer), then ask. The
reviewer receives the image but its model cannot read it. Its soul tells it to
ask the vision bot with `with_images` set, which sends the picture along with
the question; the tool result says how many images went. The reviewer writes
its answer from what comes back. 20 to 40 seconds.

```
@nemoclaw-reviewer what safety issues do you see in this photo?
```

**Your own video.** Drag a clip into the chat, then ask. The clip lands in the
vss sandbox before anyone reads the message; the reviewer asks vss about it by
name. Same 20 seconds plus the upload.

```
@nemoclaw-reviewer what happens in this clip?
```

Three bots, three sandboxes, two handoffs across the boundary. The image
reaches the vision bot because the reviewer chose to send it on that one call;
`message_teammate` forwards nothing unless asked. The video reaches the vss
bot's sandbox as a file, and only the vss bot's policy reaches RT-VLM.

We ran each of these three times in a row through the same path Desktop uses
before writing this section, reading the tool trace in every sandbox each
time. The traps we hit on the way, and what fixed them, are in
[docs/troubleshooting.md](../docs/troubleshooting.md#multimodal-handoffs).

## What's here

```
souls/nemoclaw-vision.md      the role
souls/nemoclaw-vss.md         the role
policies/nemoclaw-vss.yaml    egress to RT-VLM on the bridge
plugins/vss/                  vss_describe_video, vss_ask_video
skills/vss-video/SKILL.md     how and when to use them
vss/compose.yml, .env.example RT-VLM standalone
videos/                       two public-domain clips + LICENSES.md
```
