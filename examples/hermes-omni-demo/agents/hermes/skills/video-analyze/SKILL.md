---
name: video-analyze
description: Analyze video files using Nemotron 3 Nano Omni multimodal model. Handles a single video, image, audio file, a directory of PDF-rendered pages, OR a directory of pre-chunked video segments for long videos. Use whenever the user provides a video path and wants it analyzed, described, summarized, or transcribed.
version: 3.2.0
metadata:
  hermes:
    tags: [video, omni, multimodal, transcript, analysis, nemotron, long-video, chunked]
---

# Video Analysis with Nemotron 3 Nano Omni

Analyze videos, audio, images, and documents using NVIDIA's Nemotron 3 Nano Omni multimodal model.

## Inputs the skill accepts

| Input | What happens |
|---|---|
| `*.mp4 / .mov / .webm` | One Omni call with the full video |
| `*.mp3 / .wav / .m4a` | One Omni call with audio |
| `*.png / .jpg / .webp` | One Omni call with the image |
| Directory of PNGs (e.g. `*.pdf-pages/`) | If ≤ 8 pages, one Omni call. If > 8 pages, batched (8 pages per call) + synthesis — Omni's per-request image cap is 8. |
| **Directory of MP4 chunks (e.g. `*-chunks/`)** | **Per-chunk Omni call + final synthesis** (medium-video path, 2-30 min) |
| **Long-video bundle dir (e.g. `*-longvideo/` containing `audio.mp3` + `frames/` + `manifest.json`)** | **Transcribe audio + send full transcript with 8 keyframes + user's question in one Omni call** (long-video path, > 30 min) |

The chunked directory path expects `chunk_001.mp4`, `chunk_002.mp4`, … and a `chunks.json` manifest produced by the host-side `chunk-upload.sh` helper. If `chunks.json` is missing, the skill falls back to probing each chunk's duration to derive timestamps.

## When to use this skill

- User provides a video path and asks to analyze, describe, or summarize it
- User asks "what's happening in this video", "transcribe the audio", "what does the speaker say"
- **User provides a path ending in `-chunks` or any directory containing video files** → chunked long-video flow
- User wants a plain-English or structured analysis of video content

## CRITICAL — run the script via the `terminal` tool, NOT `execute_code`

The `execute_code` tool runs in an isolated Python environment without network access. Calling the script from there will fail. Always use the terminal tool.

## How to invoke

### Mode 1: Analyze (default)

**Single video / audio / image / pages dir:**
```bash
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /tmp/upload-X.mp4
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /tmp/upload-X.mp4 "Custom question"
```

**Long video (pre-chunked directory):**
```bash
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /tmp/long-video-chunks
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /tmp/long-video-chunks "What's the speaker's main argument?"
```

When given a chunk directory, the skill loops over each segment with the user's question, then runs ONE final synthesis call across all segment summaries to produce the user-facing answer. Cost scales linearly with video length.

### Mode 2: Transcript (single input only)

```bash
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /tmp/upload-X.mp4 --mode transcript
```

Transcript output:
```json
{
  "video": "/tmp/upload-X.mp4",
  "duration": "3:05",
  "transcript": [
    {"timestamp": "0:03", "speaker": "Professor", "text": "Today we will discuss..."},
    {"timestamp": "0:15", "speaker": "Professor", "text": "A unit vector is..."}
  ]
}
```

Transcript mode does NOT support chunked directories — it requires a single video file.

## Follow-up questions

Each call to `omni-video-analyze.py` re-sends the video (or chunks) to Omni. If the user asks a follow-up, **re-run the script with the new question**. Do not answer from memory of a previous narrow answer.

## Long-video workflow (host-side preparation)

For videos longer than ~2 min, ask the user (or run yourself if you have host shell access) to chunk + upload first using the host helper:

```bash
chunk-upload.sh /path/to/long-video.mp4
# → uploads /tmp/long-video-chunks/ into the sandbox
```

Then invoke the skill with the printed sandbox path.

## Tips

- For specific portions, say so in the prompt ("focus on the conclusion", "describe only the first minute")
- Custom prompts only work in analyze mode (not transcript mode)
- Single-video payload limit: ~9 MB after base64 (gateway body cap). Beyond that, use the chunked workflow.
- Per-chunk analyses use a small token budget (1024) so the synthesis pass has room to work; the synthesis call gets 4096
