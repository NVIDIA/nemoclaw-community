#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Nemotron Omni video analysis — single video, single image, audio, PDF-pages, OR
a directory of pre-chunked MP4 segments for long videos.

Modes:
    analyze     Describe what's happening (default)
    transcript  Extract audio captions as JSON

Backwards-compatible inputs:
    .mp4 / .mov / .webm     → one video_url call (current behavior)
    .mp3 / .wav / .m4a      → one input_audio call
    .png / .jpg / .webp     → one image_url call
    directory of PNGs       → multi-image_url call (PDF pages)
    directory of MP4s       → NEW: per-chunk video_url calls + synthesis

Chunk directories are produced by the host-side chunk-upload.sh helper. Each
directory should contain chunk_001.mp4, chunk_002.mp4, ... and a chunks.json
manifest with start/end times for each segment. If chunks.json is missing the
script falls back to assuming sequential chunks with no time metadata.

Usage:
    python3 omni-video-analyze.py /path/to/video.mp4
    python3 omni-video-analyze.py /path/to/video.mp4 "Custom question"
    python3 omni-video-analyze.py /path/to/video.mp4 --mode transcript
    python3 omni-video-analyze.py /tmp/long-video-chunks    # NEW chunked path
    python3 omni-video-analyze.py /tmp/long-video-chunks "What's the speaker's main argument?"
"""
import sys, json, base64, urllib.request, os, subprocess, re, argparse, struct

API_URL = "https://inference.local/v1/chat/completions"
# Override with OMNI_MODEL=... if you switch the gateway to another checkpoint.
MODEL = os.environ.get(
    "OMNI_MODEL",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
)

# This checkpoint is a *reasoning* model: the API can return chain-of-thought
# in `reasoning_content`. For multimodal Q&A, NVIDIA recommends
# `enable_thinking: false` plus instruct-style sampling (low temperature,
# top_k=1) — otherwise completions often collapse into repetitive tokens.
_DEFAULT_CHAT_TEMPLATE_KWARGS = {"enable_thinking": False}


def _no_think_prompt(prompt: str) -> str:
    """Append Nemotron's in-prompt thinking toggle (HF chat_template_jinja).

    The Omni tokenizer template scans each user *text* part for `/no_think`
    and turns off the VLM reasoning path. This still works if an API proxy
    strips top-level `chat_template_kwargs` (see model card on Hugging Face).
    The directive is stripped again before tokenization.
    """
    p = (prompt or "").rstrip()
    if not p or "/no_think" in p:
        return p
    return f"{p}\n/no_think"


AUDIO_EXTS = {"mp3", "wav", "m4a", "aac", "ogg", "flac"}
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
VIDEO_EXTS = {"mp4", "mov", "webm", "mkv", "avi"}

# Per-chunk Omni call should leave room for the synthesis call. Cap each
# chunk's analysis budget so total tokens stay reasonable on a 30-min video.
CHUNK_MAX_TOKENS = 3072
SYNTHESIS_MAX_TOKENS = 4096

# Omni's chat-completions endpoint accepts at most this many image_url
# blocks per request. PDFs / image dirs over this length are split into
# batches, then synthesized.
MAX_IMAGES_PER_CALL = 8


def get_duration(video_path: str):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout:
            return float(json.loads(result.stdout)["format"]["duration"])
    except FileNotFoundError:
        pass
    try:
        return _mp4_duration_pure_python(video_path)
    except Exception:
        return None


def _mp4_duration_pure_python(path: str) -> float:
    with open(path, "rb") as f:
        data = f.read()

    def scan(buf, offset, end):
        while offset < end - 8:
            size = struct.unpack(">I", buf[offset:offset + 4])[0]
            atype = buf[offset + 4:offset + 8]
            if size == 1:
                size = struct.unpack(">Q", buf[offset + 8:offset + 16])[0]
                hdr = 16
            else:
                hdr = 8
            if size <= 0:
                break
            if atype == b"moov":
                inner = scan(buf, offset + hdr, offset + size)
                if inner is not None:
                    return inner
            elif atype == b"mvhd":
                version = buf[offset + hdr]
                body = offset + hdr + 4
                if version == 1:
                    timescale = struct.unpack(">I", buf[body + 16:body + 20])[0]
                    duration = struct.unpack(">Q", buf[body + 20:body + 28])[0]
                else:
                    timescale = struct.unpack(">I", buf[body + 8:body + 12])[0]
                    duration = struct.unpack(">I", buf[body + 12:body + 16])[0]
                return duration / timescale if timescale else 0.0
            offset += size
        return None

    result = scan(data, 0, len(data))
    if result is None:
        raise RuntimeError(f"Could not determine duration of {path}")
    return result


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _is_chunk_dir(path: str) -> bool:
    """A chunk dir is a directory containing one or more .mp4 (or other video) files."""
    if not os.path.isdir(path):
        return False
    return any(
        os.path.splitext(f)[1].lstrip(".").lower() in VIDEO_EXTS
        for f in os.listdir(path)
    )


def _is_longvideo_dir(path: str) -> bool:
    """A long-video bundle has audio.mp3 + manifest.json + frames/ subdir.
    Produced by the server's /api/upload pipeline for long videos."""
    if not os.path.isdir(path):
        return False
    return all(
        os.path.exists(os.path.join(path, p))
        for p in ("audio.mp3", "manifest.json", "frames")
    )


