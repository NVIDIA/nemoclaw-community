#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bridge Outlook-style email requests to the financial assistant.

Fixture mode is intended for booth rehearsals and CI. Graph mode is the real
Microsoft Graph path used after OpenShell provider credentials are configured.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_SYSTEM_PROMPT = (
    "You are a concise financial analyst assistant running through NemoClaw/Hermes. "
    "Use public market snapshots and SEC company facts when helpful. Separate facts "
    "from hypotheses. Do not provide investment advice."
)


def request_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def graph_request(
    path: str, *, method: str = "GET", payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    token = os.environ.get("MS_GRAPH_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("MS_GRAPH_ACCESS_TOKEN is required for Graph mode")
    url = f"https://graph.microsoft.com/v1.0{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status == 204:
            return {}
        return json.load(response)


def load_fixture(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("fixture must be a JSON list")
    return data


def load_graph_messages(limit: int) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "$top": str(limit),
            "$orderby": "receivedDateTime desc",
            "$select": "id,from,subject,bodyPreview",
        }
    )
    data = graph_request(f"/me/mailFolders/inbox/messages?{query}")
    messages = []
    for item in data.get("value", []):
        sender = item.get("from", {}).get("emailAddress", {}).get("address", "unknown")
        messages.append(
            {
                "id": item.get("id"),
                "from": sender,
                "subject": item.get("subject", "(no subject)"),
                "body": item.get("bodyPreview", ""),
            }
        )
    return messages


def build_prompt(message: dict[str, Any]) -> str:
    return (
        f"Email from {message.get('from', 'unknown')}.\n"
        f"Subject: {message.get('subject', '(no subject)')}\n\n"
        f"{message.get('body', '')}\n\n"
        "Reply with a concise analyst response suitable for email. Include caveats."
    )


def ask_agent(base_url: str, message: dict[str, Any], timeout: int) -> str:
    payload = {
        "model": os.environ.get("FINANCE_MODEL", "financial-assistant"),
        "messages": [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(message)},
        ],
        "temperature": 0.2,
        "max_tokens": 1000,
    }
    data = request_json(f"{base_url.rstrip('/')}/chat/completions", payload, timeout)
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def reply_graph(message_id: str, body: str) -> None:
    graph_request(
        f"/me/messages/{message_id}/reply", method="POST", payload={"comment": body}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url", dest="base_url", default="http://127.0.0.1:8642/v1"
    )
    parser.add_argument("--fixture", type=Path, help="JSON fixture of email messages")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--reply-mode", choices=["print", "graph"], default="print")
    args = parser.parse_args()

    messages = (
        load_fixture(args.fixture) if args.fixture else load_graph_messages(args.limit)
    )
    results = []
    for message in messages[: args.limit]:
        reply = ask_agent(args.base_url, message, args.timeout)
        if args.reply_mode == "graph":
            if not message.get("id"):
                raise RuntimeError("Graph reply mode requires message id")
            reply_graph(str(message["id"]), reply)
        results.append(
            {
                "id": message.get("id"),
                "from": message.get("from"),
                "subject": message.get("subject"),
                "reply_excerpt": reply[:700],
                "reply_mode": args.reply_mode,
            }
        )
    print(
        json.dumps(
            {"ok": True, "processed": len(results), "results": results}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                indent=2,
            )
        )
        raise SystemExit(1)
