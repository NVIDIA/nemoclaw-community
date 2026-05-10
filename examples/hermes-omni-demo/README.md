![NVIDIA](../assets/nvidia_header.png)

# hermes-omni-demo: Hermes + Nemotron Omni

A browser-based multimodal demo for an existing Hermes sandbox. Drop in a video,
audio file, image, or PDF, ask questions about it, and watch the host UI route
the prepared artifact into the sandbox for Nemotron 3 Nano Omni analysis.

## What This Demonstrates

- Hermes skill use for video, audio, image, PDF, and long-video analysis.
- A host-side FastAPI/Vite UI that talks to the sandbox through OpenShell.
- A narrow policy extension for Wikipedia and Free Dictionary jargon lookup.
- Optional Phoenix telemetry infrastructure for NemoFlow-enabled Hermes images.

## Structure

| Path | Purpose |
|---|---|
| `agents/hermes/` | SOUL instructions, Hermes skills, and workspace scripts uploaded into the sandbox. |
| `app/` | Host-side FastAPI backend and Vite/React UI. |
| `policy.yaml` | Policy blocks appended to the active sandbox policy. |
| `extras/` | Optional Phoenix host service. |
| `scripts/` | Setup, UI start/stop, upload helpers, and smoke test. |
| `docs/` | Deeper notes, including upstream walkthrough and telemetry/UI details. |

## Requirements

- Linux host with Docker and a running Hermes sandbox.
- `nemohermes`, `nemoclaw`, and `openshell` CLIs.
- NVIDIA API key with access to `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`.
- Host tools: `ffmpeg`, `ffprobe`, `poppler-utils` (`pdftoppm`), `lsof`, Python 3.10+ with `venv`, Node 20+ with `npm`.

## Quickstart

Create and switch an existing Hermes sandbox to Omni:

```bash
nemohermes onboard
openshell inference set --provider nvidia-prod \
  --model nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
```

Configure the example:

```bash
cd examples/hermes-omni-demo
cp .env.example .env
# edit SANDBOX if you did not use my-hermes
bash scripts/setup.sh
```

Smoke-test the Omni path:

```bash
bash scripts/verify.sh
```

Start the UI:

```bash
bash scripts/start.sh
```

Open `http://localhost:8765`.

## Optional Phoenix

```bash
bash scripts/00-host-services.sh
```

Set `PHOENIX_COLLECTOR_ENDPOINT` and, optionally, `NEMO_FLOW_PROJECT_NAME` in
`.env` if your Hermes image includes NemoFlow/OpenInference instrumentation.
The default project name is `hermes-omni-demo`. See
[docs/telemetry-and-ui.md](docs/telemetry-and-ui.md).

## Common Tasks

Chunk and upload a longer video:

```bash
SANDBOX=my-hermes bash scripts/chunk-upload.sh /path/to/long-video.mp4
```

Render and upload a PDF:

```bash
SANDBOX=my-hermes bash scripts/pdf-upload.sh /path/to/document.pdf
```

Stop the UI server:

```bash
bash scripts/stop.sh
```