def _load_chunks_manifest(chunk_dir: str) -> list:
    """Return a list of {name, path, start, end} for every chunk, in order."""
    files = sorted(
        f for f in os.listdir(chunk_dir)
        if os.path.splitext(f)[1].lstrip(".").lower() in VIDEO_EXTS
    )
    manifest_path = os.path.join(chunk_dir, "chunks.json")

    times = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            data = json.load(f)
        for entry in data.get("chunks", []):
            times[entry["name"]] = (float(entry["start"]), float(entry["end"]))

    chunks = []
    cursor = 0.0
    for name in files:
        path = os.path.join(chunk_dir, name)
        if name in times:
            start, end = times[name]
        else:
            dur = get_duration(path) or 0.0
            start, end = cursor, cursor + dur
        chunks.append({"name": name, "path": path, "start": start, "end": end})
        cursor = chunks[-1]["end"]
    return chunks


def _build_content_blocks(path: str, prompt: str) -> list:
    """Build messages[0].content for non-chunked inputs.

    Order follows NVIDIA Omni cookbooks: video_url / input_audio *before* the
    question text for video and audio; image examples keep text then image.
    """
    if os.path.isdir(path):
        # PDF-pages dir (images only) — instructions first, then pages.
        blocks: list = [{"type": "text", "text": prompt}]

        pages = sorted(
            os.path.join(path, f)
            for f in os.listdir(path)
            if os.path.splitext(f)[1].lstrip(".").lower() in IMAGE_EXTS
        )
        for p in pages:
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = os.path.splitext(p)[1].lstrip(".").lower() or "png"
            blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/{ext};base64,{b64}"},
            })
        return blocks

    ext = os.path.splitext(path)[1].lstrip(".").lower() or "mp4"
    with open(path, "rb") as f:
        data_b64 = base64.b64encode(f.read()).decode()

    if ext in AUDIO_EXTS:
        blocks = []
        blocks.append({
            "type": "input_audio",
            "input_audio": {
                "data": data_b64,
                "format": "mp3" if ext == "mp3" else "wav",
            },
        })
        blocks.append({"type": "text", "text": prompt})
    elif ext in IMAGE_EXTS:
        blocks = [{"type": "text", "text": prompt}]
        blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/{ext};base64,{data_b64}"},
        })
    else:
        # video — match NVIDIA video example: clip first, question second.
        blocks = []
        blocks.append({
            "type": "video_url",
            "video_url": {"url": f"data:video/{ext};base64,{data_b64}"},
        })
        blocks.append({"type": "text", "text": prompt})

    return blocks


