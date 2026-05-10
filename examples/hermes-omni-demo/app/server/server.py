#!/usr/bin/env python3
"""
FastAPI backend for the NVIDIA Omni demo frontend.

Runs on the host. Talks to the NemoClaw sandbox via the openshell CLI:
  - POST /api/upload   → saves file locally, uploads it into the sandbox /tmp/
  - POST /api/chat     → streams output from `hermes chat -q "..." --yolo`
  - GET  /api/policy/stream → SSE stream of OCSF ALLOW/DENY events
  - GET  /api/video?path=... → serves a video file out of the sandbox (or host)

Env:
  SANDBOX         Sandbox name (default: my-hermes)
  UPLOAD_DIR      Host scratch dir (default: /tmp/omni-demo-uploads)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SANDBOX = os.environ.get("SANDBOX", "my-hermes")
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/omni-demo-uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Omni Demo Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────── upload ────────────────────────────

class UploadResponse(BaseModel):
    sandbox_path: str
    size_bytes: int
    original_name: str
    kind: str = "video"  # video | audio | document
    pages: int | None = None  # for documents, number of rendered pages


async def _handle_pdf_upload(raw_path: Path, uid: str, original_name: str) -> UploadResponse:
    """Render PDF pages to PNGs on the host, ship them into the sandbox as a
    directory of images. The analyzer script recognizes a `.pdf-pages` dir
    and sends the pages to Omni as a multi-image content block.
    Caps rendering at 15 pages to stay under the gateway's ~9 MB body limit.
    """
    out_dir = UPLOAD_DIR / f"upload-{uid}.pdf-pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "pdftoppm",
        "-r", "110",        # ~110 DPI — sharp enough for text, not too heavy
        "-l", "15",          # cap at first 15 pages
        "-png",
        str(raw_path),
        str(out_dir / "page"),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            500,
            f"pdftoppm failed: {err.decode(errors='ignore')[-300:]}",
        )

    # Count pages produced
    pages = sorted(out_dir.glob("page-*.png"))
    if not pages:
        raise HTTPException(500, "no pages rendered from PDF")

    # Upload the whole directory into the sandbox — for dirs, the DEST must be
    # the full target path (not the parent with a trailing slash, unlike files)
    sandbox_dir = f"/tmp/upload-{uid}.pdf-pages"
    up = await asyncio.create_subprocess_exec(
        "openshell", "sandbox", "upload", SANDBOX, str(out_dir), sandbox_dir,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await up.communicate()
    if up.returncode != 0:
        raise HTTPException(
            500,
            f"pdf sandbox upload failed: {err.decode(errors='ignore')[:400]}",
        )

    total_bytes = sum(p.stat().st_size for p in pages)
    return UploadResponse(
        sandbox_path=sandbox_dir,
        size_bytes=total_bytes,
        original_name=original_name,
        kind="document",
        pages=len(pages),
    )


@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)):
    # Persist to the host scratch dir with a unique name
    original_ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    uid = uuid.uuid4().hex[:8]
    raw_name = f"upload-{uid}{original_ext}"
    raw_path = UPLOAD_DIR / raw_name
    with raw_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # ── PDF branch ─────────────────────────────────────────────
    if original_ext == ".pdf" or (file.content_type or "") == "application/pdf":
        return await _handle_pdf_upload(raw_path, uid, file.filename or raw_name)

    # Omni's `video_url`/`audio_url` API rejects webm/opus. Transcode those
    # to mp4 (video) or mp4/aac (audio-only) on the host before sending in.
    final_path = raw_path
    needs_transcode = original_ext in (".webm", ".ogg", ".opus", ".m4a", ".wav", ".flac", ".mka")
    if needs_transcode:
        out_name = f"upload-{uid}.mp4"
        out_path = UPLOAD_DIR / out_name
        # Treat as audio-only if the input mime starts with audio/ or is a
        # known audio-only extension
        is_audio_only = (
            (file.content_type or "").startswith("audio/")
            or original_ext in (".ogg", ".opus", ".m4a", ".wav", ".flac", ".mka", ".mp3")
        )
        if is_audio_only:
            # Audio-only: transcode to MP3 and name it .mp3 so the analyzer
            # script routes it through Omni's input_audio content type
            # instead of video_url.
            out_name = f"upload-{uid}.mp3"
            out_path = UPLOAD_DIR / out_name
            cmd = [
                "ffmpeg", "-nostdin", "-y", "-i", str(raw_path),
                "-vn",
                "-c:a", "libmp3lame", "-q:a", "4",
                str(out_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-nostdin", "-y", "-i", str(raw_path),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                "-c:a", "aac", "-b:a", "96k",
                "-f", "mp4", "-movflags", "+faststart",
                str(out_path),
            ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0 or not out_path.exists():
            raise HTTPException(
                500,
                f"transcode failed: {err.decode(errors='ignore')[-500:]}",
            )
        final_path = out_path

    is_audio_final = final_path.name.endswith(".mp3") or final_path.name.endswith(".wav")
    size = final_path.stat().st_size

    # Three video paths, picked by length:
    #   ≤ 8 MB                              → single Omni call
    #   8 MB to LONGVIDEO_THRESHOLD_MIN min   → chunk-and-synthesize
    #   > LONGVIDEO_THRESHOLD_MIN min         → long-video bundle (transcript + frames)
    # The last path is for genuinely long content (recorded calls, demo days)
    # where the user is going to ask specific questions, not "summarize."
    VIDEO_INLINE_LIMIT_BYTES = 8 * 1024 * 1024
    LONGVIDEO_THRESHOLD_MIN = float(os.environ.get("LONGVIDEO_THRESHOLD_MIN", "30"))
    duration_seconds: float | None = None
    if not is_audio_final and size > VIDEO_INLINE_LIMIT_BYTES:
        duration_seconds = await _probe_duration_seconds(final_path)

    if (not is_audio_final
            and duration_seconds is not None
            and duration_seconds / 60 >= LONGVIDEO_THRESHOLD_MIN):
        longvideo_dir = await _prepare_longvideo_bundle(final_path, uid, duration_seconds)
        sandbox_path = f"/tmp/{longvideo_dir.name}"
        proc = await asyncio.create_subprocess_exec(
            "openshell", "sandbox", "upload", SANDBOX, str(longvideo_dir), sandbox_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"sandbox upload failed: {err.decode(errors='ignore')[:500]}",
            )
        bundle_size = sum(
            p.stat().st_size for p in longvideo_dir.rglob("*") if p.is_file()
        )
        return UploadResponse(
            sandbox_path=sandbox_path,
            size_bytes=bundle_size,
            original_name=file.filename or longvideo_dir.name,
            kind="video",
        )

    if not is_audio_final and size > VIDEO_INLINE_LIMIT_BYTES:
        chunks_dir = await _chunk_long_video(final_path, uid)
        sandbox_path = f"/tmp/{chunks_dir.name}"
        proc = await asyncio.create_subprocess_exec(
            "openshell", "sandbox", "upload", SANDBOX, str(chunks_dir), sandbox_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"sandbox upload failed: {err.decode(errors='ignore')[:500]}",
            )
        chunk_size = sum(p.stat().st_size for p in chunks_dir.glob("*.mp4"))
        return UploadResponse(
            sandbox_path=sandbox_path,
            size_bytes=chunk_size,
            original_name=file.filename or chunks_dir.name,
            kind="video",
        )

    sandbox_name = final_path.name
    sandbox_path = f"/tmp/{sandbox_name}"
    proc = await asyncio.create_subprocess_exec(
        "openshell", "sandbox", "upload", SANDBOX, str(final_path), "/tmp/",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"sandbox upload failed: {err.decode(errors='ignore')[:500]}",
        )

    return UploadResponse(
        sandbox_path=sandbox_path,
        size_bytes=size,
        original_name=file.filename or sandbox_name,
        kind="audio" if is_audio_final else "video",
    )


async def _probe_duration_seconds(src: Path) -> float | None:
    """Return the video duration in seconds via ffprobe, or None on failure."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(src),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except (ValueError, AttributeError):
        return None


