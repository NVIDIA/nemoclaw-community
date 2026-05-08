#!/usr/bin/python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Fetch all messages in a single email thread (conversation) via Microsoft Graph.

Routes requests through the credential sidecar (MS_GRAPH_SIDECAR_URL) which swaps
Authorization: Bearer MS_GRAPH_TOKEN_PLACEHOLDER for a live delegated access token.

Usage:
    /usr/bin/python3 get_thread.py --conversation-id <ID> [--top N]

The conversation_id is returned by search_emails.py in the "conversation_id" field
of each message.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

MS_GRAPH_TOKEN_PLACEHOLDER = "MS_GRAPH_TOKEN_PLACEHOLDER_OUTLOOK"


def _graph_base() -> str:
    sidecar = os.environ.get("MS_GRAPH_SIDECAR_URL", "").rstrip("/")
    return f"{sidecar}/v1.0" if sidecar else "https://graph.microsoft.com/v1.0"


def _mailbox() -> str:
    for env_key in ("OUTLOOK_REPLY_TO", "OUTLOOK_TARGET_MAILBOX"):
        raw = os.environ.get(env_key, "").strip()
        if raw and not raw.startswith("openshell:resolve:"):
            return f"users/{raw}"
    return "me"


def _graph_get(path: str) -> dict:
    url = f"{_graph_base()}/{path.lstrip('/')}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {MS_GRAPH_TOKEN_PLACEHOLDER}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", {}).get("message", body[:300])
        except Exception:
            detail = body[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _strip_html(text: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_thread(conversation_id: str, top: int) -> list[dict]:
    mailbox = _mailbox()

    # Graph OData requires single quotes around string values; escape embedded quotes.
    safe_id = conversation_id.replace("'", "''")
    params = urllib.parse.urlencode({
        "$filter": f"conversationId eq '{safe_id}'",
        "$select": "id,subject,from,receivedDateTime,body,conversationId",
        "$orderby": "receivedDateTime asc",
        "$top": str(min(top, 50)),
    })
    path = f"{mailbox}/messages?{params}"

    data = _graph_get(path)
    messages = data.get("value", [])

    results = []
    for msg in messages:
        from_addr = msg.get("from", {}).get("emailAddress", {})
        body_obj = msg.get("body", {})
        content = body_obj.get("content", "")
        if body_obj.get("contentType", "text").lower() == "html":
            content = _strip_html(content)
        results.append({
            "id": msg.get("id"),
            "subject": msg.get("subject", "(no subject)"),
            "from": from_addr.get("address", ""),
            "from_name": from_addr.get("name", ""),
            "received": msg.get("receivedDateTime", ""),
            "body": content[:5000],
        })

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch all messages in an Outlook email thread via Microsoft Graph"
    )
    parser.add_argument("--conversation-id", required=True, metavar="ID",
                        help="The conversationId from search_emails.py output")
    parser.add_argument("--top", type=int, default=50,
                        help="Max messages to fetch (default 50; threads rarely exceed this)")
    args = parser.parse_args()

    try:
        messages = fetch_thread(args.conversation_id, args.top)
        print(json.dumps({
            "ok": True,
            "conversation_id": args.conversation_id,
            "count": len(messages),
            "messages": messages,
        }, indent=2))
        return 0
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": "graph_error", "message": str(exc)}))
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": "unexpected", "message": str(exc)}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