def _post(payload: dict) -> dict:
    payload = {**payload}
    # Merge so callers can extend chat_template_kwargs without dropping defaults.
    ct = {**dict(_DEFAULT_CHAT_TEMPLATE_KWARGS), **payload.get("chat_template_kwargs", {})}
    payload["chat_template_kwargs"] = ct
    # Instruct-style defaults reduce runaway repetition vs server defaults.
    payload.setdefault("temperature", 0.2)
    payload.setdefault("top_k", 1)
    raw = json.dumps(payload).encode()
    size_kb = len(raw) // 1024
    # Retry on transient 5xx and SSL/connection errors. The NVIDIA-hosted
    # endpoint occasionally returns 502/503 mid-demo; one-shot retry with a
    # short backoff hides the blip.
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                API_URL, data=raw, headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code >= 500 and attempt < 2:
                print(f"  (transient HTTP {e.code} from gateway, retrying in 2s…)", file=sys.stderr)
                import time as _time; _time.sleep(2)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            if attempt < 2:
                print(f"  (connection error: {e.reason}, retrying in 2s…)", file=sys.stderr)
                import time as _time; _time.sleep(2)
                continue
            raise

    msg = data["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
    if not content and reasoning:
        # Reasoning model ran out of tokens before producing a final content
        # block; fall back to whatever it managed to think.
        content = reasoning
    return {
        "content": content,
        "reasoning": reasoning,
        "tokens": data["usage"]["total_tokens"],
        "payload_kb": size_kb,
    }


def call_omni(path: str, prompt: str, max_tokens: int = 2048) -> dict:
    prompt = _no_think_prompt(prompt)
    content = _build_content_blocks(path, prompt)
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }
    raw_size_mb = len(json.dumps(payload).encode()) / 1e6
    if raw_size_mb > 9:
        # The gateway will silently drop this with an SSL EOF after 30+
        # seconds. Fail fast with a useful message instead.
        sys.exit(
            f"\nERROR: this video is too large to send to Omni in one call.\n"
            f"Payload would be {raw_size_mb:.1f} MB; the gateway caps requests at ~9 MB.\n"
            f"Run on the host first to split it into chunks:\n"
            f"    bash scripts/chunk-upload.sh {path}\n"
            f"Then re-ask the question against the chunk directory the helper prints."
        )
    return _post(payload)


def call_omni_text(prompt: str, max_tokens: int = 2048) -> dict:
    """Text-only Omni call (used by the synthesis pass)."""
    prompt = _no_think_prompt(prompt)
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    return _post(payload)


# ─── single-input path (existing behavior) ────────────────────────────────


def analyze_single(video_path: str, prompt: str = None):
    if not os.path.exists(video_path):
        sys.exit(f"File not found: {video_path}")

    duration = get_duration(video_path) if os.path.isfile(video_path) else None
    if os.path.isfile(video_path):
        size_mb = os.path.getsize(video_path) / 1e6
        print(f"Input: {video_path}")
        if duration is not None:
            print(f"Duration: {fmt_time(duration)} ({duration:.1f}s), {size_mb:.1f}MB")
        else:
            print(f"Size: {size_mb:.1f}MB")
    else:
        print(f"Input: {video_path} (directory)")

    if prompt is None:
        prompt = (
            "Watch this video carefully and describe in detail what is happening: "
            "what you see, what you hear, what actions take place, and the overall "
            "content or purpose of the video."
        )

    print("\nSending to Nemotron 3 Nano Omni...")
    result = call_omni(video_path, prompt, max_tokens=4096)

    if result["reasoning"] and result["reasoning"] != result["content"]:
        print("\n--- Omni Reasoning ---")
        print(result["reasoning"])
    print("\n--- Omni Analysis ---")
    print(result["content"])
    print(f"\n[{result['tokens']} tokens, {result['payload_kb']}KB payload]")
    return result


# ─── chunked-directory path (new) ──────────────────────────────────────────


