# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Handlers for the vss plugin.

Two tools that put a video in front of NVIDIA's RT-VLM (the vision model
inside the Video Search and Summarization blueprint) and return text.

  vss_describe_video(video, focus=None)   timestamped narrative of the clip
  vss_ask_video(video, question)          one answer about the clip

RT-VLM speaks the OpenAI chat-completions dialect with a `video_url` content
part. `video` is a filename under /sandbox/videos (copied in by `swarm` from
VSS_VIDEOS_DIR) or an http(s) URL the RT-VLM container can fetch. Local files
travel inline as a data: URL, so no shared filesystem or upload step is
needed; the size cap below keeps that honest.

Endpoint and model come from the environment (VSS_BASE_URL, VSS_MODEL),
written into the sandbox .env by `swarm`. No key: RT-VLM sits on the OpenShell
bridge and only sandboxes whose egress policy names it can reach it.
"""

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request

_TIMEOUT_S = 600
_VIDEO_DIR = "/sandbox/videos"
_MAX_INLINE_BYTES = 40 * 1024 * 1024  # a 30 s 1080p clip is well under this
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


def _resolve_video(video: str) -> tuple[str, str | None]:
    """Return (url_for_rtvlm, error). url is "" when error is set."""
    video = (video or "").strip()
    if not video:
        return "", "No video given. Pass a filename under /sandbox/videos or an http(s) URL."
    if video.startswith(("http://", "https://")):
        return video, None
    # Paths: confine to /videos, no traversal.
    rel = video[len(_VIDEO_DIR) + 1 :] if video.startswith(_VIDEO_DIR + "/") else video.lstrip("/")
    path = os.path.realpath(os.path.join(_VIDEO_DIR, rel))
    if not path.startswith(_VIDEO_DIR + "/"):
        return "", f"'{video}' is outside {_VIDEO_DIR}."
    if not os.path.isfile(path):
        try:
            have = sorted(os.listdir(_VIDEO_DIR))
        except OSError:
            have = []
        return "", f"No such file: {path}. Available: {', '.join(have) or 'nothing in /sandbox/videos'}"
    size = os.path.getsize(path)
    if size > _MAX_INLINE_BYTES:
        return "", f"{path} is {size // (1024*1024)} MB; the inline limit is {_MAX_INLINE_BYTES // (1024*1024)} MB. Use a shorter clip or an http(s) URL."
    mime = mimetypes.guess_type(path)[0] or "video/mp4"
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{b64}", None


def _chat(prompt: str, video_url: str, max_tokens: int) -> dict:
    base, model = _base_url(), _model()
    if not base:
        return {"error": "VSS_BASE_URL is not set for this bot. An operator sets VSS_BASE_URL in swarm.env and re-runs swarm up."}
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