async def _prepare_longvideo_bundle(src: Path, uid: str, duration: float) -> Path:
    """Build a long-video analysis bundle: mono 32 kbps audio + 8 evenly-spaced
    keyframes at 480p + manifest.json. The skill detects this directory shape
    and runs transcript + frames analysis instead of per-chunk video calls."""
    bundle = UPLOAD_DIR / f"upload-{uid}-longvideo"
    frames_dir = bundle / "frames"
    bundle.mkdir(exist_ok=True)
    frames_dir.mkdir(exist_ok=True)
    for old in bundle.glob("*"):
        if old.is_file():
            old.unlink()
    for old in frames_dir.glob("*"):
        old.unlink()

    audio_path = bundle / "audio.mp3"
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libmp3lame", "-b:a", "32k",
        str(audio_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            500,
            f"audio extract failed: {err.decode(errors='ignore')[-500:]}",
        )

    n_frames = 8
    timestamps = [duration * (i + 0.5) / n_frames for i in range(n_frames)]
    for i, ts in enumerate(timestamps):
        out_path = frames_dir / f"frame-{i:02d}-at-{int(ts)}s.jpg"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-y", "-ss", f"{ts:.3f}", "-i", str(src),
            "-frames:v", "1",
            "-vf", "scale=854:480",
            "-q:v", "3",
            str(out_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    frames = sorted(frames_dir.glob("frame-*.jpg"))
    manifest = {
        "source": str(src),
        "duration": duration,
        "audio": "audio.mp3",
        "frames": [
            {
                "name": f.name,
                # Recover the timestamp from the filename so the skill can
                # cite "[frame at 4:32]" when it answers.
                "timestamp": float(f.stem.split("-at-")[1].rstrip("s")),
            }
            for f in frames
        ],
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return bundle


async def _chunk_long_video(src: Path, uid: str) -> Path:
    """ffmpeg-split a too-big video into ≤ 120s chunks at 480p, write a
    chunks.json manifest with absolute timestamps, return the directory.
    Mirrors scripts/chunk-upload.sh — kept here so drag-and-drop in the UI
    works for arbitrarily long videos."""
    chunks_dir = UPLOAD_DIR / f"upload-{uid}-chunks"
    chunks_dir.mkdir(exist_ok=True)
    for old in chunks_dir.glob("*"):
        old.unlink()

    cmd = [
        "ffmpeg", "-nostdin", "-y", "-i", str(src),
        "-vf", "scale=854:480,fps=24",
        "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
        "-force_key_frames", "expr:gte(t,n_forced*120)",
        "-c:a", "aac", "-b:a", "64k",
        "-f", "segment", "-segment_time", "120", "-reset_timestamps", "1",
        "-segment_format", "mp4",
        str(chunks_dir / "chunk_%03d.mp4"),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            500,
            f"chunk transcode failed: {err.decode(errors='ignore')[-500:]}",
        )

    manifest = {"source": str(src), "chunks": []}
    offset = 0.0
    for path in sorted(chunks_dir.glob("chunk_*.mp4")):
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        try:
            dur = float(out.decode().strip())
        except ValueError:
            dur = 0.0
        manifest["chunks"].append({"name": path.name, "start": offset, "end": offset + dur})
        offset += dur

    (chunks_dir / "chunks.json").write_text(json.dumps(manifest, indent=2))
    return chunks_dir


# ──────────────────────────── chat ──────────────────────────────

class ChatRequest(BaseModel):
    prompt: str
    video_path: str | None = None
    session_id: str | None = None
    new_session: bool = False


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


def _compose_prompt(prompt: str, video_path: str | None) -> str:
    """Attach the video path so Hermes picks up the video-analyze skill.

    `openshell sandbox exec` rejects args containing newlines, so we keep the
    composed prompt on a single line.
    """
    user = " ".join(prompt.split())
    if video_path:
        return (
            f"The user uploaded a file at this explicit sandbox path: {video_path}. "
            f"This path is the current attachment; do not use the missing-file fallback. "
            f"Use the video-analyze skill via the terminal tool to inspect exactly this path. "
            f"After the terminal tool returns, answer from its Omni Analysis output. "
            f"If they ask to look something up on Wikipedia, use the jargon-lookup skill. "
            f"Never use browser_navigate or execute_code. "
            f"User question: {user}"
        )
    return user


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Stream tokens from hermes chat via SSE."""
    composed = _compose_prompt(req.prompt, req.video_path)

    # Build the hermes command. By default we chain onto the most recent
    # session with --continue, so the whole browser chat is one continuous
    # Hermes conversation. Client can force a fresh session with new_session.
    hermes_cmd = ["hermes", "chat", "-q", composed, "--yolo"]
    # Session resumption is OPT-IN: the client must pass an explicit
    # session_id to continue a prior chat. We never use `--continue` on
    # behalf of the UI, because that picks up whatever session was most
    # recently on disk — which can be from a different browser tab, a
    # different user, or a CLI test. New browser → new Hermes session.
    if req.new_session:
        pass  # explicit new session — no --resume/--continue
    elif req.session_id:
        hermes_cmd += ["--resume", req.session_id]
    # else: no session id → start a new session (do NOT auto-continue)

    async def generator():
        proc = await asyncio.create_subprocess_exec(
            "openshell", "sandbox", "exec", "-n", SANDBOX, "--",
            *hermes_cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None

        ansi_re = re.compile(rb"\x1b\[[0-9;?]*[ABCDEFGHJKSTfmnsu]")
        # Box border characters (UTF-8):
        #   ╭ = \xe2\x95\xad   ╰ = \xe2\x95\xb0
        #   ╮ = \xe2\x95\xae   ╯ = \xe2\x95\xaf
        #   ─ = \xe2\x94\x80
        BOX_TOP = b"\xe2\x95\xad"
        BOX_BOT = b"\xe2\x95\xb0"
        # The *answer* frame starts with "╭─ ⚕ Hermes"; the opening banner
        # starts with just "╭────" (dashes, no emoji). Discriminate on the
        # ⚕ staff-of-asclepius emoji (UTF-8: \xe2\x9a\x95).
        ANSWER_EMOJI = b"\xe2\x9a\x95"

        def clean_line(raw: bytes) -> bytes:
            s = ansi_re.sub(b"", raw)
            s = s.replace(b"\r", b"")
            return s.strip()

        in_assistant = False
        emitted_any = False
        session_id_emitted = False
        session_re = re.compile(rb"Session:\s+(\S+)")
        # Tail buffer — when Hermes emits no parseable answer we surface the
        # last ~20 raw lines so the user can see *why* in the UI instead of
        # being told to "see backend log". Bounded to avoid unbounded growth.
        from collections import deque
        tail = deque(maxlen=20)

        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                clean = clean_line(line)
                if not clean:
                    continue
                tail.append(clean.decode(errors="ignore"))

                # Pick off the session id that hermes prints at the tail
                if not session_id_emitted:
                    m = session_re.search(clean)
                    if m:
                        yield _sse({
                            "type": "session",
                            "id": m.group(1).decode(errors="ignore"),
                        })
                        session_id_emitted = True

                # Assistant block boundaries — the answer frame is the one
                # that contains the ⚕ emoji; the v0.8.0 banner is not.
                if not in_assistant and clean.startswith(BOX_TOP) and ANSWER_EMOJI in clean:
                    in_assistant = True
                    continue
                if in_assistant and clean.startswith(BOX_BOT):
                    in_assistant = False
                    continue

                if in_assistant:
                    text = clean.decode(errors="ignore")
                    if text:
                        yield _sse({"type": "token", "text": text + "\n"})
                        emitted_any = True
                    continue

                # Outside assistant: surface *actual* commands that ran,
                # and skill invocations. We ignore "preparing X…" noise
                # because the real command line tells you everything.
                text = clean.decode(errors="ignore")

                # "💻 $   <cmd>    5.6s"  — the command that actually ran
                exec_m = re.search(
                    r"\$\s+(.+?)\s+(\d+\.?\d*)\s*s(?:\s*\[exit\s*(\d+)\])?\s*$",
                    text,
                )
                if exec_m:
                    cmd = exec_m.group(1).strip()
                    # Collapse runs of whitespace inside the command
                    cmd = re.sub(r"\s+", " ", cmd)
                    yield _sse({
                        "type": "exec",
                        "cmd": cmd,
                        "duration": exec_m.group(2) + "s",
                        "exit": int(exec_m.group(3)) if exec_m.group(3) else 0,
                    })
                    continue

                # Skill invocations like "⚡ preparing video-analyze…"
                skill_m = re.search(r"preparing\s+([a-zA-Z0-9_-]+)", text)
                if skill_m and skill_m.group(1) not in ("terminal", "execute_code"):
                    yield _sse({"type": "tool", "tool": skill_m.group(1)})
        finally:
            rc = await proc.wait()
            if not emitted_any:
                # Surface the actual hermes output (last ~20 lines) so the
                # user can see *why* nothing came back, instead of being
                # redirected to a backend log that doesn't usefully exist.
                snippet = "\n".join(tail).strip()[-1500:]
                msg = (
                    f"Hermes produced no visible answer (exit {rc}). "
                    "Last lines of output:\n\n" + (snippet or "(empty)")
                )
                yield _sse({"type": "error", "error": msg})
            yield _sse({"type": "done"})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ──────────────────── policy stream (OCSF) ──────────────────────

_OCSF_RE = re.compile(
    r"\[(?P<ts>[\d.]+)\]\s+\[sandbox\]\s+\[OCSF\s*\]\s+\[ocsf\]\s+"
    r"(?P<kind>\S+)\s+\[(?P<sev>[A-Z]+)\s*\]\s+"
    r"(?P<verdict>ALLOWED|DENIED)\s+"
    r"(?P<rest>.*)$"
)


def _parse_ocsf_line(line: str) -> dict | None:
    m = _OCSF_RE.search(line)
    if not m:
        return None
    rest = m.group("rest").strip()
    # Examples:
    #   "POST http://integrate.api.nvidia.com/v1/chat/completions [policy:nvidia]"
    #   "/usr/bin/curl(42311) -> google.com:443 [policy:- engine:opa]"
    binary = ""
    target = rest
    http_methods = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "CONNECT")
    arrow = re.search(
        r"(?P<bin>\S+?)(\([^)]*\))?\s*->\s*(?P<tail>.+?)(?:\s+\[|\s*$)",
        rest,
    )
    if arrow:
        binary = arrow.group("bin")
        tail = arrow.group("tail").strip()
        # tail may be "nvidia.com:443" OR "HEAD http://nvidia.com/"
        tail_parts = tail.split(maxsplit=1)
        if len(tail_parts) >= 2 and tail_parts[0] in http_methods:
            target = tail_parts[1]
        else:
            target = tail_parts[0] if tail_parts else tail
    else:
        # Kind-only lines: "HTTP:HEAD ... <method> <url>"
        parts = rest.split()
        if len(parts) >= 2 and parts[0] in http_methods:
            target = parts[1]
            binary = f"http {parts[0].lower()}"
        elif len(parts) >= 1 and parts[0] in http_methods:
            target = "(no target)"
            binary = f"http {parts[0].lower()}"
    return {
        "ts": float(m.group("ts")),
        "verdict": m.group("verdict"),
        "severity": m.group("sev"),
        "binary": binary,
        "target": target,
    }


@app.get("/api/policy/stream")
async def policy_stream():
    async def generator():
        proc = await asyncio.create_subprocess_exec(
            "openshell", "logs", SANDBOX, "--tail", "--source", "sandbox",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="ignore")
                if "OCSF" not in text or "ocsf" not in text:
                    continue
                evt = _parse_ocsf_line(text)
                if evt:
                    yield _sse(evt)
        finally:
            try:
                proc.terminate()
                await proc.wait()
            except ProcessLookupError:
                pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ──────────────────────── video passthrough ─────────────────────

@app.get("/api/video")
async def get_video(path: str):
    """Download a file out of the sandbox by path, return it to the browser."""
    # Security: only allow paths under /tmp/ or /sandbox/.hermes-data/workspace/
    allowed_prefixes = ("/tmp/", "/sandbox/.hermes-data/workspace/")
    if not any(path.startswith(p) for p in allowed_prefixes):
        raise HTTPException(status_code=400, detail="path not allowed")

    # Use sandbox download
    local_dir = UPLOAD_DIR / "cache"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / Path(path).name

    if not local_path.exists():
        # openshell sandbox download DEST must be a directory; it puts the file inside.
        proc = await asyncio.create_subprocess_exec(
            "openshell", "sandbox", "download", SANDBOX, path, str(local_dir) + "/",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0 or not local_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"could not fetch from sandbox: {err.decode(errors='ignore')[:300]}",
            )

    return FileResponse(local_path, media_type="video/mp4")


@app.get("/api/health")
async def health():
    return {"status": "ok", "sandbox": SANDBOX}


# ──────────────────── memory / history ────────────────────

@app.get("/api/memory/summary")
async def memory_summary(limit: int = 25):
    """Read Hermes session files from the sandbox, aggregate a short summary.
    Returns stats + a reverse-chronological list of recent sessions."""
    # Pull a concatenated JSON array of session summaries from the sandbox.
    # We do the parsing inside the sandbox with python3 so we don't have to
    # transfer potentially large session payloads back to the host.
    inline = r"""
import json, os, glob, sys
sessions_dir = "/sandbox/.hermes-data/sessions"
out = []
for path in sorted(glob.glob(os.path.join(sessions_dir, "session_*.json"))):
    try:
        with open(path) as f:
            d = json.load(f)
    except Exception:
        continue
    msgs = d.get("messages", []) or []
    users = [m for m in msgs if m.get("role") == "user"]
    tools = []
    attach_paths = []
    for m in msgs:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    url = (part.get("video_url") or {}).get("url", "")
                    if "data:" in url and "/tmp/" in str(m):
                        pass
        if m.get("role") == "assistant":
            for tc in (m.get("tool_calls") or []):
                fn = (tc.get("function") or {}).get("name")
                if fn:
                    tools.append(fn)
    # Also harvest attachment paths from user messages (we compose prompts that include /tmp/upload-...)
    for u in users:
        c = u.get("content") or ""
        if isinstance(c, str):
            import re as _re
            for m_ in _re.finditer(r"/tmp/upload-[A-Za-z0-9._-]+(?:\.(?:mp4|mp3|wav|pdf|webm|png|jpg)|\.pdf-pages)?", c):
                attach_paths.append(m_.group(0))
    first_user = next((u.get("content","") for u in users), "") if users else ""
    if isinstance(first_user, list):
        first_user = next((p.get("text","") for p in first_user if isinstance(p,dict) and p.get("type")=="text"), "")
    last_user = ""
    if users:
        lc = users[-1].get("content","")
        last_user = lc if isinstance(lc, str) else next((p.get("text","") for p in lc if isinstance(p,dict) and p.get("type")=="text"), "")
    out.append({
        "id": d.get("session_id", os.path.basename(path)),
        "started": d.get("session_start"),
        "updated": d.get("last_updated"),
        "model": d.get("model") or "",
        "turns": len(users),
        "total_messages": len(msgs),
        "tool_calls": len(tools),
        "tools": list(dict.fromkeys(tools)),
        "first_prompt": (first_user or "")[:200],
        "last_prompt": (last_user or "")[:200],
        "attachment_count": len(set(attach_paths)),
    })
# newest first
out.sort(key=lambda s: s.get("updated") or s.get("started") or "", reverse=True)
print(json.dumps(out))
"""
    # openshell sandbox exec rejects args with newlines, so base64-encode the
    # script and exec it via a short bootstrap that has no newlines.
    import base64 as _b64
    encoded = _b64.b64encode(inline.encode()).decode()
    bootstrap = f"import base64,sys; exec(base64.b64decode('{encoded}').decode())"
    proc = await asyncio.create_subprocess_exec(
        "openshell", "sandbox", "exec", "-n", SANDBOX, "--",
        "python3", "-c", bootstrap,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(500, f"memory read failed: {err.decode(errors='ignore')[:400]}")
    try:
        all_sessions = json.loads(out.decode(errors="ignore") or "[]")
    except Exception as e:
        raise HTTPException(500, f"memory parse: {e}")

    # Aggregate stats
    total_sessions = len(all_sessions)
    total_turns = sum(s.get("turns", 0) for s in all_sessions)
    total_tools = sum(s.get("tool_calls", 0) for s in all_sessions)
    total_attachments = sum(s.get("attachment_count", 0) for s in all_sessions)

    # Top tools across sessions
    tool_counts: dict[str, int] = {}
    for s in all_sessions:
        for t in s.get("tools", []):
            tool_counts[t] = tool_counts.get(t, 0) + 1
    top_tools = sorted(
        ({"name": n, "count": c} for n, c in tool_counts.items()),
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    # First-seen date = oldest session's start
    starts = [s.get("started") for s in all_sessions if s.get("started")]
    oldest = min(starts) if starts else None

    return {
        "stats": {
            "total_sessions": total_sessions,
            "total_turns": total_turns,
            "total_tool_calls": total_tools,
            "total_attachments": total_attachments,
            "oldest": oldest,
        },
        "top_tools": top_tools,
        "recent": all_sessions[:limit],
    }


# ──────────────────── voice transcription ──────────────────

@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Quick voice → text. Records get transcoded to mp3, pushed into the
    sandbox, Omni transcribes via input_audio, we return just the text.
    Does NOT become the chat's video source — this is dictation."""
    ext = Path(file.filename or "rec.webm").suffix.lower() or ".webm"
    uid = uuid.uuid4().hex[:8]
    raw_path = UPLOAD_DIR / f"voice-{uid}{ext}"
    with raw_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # Always transcode to mp3 for input_audio routing
    out_path = UPLOAD_DIR / f"voice-{uid}.mp3"
    tr = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-y", "-i", str(raw_path),
        "-vn", "-c:a", "libmp3lame", "-q:a", "4",
        str(out_path),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await tr.communicate()
    if tr.returncode != 0 or not out_path.exists():
        raise HTTPException(500, f"transcode failed: {err.decode(errors='ignore')[-300:]}")

    # Upload into the sandbox under a scratch name
    sb_path = f"/tmp/{out_path.name}"
    up = await asyncio.create_subprocess_exec(
        "openshell", "sandbox", "upload", SANDBOX, str(out_path), "/tmp/",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await up.communicate()
    if up.returncode != 0:
        raise HTTPException(500, f"sandbox upload failed: {err.decode(errors='ignore')[:300]}")

    # Run the analyzer with a transcribe-only prompt; parse the response
    run = await asyncio.create_subprocess_exec(
        "openshell", "sandbox", "exec", "-n", SANDBOX, "--",
        "python3", "/sandbox/.hermes-data/workspace/omni-video-analyze.py",
        sb_path,
        "Transcribe this audio exactly. Output only the spoken words, no commentary or description.",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await run.communicate()
    text = out.decode(errors="ignore")
    m = re.search(r"---\s*Omni Analysis\s*---\s*(.*?)\s*\[\d+\s+tokens", text, re.DOTALL)
    transcribed = (m.group(1) if m else text).strip()

    # Clean up the scratch audio in the sandbox; we don't need to keep it.
    try:
        await (await asyncio.create_subprocess_exec(
            "openshell", "sandbox", "exec", "-n", SANDBOX, "--",
            "rm", "-f", sb_path,
        )).communicate()
    except Exception:
        pass

    return {"text": transcribed}


# ──────────────────── policy introspection + toggle ─────────

# Name of the on-demand policy block we add/remove for the Google toggle.
GOOGLE_BLOCK_NAME = "demo_google_toggle"

GOOGLE_BLOCK = {
    "name": GOOGLE_BLOCK_NAME,
    "endpoints": [
        {"host": "google.com", "port": 443, "access": "full"},
        {"host": "www.google.com", "port": 443, "access": "full"},
    ],
    "binaries": [
        {"path": "/usr/bin/curl"},
        {"path": "/usr/bin/python3.11"},
    ],
}


# Hot-swap policy toggles. Each one adds/removes a named block that
# whitelists a host for curl + python3.
DEMO_TOGGLES = {
    "nvidia_web": {"name": "nvidia.com", "hosts": ["nvidia.com", "www.nvidia.com"]},
    "google": {"name": "Google", "hosts": ["google.com", "www.google.com"]},
    "openai": {"name": "OpenAI", "hosts": ["openai.com", "chatgpt.com"]},
    "stackoverflow": {"name": "Stack Overflow", "hosts": ["stackoverflow.com"]},
    "reddit": {"name": "Reddit", "hosts": ["reddit.com", "www.reddit.com"]},
    "youtube": {"name": "YouTube", "hosts": ["youtube.com", "www.youtube.com"]},
}


def _toggle_block_name(key: str) -> str:
    # Google uses the legacy name so the existing endpoint stays compatible
    return GOOGLE_BLOCK_NAME if key == "google" else f"demo_{key}_toggle"


def _toggle_policy_block(key: str) -> dict:
    info = DEMO_TOGGLES[key]
    return {
        "name": _toggle_block_name(key),
        "endpoints": [
            {"host": h, "port": 443, "access": "full"} for h in info["hosts"]
        ],
        "binaries": [
            {"path": "/usr/bin/curl"},
            {"path": "/usr/bin/python3.11"},
        ],
    }


async def _dump_policy() -> dict:
    """Fetch the current effective policy as a parsed YAML dict."""
    proc = await asyncio.create_subprocess_exec(
        "openshell", "policy", "get", SANDBOX, "--full",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(500, f"policy get failed: {err.decode(errors='ignore')[:300]}")
    text = out.decode(errors="ignore")
    # Strip the status header — YAML starts at the first "version:" line.
    idx = text.find("\nversion:")
    if idx < 0:
        # Might be at start
        idx = 0 if text.startswith("version:") else text.find("version:")
    if idx > 0:
        text = text[idx + 1:]
    elif idx < 0:
        raise HTTPException(500, "could not locate YAML in policy output")
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise HTTPException(500, f"policy YAML parse error: {e}")


def _summarize_policy(policy: dict) -> dict:
    """Shape the policy into a UI-friendly view."""
    hosts: list[dict] = []
    network = policy.get("network_policies") or {}
    for block_name, block in network.items():
        if not isinstance(block, dict):
            continue
        binaries = [
            Path(b.get("path", "")).name if isinstance(b, dict) else Path(str(b)).name
            for b in (block.get("binaries") or [])
        ]
        binaries = [b.replace("*", "") for b in binaries if b]
        for ep in block.get("endpoints") or []:
            if not isinstance(ep, dict):
                continue
            host = ep.get("host") or "—"
            port = ep.get("port")
            rules = []
            for r in ep.get("rules") or []:
                if not isinstance(r, dict):
                    continue
                allow = r.get("allow")
                if isinstance(allow, dict):
                    rules.append(f"{allow.get('method','')} {allow.get('path','')}".strip())
            access = ep.get("access")
            hosts.append({
                "block": block_name,
                "host": host,
                "port": port,
                "rules": rules if rules else ([access] if access else []),
                "binaries": list(dict.fromkeys(binaries)),
                "is_demo_toggle": block_name == GOOGLE_BLOCK_NAME,
            })
    google_allowed = GOOGLE_BLOCK_NAME in network
    return {
        "google_allowed": google_allowed,
        "hosts": hosts,
        "block_count": len(network),
    }


@app.get("/api/policy/rules")
async def policy_rules():
    policy = await _dump_policy()
    return _summarize_policy(policy)


class GoogleToggleRequest(BaseModel):
    enabled: bool


@app.post("/api/policy/google")
async def policy_google(req: GoogleToggleRequest):
    policy = await _dump_policy()
    network = policy.setdefault("network_policies", {})

    if req.enabled:
        network[GOOGLE_BLOCK_NAME] = GOOGLE_BLOCK
    else:
        network.pop(GOOGLE_BLOCK_NAME, None)

    # Write to a temp file and apply.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, dir="/tmp"
    ) as f:
        yaml.safe_dump(policy, f, sort_keys=False, default_flow_style=False)
        tmp_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "openshell", "policy", "set", "--policy", tmp_path, SANDBOX,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(
                500,
                f"policy set failed: {err.decode(errors='ignore')[:400] or out.decode(errors='ignore')[:400]}",
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Wait for the new policy to actually become "Loaded" — openshell
    # submits it asynchronously and we want the UI state to be honest.
    await _wait_for_policy_loaded(timeout_s=12)

    refreshed = await _dump_policy()
    summary = _summarize_policy(refreshed)
    return {"ok": True, "google_allowed": summary["google_allowed"], "block_count": summary["block_count"]}


# ───── Generalized multi-host hot-swap ─────

@app.get("/api/policy/toggles")
async def list_toggles():
    policy = await _dump_policy()
    network = policy.get("network_policies") or {}
    toggles = []
    for key, info in DEMO_TOGGLES.items():
        toggles.append({
            "key": key,
            "name": info["name"],
            "hosts": info["hosts"],
            "enabled": _toggle_block_name(key) in network,
        })
    return {"toggles": toggles}


class ToggleRequest(BaseModel):
    key: str
    enabled: bool


@app.post("/api/policy/toggle")
async def set_toggle(req: ToggleRequest):
    if req.key not in DEMO_TOGGLES:
        raise HTTPException(400, f"unknown toggle: {req.key}")
    policy = await _dump_policy()
    network = policy.setdefault("network_policies", {})
    block_name = _toggle_block_name(req.key)

    if req.enabled:
        network[block_name] = _toggle_policy_block(req.key)
    else:
        network.pop(block_name, None)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, dir="/tmp"
    ) as f:
        yaml.safe_dump(policy, f, sort_keys=False, default_flow_style=False)
        tmp_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "openshell", "policy", "set", "--policy", tmp_path, SANDBOX,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(
                500,
                f"policy set failed: {err.decode(errors='ignore')[:400] or out.decode(errors='ignore')[:400]}",
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    await _wait_for_policy_loaded(timeout_s=12)
    return {"ok": True, "key": req.key, "enabled": req.enabled}


# ───── Red team runner ─────

RED_TEAM_TARGETS = [
    ("nvidia.com (homepage)", "https://www.nvidia.com"),
    ("Google", "https://google.com"),
    ("OpenAI", "https://openai.com"),
    ("npm registry", "https://registry.npmjs.org"),
    ("NVIDIA API (curl)", "https://integrate.api.nvidia.com/v1/models"),
    ("Wikipedia (curl)", "https://en.wikipedia.org/api/rest_v1/page/summary/NVIDIA"),
    ("Homebrew", "https://formulae.brew.sh/api/formula.json"),
]


@app.post("/api/red-team")
async def red_team():
    """Fire a battery of curl attempts INSIDE the sandbox, one at a time.
    Stream each {running, result} event via SSE so the UI can animate."""

    async def gen():
        yield _sse({"type": "start", "count": len(RED_TEAM_TARGETS)})
        for name, url in RED_TEAM_TARGETS:
            yield _sse({"type": "running", "name": name, "url": url})
            t0 = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                "openshell", "sandbox", "exec", "-n", SANDBOX, "--",
                "curl", "-sS", "-o", "/dev/null",
                "-w", "%{http_code}",
                "--max-time", "5", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                http = out.decode(errors="ignore").strip() or "000"
            except asyncio.TimeoutError:
                proc.kill()
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                http = "000"
            yield _sse({
                "type": "result",
                "name": name,
                "url": url,
                "http_code": http,
                "blocked": http in ("000", "403"),
                "duration_ms": elapsed_ms,
            })
        yield _sse({"type": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _wait_for_policy_loaded(timeout_s: float = 12.0) -> bool:
    """Poll `openshell policy get` until Status=Loaded and Active matches the
    latest Version. Returns True on success, False on timeout.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        proc = await asyncio.create_subprocess_exec(
            "openshell", "policy", "get", SANDBOX,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        text = out.decode(errors="ignore")
        m_v = re.search(r"Version:\s*(\d+)", text)
        m_s = re.search(r"Status:\s*(\w+)", text)
        m_a = re.search(r"Active:\s*(\d+)", text)
        if m_v and m_s and m_a:
            if m_s.group(1) == "Loaded" and m_v.group(1) == m_a.group(1):
                return True
        await asyncio.sleep(0.4)
    return False


# ──────────────── serve the built UI on the same port ──────────────
# Mounted last so /api/* routes still resolve. If ui/dist doesn't exist
# yet (UI not built), the server still runs API-only.

UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
if UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="ui")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