def analyze_chunked(chunk_dir: str, prompt: str = None):
    chunks = _load_chunks_manifest(chunk_dir)
    if not chunks:
        sys.exit(f"No video chunks found in {chunk_dir}")

    if prompt is None:
        prompt = (
            "Watch this video carefully and describe what is happening: "
            "what you see, what you hear, what actions take place, and the "
            "overall content or purpose."
        )

    total_dur = chunks[-1]["end"]
    print(f"Chunked input: {chunk_dir}")
    print(f"{len(chunks)} segments, total duration {fmt_time(total_dur)} ({total_dur:.1f}s)")
    print(f"User prompt: {prompt!r}\n")

    chunk_results = []
    total_tokens = 0
    for i, chunk in enumerate(chunks, 1):
        size_mb = os.path.getsize(chunk["path"]) / 1e6
        print(
            f"[{i}/{len(chunks)}] {chunk['name']} "
            f"({fmt_time(chunk['start'])}-{fmt_time(chunk['end'])}, {size_mb:.1f}MB)..."
        )
        chunk_prompt = (
            f"This is segment {i} of {len(chunks)} from a longer video, covering "
            f"{fmt_time(chunk['start'])}–{fmt_time(chunk['end'])} of the source. "
            f"The user's overall question is: {prompt}\n\n"
            f"Describe what happens in THIS segment. Cite specific moments using "
            f"timestamps relative to the FULL video (so a moment 30 seconds into "
            f"this segment becomes {fmt_time(chunk['start'] + 30)}). Stay focused "
            f"on observable events, dialogue, and visuals — leave conclusions for "
            f"later synthesis."
        )
        try:
            r = call_omni(chunk["path"], chunk_prompt, max_tokens=CHUNK_MAX_TOKENS)
        except Exception as e:
            print(f"    ! chunk {i} failed: {e}", file=sys.stderr)
            chunk_results.append({
                **chunk,
                "analysis": f"[chunk failed: {e}]",
                "tokens": 0,
            })
            continue
        chunk_results.append({**chunk, "analysis": r["content"], "tokens": r["tokens"]})
        total_tokens += r["tokens"]
        print(f"    ok — {r['tokens']} tokens")

    print(f"\nSynthesizing across {len(chunk_results)} segments...")

    chunk_summaries = "\n\n".join(
        f"=== Segment {i} ({fmt_time(c['start'])}–{fmt_time(c['end'])}) ===\n{c['analysis']}"
        for i, c in enumerate(chunk_results, 1)
    )
    synthesis_prompt = (
        f"Below are per-segment analyses of a {fmt_time(total_dur)} video, in "
        f"chronological order. The user asked: {prompt}\n\n"
        f"Write ONE coherent answer to the user's question, drawing on all "
        f"segments. Cite timestamps when useful. Do NOT enumerate segments — "
        f"write a unified, natural response.\n\n"
        f"{chunk_summaries}"
    )
    synthesis = call_omni_text(synthesis_prompt, max_tokens=SYNTHESIS_MAX_TOKENS)
    total_tokens += synthesis["tokens"]

    print("\n--- Omni Synthesis ---")
    print(synthesis["content"])
    print(f"\n[{total_tokens} total tokens across {len(chunks)} chunk calls + 1 synthesis]")
    return {
        "chunks": chunk_results,
        "synthesis": synthesis["content"],
        "total_tokens": total_tokens,
    }


# ─── batched-PDF / large-image-dir path ────────────────────────────────────


def _load_image_dir(path: str) -> list:
    """Return sorted list of image file paths in a directory."""
    return sorted(
        os.path.join(path, f)
        for f in os.listdir(path)
        if os.path.splitext(f)[1].lstrip(".").lower() in IMAGE_EXTS
    )


