# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Handlers for the vss plugin.

Two tools put a video in front of NVIDIA's RT-VLM (the vision model inside the
Video Search and Summarization blueprint) and return text.

  vss_describe_video(video, focus=None)   timestamped narrative of the clip
  vss_ask_video(video, question)          one answer about the clip

RT-VLM speaks the OpenAI chat-completions dialect with a ``video_url`` content
part. ``video`` is a filename beneath /sandbox/videos, populated explicitly by
the host operator. The local file travels inline as a data URL, so RT-VLM never
fetches arbitrary media URLs and no filesystem is shared with it.

Endpoint and model come from the environment (VSS_BASE_URL, VSS_MODEL), written
into the sandbox .env by ``swarm``. No key: RT-VLM sits on the OpenShell bridge
and only sandboxes whose egress policy names it can reach it.
"""

from __future__ import annotations

import base64
import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT_S = 600
_VIDEO_DIR = "/sandbox/videos"
_MAX_INLINE_BYTES = 40 * 1024 * 1024
_VIDEO_MIME = {
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
_DESCRIBE_PROMPT = (
    "Describe what happens in this video in order, with timestamps. Cover every "
    "visible person, vehicle, piece of equipment and action. Report only what is "
    "visible; say 'not visible' rather than guess.\n"
    "Format each line as: [mm:ss-mm:ss] what happens."
)


def _base_url() -> str:
    return (os.environ.get("VSS_BASE_URL") or _env_file_value("VSS_BASE_URL") or "").rstrip("/")


def _model() -> str:
    return os.environ.get("VSS_MODEL") or _env_file_value("VSS_MODEL") or ""


def _env_file_value(key: str) -> str | None:
    home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
    try:
        with open(os.path.join(home, ".env"), encoding="utf-8") as fh:
            for line in fh:
                k, _, v = line.strip().partition("=")
                if k == key:
                    return v.strip().strip("'\"") or None
    except OSError:
        return None
    return None


def _video_error(message: str) -> tuple[str, str]:
    return "", message


def _resolve_video(video: str) -> tuple[str, str | None]:
    """Return an inline data URL for a confined local video, or an error."""
    video = (video or "").strip()
    if not video:
        return _video_error(f"No video given. Pass a filename under {_VIDEO_DIR}.")

    try:
        scheme = urllib.parse.urlsplit(video).scheme
    except ValueError:
        return _video_error("Video reference is malformed; use a filename under /sandbox/videos.")
    if scheme:
        return _video_error("Video URLs and URI schemes are not accepted; use a filename under /sandbox/videos.")
    if ".." in video.split(os.sep):
        return _video_error(
            f"Video must remain confined beneath {_VIDEO_DIR} without traversal components."
        )

    root = os.path.abspath(_VIDEO_DIR)
    candidate = os.path.abspath(video) if os.path.isabs(video) else os.path.abspath(os.path.join(root, video))
    try:
        if os.path.commonpath((root, candidate)) != root:
            return _video_error(f"Video must be confined to {_VIDEO_DIR}.")
    except ValueError:
        return _video_error(f"Video must be confined to {_VIDEO_DIR}.")

    relative = os.path.relpath(candidate, root)
    parts = relative.split(os.sep)
    if not parts or relative in {"", "."} or any(part in {"", ".", ".."} for part in parts):
        return _video_error(f"Video must be a file beneath {_VIDEO_DIR} without traversal components.")

    extension = os.path.splitext(parts[-1])[1].lower()
    mime = _VIDEO_MIME.get(extension)
    if mime is None:
        return _video_error(f"Video must use one of: {', '.join(sorted(_VIDEO_MIME))}.")

    try:
        resolved_root = os.path.realpath(root)
        resolved_candidate = os.path.realpath(candidate)
        if os.path.commonpath((resolved_root, resolved_candidate)) != resolved_root:
            return _video_error(f"Video must be confined to {_VIDEO_DIR}; symlink escapes are not accepted.")
    except (OSError, ValueError):
        return _video_error(
            f"Video reference is malformed or cannot be confined beneath {_VIDEO_DIR}."
        )

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    opened_directories: list[int] = []
    file_fd: int | None = None
    try:
        current_fd = os.open(root, directory_flags | nofollow)
        opened_directories.append(current_fd)
        for component in parts[:-1]:
            current_fd = os.open(component, directory_flags | nofollow, dir_fd=current_fd)
            opened_directories.append(current_fd)

        before_open = os.stat(parts[-1], dir_fd=current_fd, follow_symlinks=False)
        if not stat.S_ISREG(before_open.st_mode):
            return _video_error("Video path is not a regular file; symlinks are not accepted.")
        file_flags = (
            os.O_RDONLY
            | nofollow
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        file_fd = os.open(parts[-1], file_flags, dir_fd=current_fd)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            return _video_error("Video path is not a regular file.")
        if (metadata.st_dev, metadata.st_ino) != (before_open.st_dev, before_open.st_ino):
            return _video_error("Video path changed while it was being opened.")
        if metadata.st_size == 0:
            return _video_error("Video file is empty.")
        if metadata.st_size > _MAX_INLINE_BYTES:
            return _video_error(
                f"Video is {metadata.st_size // (1024 * 1024)} MiB; "
                f"the inline limit is {_MAX_INLINE_BYTES // (1024 * 1024)} MiB. Use a shorter clip."
            )
        with os.fdopen(file_fd, "rb", closefd=False) as fh:
            payload = fh.read(_MAX_INLINE_BYTES + 1)
        if not payload:
            return _video_error("Video file became empty while it was being read.")
        if len(payload) > _MAX_INLINE_BYTES:
            return _video_error(
                f"Video grew beyond the {_MAX_INLINE_BYTES // (1024 * 1024)} MiB inline limit while reading."
            )
    except (OSError, ValueError):
        return _video_error(
            f"No readable regular video file was found beneath {_VIDEO_DIR}; "
            "symlinks are not accepted."
        )
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for directory_fd in reversed(opened_directories):
            os.close(directory_fd)

    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime};base64,{encoded}", None


def _chat(prompt: str, video_url: str, max_tokens: int) -> dict:
    base, model = _base_url(), _model()
    if not base:
        return {
            "error": "VSS_BASE_URL is not set for this bot. An operator sets "
            "VSS_BASE_URL in swarm.env and re-runs swarm up."
        }
    if not model:
        # Ask the endpoint; RT-VLM advertises exactly one model.
        try:
            with urllib.request.urlopen(f"{base}/v1/models", timeout=30) as r:
                ids = [m.get("id") for m in json.loads(r.read()).get("data", []) if m.get("id")]
            model = ids[0] if len(ids) == 1 else ""
        except Exception as e:  # noqa: BLE001
            return {"error": f"Could not list models at {base}: {e}"}
        if not model:
            return {"error": f"Set VSS_MODEL; {base}/v1/models advertises {ids}"}
    body = json.dumps({
        "model": model,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "video_url", "video_url": {"url": video_url}},
        ]}],
    }).encode("utf-8")
    req = urllib.request.Request(f"{base}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:400]
        except Exception:  # noqa: BLE001
            pass
        hint = "403 usually means this bot's egress policy does not name the VSS endpoint." if e.code == 403 else ""
        return {"error": f"RT-VLM returned HTTP {e.code}", "hint": hint, "detail": detail}
    except urllib.error.URLError as e:
        return {"error": f"Could not reach RT-VLM at {base}: {e.reason}"}
    try:
        text = out["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"error": "Malformed reply from RT-VLM", "raw": str(out)[:400]}
    usage = out.get("usage") or {}
    return {"model": model, "text": text, "tokens": usage.get("total_tokens")}


def vss_describe_video(args: dict, **kwargs) -> str:
    url, err = _resolve_video(str(args.get("video") or ""))
    if err:
        return json.dumps({"error": err})
    prompt = _DESCRIBE_PROMPT
    focus = str(args.get("focus") or "").strip()
    if focus:
        prompt += f"\nPay particular attention to: {focus}."
    res = _chat(prompt, url, max_tokens=1500)
    res.setdefault("video", args.get("video"))
    return json.dumps(res)


def vss_ask_video(args: dict, **kwargs) -> str:
    question = str(args.get("question") or "").strip()
    if not question:
        return json.dumps({"error": "No question given."})
    url, err = _resolve_video(str(args.get("video") or ""))
    if err:
        return json.dumps({"error": err})
    prompt = (
        f"{question}\n\nAnswer from what is visible in the video only. If the video does not "
        "show enough to answer, say so and describe what it does show."
    )
    res = _chat(prompt, url, max_tokens=800)
    res.setdefault("video", args.get("video"))
    res.setdefault("question", question)
    return json.dumps(res)
