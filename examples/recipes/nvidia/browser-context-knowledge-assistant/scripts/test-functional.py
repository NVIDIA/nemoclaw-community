#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run a live, synthetic Ask NemoClaw conversation and vision check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
VIEWPORT_FIXTURE = ROOT / "tests" / "fixtures" / "red-viewport.jpg.b64"
TERMINAL_STATES = {"complete", "failed", "cancelled"}


def parse_origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))
    ):
        raise argparse.ArgumentTypeError(
            "use an exact HTTPS origin or an HTTP loopback origin"
        )
    try:
        parsed.port
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid origin port: {error}") from None
    return f"{parsed.scheme}://{parsed.netloc}"


class Client:
    def __init__(self, origin: str, timeout: float):
        self.origin = origin
        self.timeout = timeout
        self.token = self._loopback_token()

    def _loopback_token(self) -> str:
        status = self.request("GET", "/api/status", authenticated=False)
        if status.get("auth_required") is not False:
            raise RuntimeError(
                "this functional test requires the loopback development endpoint"
            )
        request = urllib.request.Request(f"{self.origin}/")
        with urllib.request.urlopen(request, timeout=20) as response:
            dashboard = response.read(2_000_001).decode("utf-8", "replace")
        match = re.search(
            r'window\.__HERMES_SESSION_TOKEN__\s*=\s*("(?:\\.|[^"\\])*")',
            dashboard,
        )
        if not match:
            raise RuntimeError("Hermes did not provide a loopback session token")
        token = json.loads(match.group(1))
        if not isinstance(token, str) or not 16 <= len(token) <= 512:
            raise RuntimeError("Hermes provided an invalid loopback session token")
        return token

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        authenticated: bool = True,
        headers: dict[str, str] | None = None,
    ) -> dict:
        request_headers = {"Accept": "application/json"}
        if authenticated:
            request_headers["X-Hermes-Session-Token"] = self.token
        if method != "GET":
            request_headers["Origin"] = self.origin
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.origin}{path}", data=data, headers=request_headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read(4096).decode("utf-8", "replace")
            raise RuntimeError(f"{method} {path} returned HTTP {error.code}: {detail}") from None

    def create_conversation(self, title: str) -> str:
        body = self.request("POST", "/api/plugins/ask-nemoclaw/conversations", {"title": title})
        return str(body["conversation"]["conversation_id"])

    def run_turn(self, conversation_id: str, payload: dict) -> dict:
        submitted = self.request(
            "POST",
            f"/api/plugins/ask-nemoclaw/conversations/{conversation_id}/messages",
            payload,
            headers={"Idempotency-Key": secrets.token_urlsafe(24)},
        )
        job_id = str(submitted["job_id"])
        deadline = time.monotonic() + self.timeout
        last_status = "queued"
        while time.monotonic() < deadline:
            job = self.request(
                "GET",
                f"/api/plugins/ask-nemoclaw/conversations/{conversation_id}/messages/{job_id}",
            )
            status = str(job.get("status") or "unknown")
            if status != last_status:
                print(f"  request stage: {status}", flush=True)
                last_status = status
            if status in TERMINAL_STATES:
                if status != "complete":
                    raise RuntimeError(f"Hermes request ended as {status}: {job.get('error')}")
                result = job.get("result") or {}
                text = str(result.get("text") or "").strip()
                if not text:
                    raise RuntimeError("Hermes completed the request without a response")
                return {"job": job, "text": text}
            time.sleep(2)
        raise RuntimeError(f"Hermes did not finish within {self.timeout:.0f} seconds")


def page_payload(prompt: str, page_text: str | None = None) -> dict:
    return {
        "page_url": "https://example.com/ask-nemoclaw-functional-test",
        "page_title": "Ask NemoClaw synthetic functional test",
        "prompt": prompt,
        "page_text": page_text,
        "capture_mode": "browser",
        "selected_text": None,
        "page_text_truncated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", nargs="?", default="http://127.0.0.1:18789", type=parse_origin)
    parser.add_argument("--timeout", type=float, default=360)
    parser.add_argument(
        "--vision-only",
        action="store_true",
        help="run only the synthetic viewport test (for vision-route diagnosis)",
    )
    args = parser.parse_args()

    client = Client(args.origin, args.timeout)
    marker = f"ASK_NEMOCLAW_E2E_{secrets.token_hex(4).upper()}"
    stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    text_conversation = None
    if not args.vision_only:
        print("Text-context conversation", flush=True)
        text_conversation = client.create_conversation(f"Functional text test {stamp}")
        first = client.run_turn(
            text_conversation,
            page_payload(
                "Read the synthetic page context. Reply with only its uppercase marker.",
                f"This is synthetic test content. The uppercase marker is {marker}.",
            ),
        )
        if marker not in first["text"]:
            raise RuntimeError("the first response did not contain the synthetic page marker")
        print("  page context reached Hermes and inference", flush=True)

        second = client.run_turn(
            text_conversation,
            page_payload(
                "What uppercase marker appeared in the previous turn? Reply with only that marker.",
                "This follow-up page context intentionally omits the previous marker.",
            ),
        )
        if marker not in second["text"]:
            raise RuntimeError("the follow-up response did not preserve conversation context")
        print("  follow-up preserved the Hermes conversation", flush=True)

    print("Viewport-image conversation", flush=True)
    vision_conversation = client.create_conversation(f"Functional vision test {stamp}")
    vision_payload = page_payload(
        "What single color fills the attached viewport image? Reply with only the color name."
    )
    vision_payload["viewport_image"] = {
        "mime_type": "image/jpeg",
        "content_base64": VIEWPORT_FIXTURE.read_text(encoding="ascii").strip(),
    }
    vision = client.run_turn(vision_conversation, vision_payload)
    if "red" not in vision["text"].lower():
        raise RuntimeError("the vision response did not identify the red viewport fixture")
    print("  viewport image reached multimodal inference", flush=True)

    listed = client.request("GET", "/api/plugins/ask-nemoclaw/conversations")
    listed_ids = {
        str(item.get("conversation_id")) for item in listed.get("conversations", [])
    }
    expected_ids = {vision_conversation}
    if text_conversation is not None:
        expected_ids.add(text_conversation)
    if expected_ids - listed_ids:
        raise RuntimeError("created conversations were not returned by the conversation API")

    if text_conversation is not None:
        text_state = client.request(
            "GET", f"/api/plugins/ask-nemoclaw/conversations/{text_conversation}"
        )
        if text_state["conversation"].get("message_count") != 4:
            raise RuntimeError("text conversation did not persist two complete turns")
    vision_state = client.request(
        "GET", f"/api/plugins/ask-nemoclaw/conversations/{vision_conversation}"
    )
    if vision_state["conversation"].get("message_count") != 2:
        raise RuntimeError("vision conversation did not persist one complete turn")

    print("Functional test passed: text, follow-up, vision, and conversation listing")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