def analyze_image_dir_batched(pages_dir: str, prompt: str = None):
    """For directories of > MAX_IMAGES_PER_CALL images (typically PDFs).

    Splits pages into batches, sends each batch to Omni separately, then
    synthesizes the per-batch analyses into one user-facing answer.
    """
    pages = _load_image_dir(pages_dir)
    if not pages:
        sys.exit(f"No images found in {pages_dir}")

    if prompt is None:
        prompt = (
            "Read the document carefully and describe its content: what it "
            "says, what figures or tables appear, and the overall structure."
        )

    n_pages = len(pages)
    n_batches = (n_pages + MAX_IMAGES_PER_CALL - 1) // MAX_IMAGES_PER_CALL

    print(f"Document input: {pages_dir}")
    print(f"{n_pages} pages → {n_batches} batches of up to {MAX_IMAGES_PER_CALL}")
    print(f"User prompt: {prompt!r}\n")

    batch_results = []
    total_tokens = 0
    for i in range(n_batches):
        first = i * MAX_IMAGES_PER_CALL
        last = min((i + 1) * MAX_IMAGES_PER_CALL, n_pages)
        batch_pages = pages[first:last]
        first_n, last_n = first + 1, last

        batch_prompt = (
            f"This is pages {first_n}–{last_n} of a {n_pages}-page document. "
            f"The user's overall question is: {prompt}\n\n"
            f"Describe what is on THESE pages specifically. Cite the page "
            f"number when referencing content (e.g. 'on page {first_n}…'). "
            f"Stay focused on observable text, figures, and structure — leave "
            f"final conclusions for the synthesis step."
        )

        content = [{"type": "text", "text": _no_think_prompt(batch_prompt)}]
        for p in batch_pages:
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = os.path.splitext(p)[1].lstrip(".").lower() or "png"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/{ext};base64,{b64}"},
            })

        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": CHUNK_MAX_TOKENS,
        }
        print(f"[{i + 1}/{n_batches}] pages {first_n}-{last_n}...")
        try:
            r = _post(payload)
            batch_results.append({
                "first_page": first_n,
                "last_page": last_n,
                "analysis": r["content"],
                "tokens": r["tokens"],
            })
            total_tokens += r["tokens"]
            print(f"    ok — {r['tokens']} tokens")
        except Exception as e:
            print(f"    ! batch {i + 1} failed: {e}", file=sys.stderr)
            batch_results.append({
                "first_page": first_n,
                "last_page": last_n,
                "analysis": f"[batch failed: {e}]",
                "tokens": 0,
            })

    print(f"\nSynthesizing across {n_batches} batches...")
    summaries = "\n\n".join(
        f"=== Pages {b['first_page']}–{b['last_page']} ===\n{b['analysis']}"
        for b in batch_results
    )
    synthesis_prompt = (
        f"Below are per-batch analyses of a {n_pages}-page document, in page "
        f"order. The user asked: {prompt}\n\n"
        f"Write ONE coherent answer to the user's question. Cite page numbers "
        f"when useful. Do NOT enumerate batches — write a unified response.\n\n"
        f"{summaries}"
    )
    synthesis = call_omni_text(synthesis_prompt, max_tokens=SYNTHESIS_MAX_TOKENS)
    total_tokens += synthesis["tokens"]

    print("\n--- Omni Synthesis ---")
    print(synthesis["content"])
    print(f"\n[{total_tokens} total tokens across {n_batches} batch calls + 1 synthesis]")
    return {
        "batches": batch_results,
        "synthesis": synthesis["content"],
        "total_tokens": total_tokens,
    }


# ─── long-video bundle path (long videos: transcript + frames) ───────────────


def _transcribe_audio(audio_path: str) -> str:
    """Transcribe an audio file via Omni's input_audio. If the audio
    is too big for one call, splits it into <8MB pieces with ffmpeg
    `-segment_time` and concatenates the per-piece transcripts."""
    AUDIO_INLINE_LIMIT = 8 * 1024 * 1024
    size = os.path.getsize(audio_path)

    transcribe_prompt = (
        "Transcribe this audio with timestamps and speaker labels. Output ONLY a "
        "JSON array of objects: "
        '[{"timestamp":"M:SS","speaker":"label","text":"..."}, ...]. '
        "Use descriptive speaker labels. Do not summarize — verbatim transcript only."
    )

    if size <= AUDIO_INLINE_LIMIT:
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        result = _post({
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": _no_think_prompt(transcribe_prompt)},
                    {"type": "input_audio",
                     "input_audio": {"data": audio_b64, "format": "mp3"}},
                ],
            }],
            "max_tokens": 8192,
        })
        return result["content"]

    # Audio too big for one call — segment with ffmpeg, transcribe each
    # piece, concatenate. ffmpeg HAS to be available on the host that
    # built the bundle, but inside the sandbox we assume it isn't, so
    # we fall back to the pure-python sliced approach: read the audio
    # bytes in fixed-size windows. Lossy but works without ffmpeg.
    print(f"  audio is {size/1e6:.1f} MB — transcribing in pieces", file=sys.stderr)
    pieces = []
    chunk_bytes = 6 * 1024 * 1024  # 6 MB raw → ~8 MB after base64
    with open(audio_path, "rb") as f:
        while True:
            buf = f.read(chunk_bytes)
            if not buf:
                break
            pieces.append(buf)

    transcript_parts = []
    for i, buf in enumerate(pieces):
        b64 = base64.b64encode(buf).decode()
        print(f"    piece {i + 1}/{len(pieces)}…", file=sys.stderr)
        try:
            result = _post({
                "model": MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text",
                         "text": _no_think_prompt(
                             transcribe_prompt
                             + f"\n\n(This is part {i + 1} of {len(pieces)}.)"
                         )},
                        {"type": "input_audio",
                         "input_audio": {"data": b64, "format": "mp3"}},
                    ],
                }],
                "max_tokens": 6144,
            })
            transcript_parts.append(result["content"])
        except Exception as e:
            print(f"    piece {i + 1} failed: {e}", file=sys.stderr)
            transcript_parts.append(f"[part {i + 1} transcription failed]")

    return "\n\n".join(transcript_parts)


