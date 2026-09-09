# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Handlers for teammates.

Sends a message to a teammate bot's api_server (OpenAI-compatible
/v1/chat/completions) and returns their reply.

Peers are read from the profile's own config (bot_peers) so this works
unchanged on a host profile or inside an OpenShell sandbox. Keys are read
from the environment (HERMES_PEER_<NAME>_KEY), never hardcoded.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

_TIMEOUT_S = 300
_HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.join(
    os.path.expanduser("~"), ".hermes"
)
# Images attached to the sender's current turn can be forwarded to the teammate
# as image_url parts when the call sets with_images. Off by default. Cap so one
# handoff cannot carry an album.
_MAX_FORWARD_IMAGES = 4
# A structural reference to an image the recipient is expected to have. This is
# deliberately narrower than words such as "look" and "see": ordinary requests
# like "look into issue 42" must remain ordinary text handoffs.
_RE_DEICTIC_IMAGE = re.compile(
    r"\b(?:this|that|the|my|your|attached|uploaded)\s+"
    r"(?:(?:attached|uploaded)\s+)?(?:image|picture|photo|photograph|screenshot)\b"
    r"|\b(?:image|picture|photo|photograph|screenshot)\s+"
    r"(?:above|below|attached|uploaded|sent|shared)\b",
    re.IGNORECASE,
)
_RE_PATH_HINT = re.compile(
    r"\[Image attached(?: at)?:[^\]]*\]|MEDIA:\S+|(?<![\w/])/(?:tmp|sandbox|home|Users|var)/\S+\.(?:png|jpe?g|gif|webp)\b",
    re.IGNORECASE,
)


def _current_session_id() -> str:
    """The session this tool call belongs to, as the gateway records it."""
    try:
        from gateway.session_context import get_session_env  # part of Hermes

        sid = get_session_env("HERMES_SESSION_ID", "")
        if sid:
            return sid
    except Exception:
        pass
    return os.environ.get("HERMES_SESSION_ID", "")


# session_id -> image_url parts from that session's current user turn. Filled
# by the pre_llm_call hook in __init__.py, which Hermes fires once per turn
# with the user message as received, before any image handling for the bot's
# own (possibly text-only) model. A tool handler has no other view of the live
# turn: state.db is written after the turn ends, the dispatcher passes no
# messages, and by the time a model request is built a non-vision model has
# already had its images replaced with text. Text crosses the sandbox boundary
# as text; a picture the user attached to THIS bot's turn is invisible to a
# teammate unless we carry it. Only data: and http(s) URLs are kept; paths
# mean nothing in another sandbox.
_TURN_IMAGES: dict = {}


def remember_turn_images(session_id: str, user_message) -> None:
    """Called from the pre_llm_call hook at the start of each turn."""
    if not session_id:
        return
    imgs = []
    if isinstance(user_message, list):
        for p in user_message:
            if not isinstance(p, dict) or p.get("type") not in ("image_url", "input_image"):
                continue
            ref = p.get("image_url")
            url = (ref.get("url") if isinstance(ref, dict) else ref) or ""
            url = str(url).strip()
            if url.startswith(("data:image/", "http://", "https://")):
                imgs.append({"type": "image_url", "image_url": {"url": url}})
            if len(imgs) >= _MAX_FORWARD_IMAGES:
                break
    _TURN_IMAGES[session_id] = imgs
    if len(_TURN_IMAGES) > 64:  # bounded; sessions are short-lived here
        for k in list(_TURN_IMAGES)[:-32]:
            _TURN_IMAGES.pop(k, None)


def _images_in_current_turn(session_id: str = "") -> list:
    # Prefer the session id the dispatcher hands the handler. The ContextVar
    # fallback is not set on the worker threads Hermes uses when the model
    # emits several tool calls at once, and a miss there silently drops the
    # image from every call but the first.
    sid = (session_id or "").strip() or _current_session_id()
    return list(_TURN_IMAGES.get(sid, []))


