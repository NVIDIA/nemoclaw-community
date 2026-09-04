# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""dropbox plugin, host side only.

Runs inside each bot's host shim profile (the thin Hermes profile Desktop
talks to), never inside a sandbox. When the user drops a video into the chat,
Desktop attaches it as `@file:/host/path/clip.mp4`. That path means nothing
in a sandbox. Before the shim forwards the turn, this plugin uploads the clip
into the vss bot's /sandbox/videos and tells the bot the clip is there by
name, so `@nemoclaw-reviewer what happens in clip.mp4?` just works.

One target sandbox, one directory, video extensions only, size-capped. The
upload is `openshell sandbox upload`, the same call `swarm up` uses for the
shipped clips. Nothing here reads the file's contents.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
MAX_BYTES = int(os.environ.get("SWARM_DROP_MAX_MB", "200")) * 1024 * 1024
# The vss bot's sandbox. `swarm up` writes this into the shim's .env.
VSS_SANDBOX = os.environ.get("SWARM_VSS_SANDBOX", "")
DEST_DIR = "/sandbox/videos"

# @file:/abs/path or @file:"/abs path with spaces", and the bare-path form
# Hermes leaves in the binary-reference block.
_RE_REF = re.compile(r'@file:(?:"([^"]+)"|(\S+))')
_RE_BLOCK = re.compile(r"available on disk at `([^`]+)`")


def register(ctx):
    if not VSS_SANDBOX:
        logger.info("dropbox: SWARM_VSS_SANDBOX unset, plugin idle")
        return
    ctx.register_hook("pre_llm_call", _on_turn)
    logger.info("dropbox: uploading dropped videos to %s:%s", VSS_SANDBOX, DEST_DIR)


def _on_turn(user_message=None, **_ignored):
    try:
        text = _text_of(user_message)
        paths = _video_paths(text)
        if not paths:
            return None
        landed, failed = [], []
        for p in paths:
            ok, why = _upload(p)
            (landed if ok else failed).append((p.name, why))
        return {"context": _note(landed, failed)}
    except Exception as exc:  # never break a turn over a convenience
        logger.warning("dropbox: %s", exc)
        return None


def _text_of(msg) -> str:
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _video_paths(text: str) -> list:
    seen, out = set(), []
    cands = [a or b for a, b in _RE_REF.findall(text)] + _RE_BLOCK.findall(text)
    for raw in cands:
        raw = raw.split(":")[0] if re.search(r":\d+(-\d+)?$", raw) else raw  # strip :10-20 line ranges
        p = Path(os.path.expanduser(raw))
        if p.suffix.lower() not in VIDEO_EXT or str(p) in seen:
            continue
        seen.add(str(p))
        out.append(p)
    return out


def _upload(p: Path):
    if not p.is_file():
        return False, "not found on this host"
    size = p.stat().st_size
    if size > MAX_BYTES:
        return False, f"{size // (1024*1024)} MB is over the {MAX_BYTES // (1024*1024)} MB limit"
    if not shutil.which("openshell"):
        return False, "openshell not on PATH"
    # `openshell sandbox upload DIR DEST` lands DIR inside DEST by basename, so
    # stage under a directory literally named "videos" (same trick as swarm up).
    stage = tempfile.mkdtemp(prefix="swarm-drop.")
    try:
        vdir = Path(stage) / "videos"
        vdir.mkdir()
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", p.name)
        shutil.copy2(p, vdir / safe)
        r = subprocess.run(
            ["openshell", "sandbox", "upload", "--no-git-ignore", VSS_SANDBOX, str(vdir), "/sandbox"],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or "upload failed").strip()[:200]
        return True, safe
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _note(landed, failed) -> str:
    lines = []
    if landed:
        names = ", ".join(f"`{n}`" for _, n in landed)
        lines.append(
            f"The user dropped a video into the chat. It is now in nemoclaw-vss's sandbox at "
            f"{DEST_DIR} and nemoclaw-vss can watch it by filename: {names}. "
            f"Ask nemoclaw-vss about it by that name; ignore any host path in the message."
        )
    for name, why in failed:
        lines.append(f"A dropped video `{name}` could not be delivered to nemoclaw-vss ({why}). Tell the user.")
    return "\n".join(lines)