def analyze_longvideo(longvideo_dir: str, prompt: str = None):
    """For a *-longvideo/ bundle: transcribe the audio, then send the
    transcript + 8 evenly-spaced keyframes + the user's question to
    Omni in one multimodal call. Optimized for long recordings (demo
    days, calls, lectures) where the user has a specific question
    rather than wanting a generic summary."""
    manifest_path = os.path.join(longvideo_dir, "manifest.json")
    audio_path = os.path.join(longvideo_dir, "audio.mp3")
    if not (os.path.exists(manifest_path) and os.path.exists(audio_path)):
        sys.exit(f"Not a long-video bundle: {longvideo_dir} (missing manifest.json or audio.mp3)")

    manifest = json.load(open(manifest_path))
    duration = float(manifest.get("duration", 0))
    frames = manifest.get("frames", [])

    if prompt is None:
        prompt = (
            "Summarize this recording. Highlight the key topics covered, who "
            "spoke about what, any specific demos or projects shown on screen, "
            "and the main learnings."
        )

    print(f"Long-video input: {longvideo_dir}")
    print(f"Duration: {fmt_time(duration)} ({duration:.1f}s), {len(frames)} keyframes")
    print(f"Audio: {os.path.getsize(audio_path) / 1e6:.1f} MB")
    print(f"User prompt: {prompt!r}\n")

    print("Step 1: transcribing audio…")
    transcript = _transcribe_audio(audio_path)
    transcript_chars = len(transcript)
    print(f"  transcript: {transcript_chars} chars\n")

    print("Step 2: answering with transcript + frames…")
    context_text = (
        f"You are analyzing a recording lasting {fmt_time(duration)}.\n\n"
        f"Below is the FULL transcript with timestamps, followed by "
        f"{len(frames)} screenshots taken at evenly-spaced moments throughout "
        f"the recording. Each screenshot is annotated with its timestamp.\n\n"
        f"=== TRANSCRIPT ===\n{transcript}\n\n"
        f"=== SCREENSHOTS ===\n"
    )

    content = [{"type": "text", "text": context_text}]
    for frame in frames:
        path = os.path.join(longvideo_dir, "frames", frame["name"])
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ts = float(frame.get("timestamp", 0))
        content.append({"type": "text", "text": f"[frame at {fmt_time(ts)}]"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
    content.append({
        "type": "text",
        "text": _no_think_prompt(
            f"\n=== USER QUESTION ===\n{prompt}\n\n"
            f"Answer the user's question using BOTH the transcript and the visual "
            f"context from the screenshots. Cite timestamps when useful. Be specific "
            f"and grounded in what was actually said and shown — do not invent "
            f"details that aren't in the transcript or visible in the frames."
        ),
    })

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
    }
    raw_size_mb = len(json.dumps(payload).encode()) / 1e6
    print(f"  final payload: {raw_size_mb:.1f} MB")
    if raw_size_mb > 9:
        sys.exit(
            f"\nERROR: long-video payload is {raw_size_mb:.1f} MB, over the gateway "
            f"~9 MB cap. The transcript + frames combined are too large; this "
            f"happens for very long recordings. Reduce frame count in the bundle "
            f"or trim the source video."
        )

    result = _post(payload)

    print("\n--- Omni Answer ---")
    print(result["content"])
    print(f"\n[{result['tokens']} tokens, {raw_size_mb:.1f} MB payload]")
    return result


# ─── transcript mode (single input only) ───────────────────────────────────


def transcript_single(video_path: str):
    if not os.path.exists(video_path):
        sys.exit(f"File not found: {video_path}")
    if _is_chunk_dir(video_path):
        sys.exit("Transcript mode does not support chunked dirs yet. Use analyze mode.")

    duration = get_duration(video_path)
    size_mb = os.path.getsize(video_path) / 1e6
    print(f"Video: {video_path}")
    if duration is not None:
        print(f"Duration: {fmt_time(duration)} ({duration:.1f}s), {size_mb:.1f}MB")
    else:
        print(f"Size: {size_mb:.1f}MB")
    print("Mode: transcript\n")

    transcript_prompt = (
        "Listen carefully to ALL speech and audio in this video. "
        "Transcribe everything that is said. Output ONLY a JSON array of objects "
        "with this exact format — no other text before or after the JSON:\n"
        "[\n"
        '  {"timestamp": "M:SS", "speaker": "Speaker Name or Label", "text": "what they said"},\n'
        "  ...\n"
        "]\n"
        "Rules:\n"
        "- Timestamps relative to the start of the video\n"
        '- Use descriptive speaker labels (e.g., "Professor", "Student", "Narrator")\n'
        "- Transcribe speech verbatim — do not summarize\n"
        "- If there is no speech, return an empty array: []\n"
        "- Output ONLY valid JSON, nothing else"
    )

    print("Sending to Nemotron 3 Nano Omni for transcription...")
    result = call_omni(video_path, transcript_prompt, max_tokens=8192)
    captions = _parse_transcript_json(result["content"])

    output = {
        "video": video_path,
        "duration": fmt_time(duration) if duration is not None else None,
        "duration_seconds": round(duration, 1) if duration is not None else None,
        "total_tokens": result["tokens"],
        "transcript": captions if captions is not None else [
            {"timestamp": "0:00", "speaker": "unknown", "text": result["content"], "raw": True}
        ],
    }

    print(f"\n{'=' * 60}")
    print("TRANSCRIPT OUTPUT")
    print(f"{'=' * 60}")
    print(json.dumps(output, indent=2))
    n = len(output["transcript"])
    print(f"\n[{result['tokens']} tokens, {n} caption(s)]")
    return output


def _parse_transcript_json(text: str):
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r'\[.*\]', text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return None


# ─── entrypoint ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyze video with Nemotron 3 Nano Omni (single video, image, audio, "
                    "PDF-pages dir, or chunked-video dir)",
    )
    parser.add_argument("video", help="Path to video / image / audio / pages dir / chunks dir")
    parser.add_argument("--mode", "-m", choices=["analyze", "transcript"],
                        default="analyze",
                        help="Mode: analyze (default) or transcript (single input only)")
    parser.add_argument("prompt", nargs="?", default=None,
                        help="Custom prompt (analyze mode only)")

    args = parser.parse_args()

    if args.mode == "transcript":
        transcript_single(args.video)
    elif _is_longvideo_dir(args.video):
        # Long-recording bundle (audio.mp3 + frames/ + manifest.json) —
        # transcript + sampled-frame analysis.
        analyze_longvideo(args.video, args.prompt)
    elif _is_chunk_dir(args.video):
        analyze_chunked(args.video, args.prompt)
    elif os.path.isdir(args.video) and len(_load_image_dir(args.video)) > MAX_IMAGES_PER_CALL:
        # Multi-image directory (typically a long PDF) — too many pages for
        # one Omni call, so batch + synthesize.
        analyze_image_dir_batched(args.video, args.prompt)
    else:
        analyze_single(args.video, args.prompt)