def _load_peers() -> dict:
    """Read bot_peers from this profile's config.yaml. Returns {name: {url, note}}."""
    cfg_path = os.path.join(_HERMES_HOME, "config.yaml")
    peers: dict = {}
    try:
        import yaml  # bundled with Hermes

        with open(cfg_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        raw = cfg.get("bot_peers") or {}
        for name, entry in raw.items():
            if isinstance(entry, dict) and entry.get("url"):
                peers[str(name)] = {
                    "url": str(entry["url"]).rstrip("/"),
                    "note": str(entry.get("note") or ""),
                }
    except FileNotFoundError:
        pass
    except Exception:
        # A malformed config should not crash the tool; report empty.
        pass
    return peers


def _peer_key(name: str) -> str | None:
    """Key for a peer, as stored by `hermes peer add`.

    Checks the process environment first, then falls back to reading
    $HERMES_HOME/.env directly — plugin handlers do not always run with the
    profile's .env already exported.
    """
    # Same derivation as hermes_cli/subcommands/peer.py: dashes become
    # underscores. "nemoclaw-reviewer" -> HERMES_PEER_NEMOCLAW_REVIEWER_KEY.
    var = f"HERMES_PEER_{name.upper().replace('-', '_')}_KEY"
    val = os.environ.get(var)
    if val:
        return val
    env_path = os.path.join(_HERMES_HOME, ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == var:
                    return v.strip().strip("'\"") or None
    except FileNotFoundError:
        return None
    except Exception:
        return None
    return None


def list_teammates(args: dict, **kwargs) -> str:
    peers = _load_peers()
    if not peers:
        return json.dumps(
            {
                "teammates": [],
                "note": "No teammates configured. An operator must run: hermes peer add <name> --url <url> --key <key>",
            }
        )
    return json.dumps(
        {
            "teammates": [
                {
                    "name": n,
                    "role_note": p["note"],
                    "reachable": bool(_peer_key(n)),
                }
                for n, p in sorted(peers.items())
            ]
        }
    )


def message_teammate(args: dict, **kwargs) -> str:
    teammate = str(args.get("teammate") or "").strip()
    message = str(args.get("message") or "").strip()

    if not teammate:
        return json.dumps({"error": "No teammate specified. Call list_teammates first."})
    if not message:
        return json.dumps({"error": "No message provided."})

    peers = _load_peers()
    if teammate not in peers:
        return json.dumps(
            {
                "error": f"Unknown teammate '{teammate}'.",
                "known_teammates": sorted(peers.keys()),
            }
        )

    key = _peer_key(teammate)
    if not key:
        return json.dumps(
            {
                "error": f"No API key available for '{teammate}'. "
                f"Expected env var HERMES_PEER_{teammate.upper().replace('-', '_')}_KEY."
            }
        )

    url = f"{peers[teammate]['url']}/v1/chat/completions"
    # Opt-in. Images cross the sandbox boundary only when the sender's model
    # asks for it, and the result says how many went.
    images = _images_in_current_turn(str(kwargs.get("session_id") or "")) if args.get("with_images") else []
    if not images:
        # No image is riding along. If the ask contains a copied path/attachment
        # marker or structurally refers to an expected image, say so explicitly
        # so a vision teammate does not describe pixels it never received.
        had_path_hint = bool(_RE_PATH_HINT.search(message))
        if had_path_hint:
            message = _RE_PATH_HINT.sub("an image", message)
            message = re.sub(r"[ \t]{2,}", " ", message).strip()
        if had_path_hint or _RE_DEICTIC_IMAGE.search(message):
            message += ("\n\n[No image is attached to this message. Answer that you were not given an "
                        "image; do not guess what it shows.]")
    if images:
        # Hermes appends "[Image attached at: /host/path]" hints to the text
        # when it attaches an image natively. That path is on the sender's
        # side of the wall; a teammate that sees it will try to open it and
        # fail instead of looking at the image it was given. Strip the hints
        # and any MEDIA:/path tokens the model may have copied from them.
        message = _RE_PATH_HINT.sub("the attached image", message)
        message = re.sub(r"[ \t]{2,}", " ", message).strip()
        message = message + (
            "\n\n[An image from my turn is attached to this message. Look at it "
            "directly; do not try to open a file path.]"
        )
    content = message if not images else [{"type": "text", "text": message}, *images]
    payload = json.dumps(
        {
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": content}],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        hint = ""
        if e.code == 403:
            hint = "403 usually means the sandbox egress policy does not allow this port."
        elif e.code == 401:
            hint = "401 means the peer API key is wrong or missing."
        return json.dumps(
            {"error": f"{teammate} rejected the request (HTTP {e.code})", "hint": hint, "detail": detail}
        )
    except urllib.error.URLError as e:
        return json.dumps(
            {"error": f"Could not reach {teammate} at {peers[teammate]['url']}: {e.reason}"}
        )
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": f"Unexpected failure contacting {teammate}: {e}"})

    try:
        reply = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return json.dumps({"error": "Malformed reply from teammate", "raw": str(body)[:400]})

    usage = body.get("usage") or {}
    result = {
        "teammate": teammate,
        "reply": reply,
        "tokens": usage.get("total_tokens"),
    }
    if images:
        result["images_forwarded"] = len(images)
    return json.dumps(result)
