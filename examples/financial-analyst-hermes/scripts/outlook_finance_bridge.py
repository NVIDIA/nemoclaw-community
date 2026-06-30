#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Bridge Outlook-style email requests to the financial assistant.

Fixture mode is intended for booth rehearsals and CI. Graph mode is the real
Microsoft Graph path used after OpenShell provider credentials are configured.
"""

from __future__ import annotations

import argparse
import json
import os
import time
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
        headers={
            "Content-Type": "application/json",
            "User-Agent": "NemoHermes financial assistant Outlook bridge",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def graph_request(
    path: str, *, method: str = "GET", payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    token = os.environ.get(
        "MS_GRAPH_ACCESS_TOKEN", "openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN"
    )
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
            "Prefer": 'outlook.body-content-type="text"',
            "User-Agent": "NemoHermes financial assistant Outlook bridge",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status == 204:
            return {}
        return json.load(response)


def env_email(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if "@" not in value:
        raise RuntimeError(f"{name} must be set to an email address")
    return value


def mailbox_base() -> str:
    mailbox = env_email("OUTLOOK_TARGET_MAILBOX")
    return f"/users/{urllib.parse.quote(mailbox, safe='')}"


def allowed_sender() -> str:
    return env_email("OUTLOOK_REPLY_TO").lower()


def state_path() -> Path:
    default = (
        Path(os.environ.get("HERMES_HOME", "/sandbox/.hermes"))
        / "outlook"
        / "processed.json"
    )
    return Path(os.environ.get("OUTLOOK_BRIDGE_STATE", str(default)))


def load_processed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data}


def save_processed(path: Path, processed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(sorted(processed), indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def load_fixture(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("fixture must be a JSON list")
    return data


def load_graph_messages(
    limit: int, *, include_read: bool = False
) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "$top": str(max(limit * 5, 10)),
            "$orderby": "receivedDateTime desc",
            "$select": "id,from,subject,body,bodyPreview,isRead,receivedDateTime",
        }
    )
    data = graph_request(f"{mailbox_base()}/mailFolders/inbox/messages?{query}")
    messages = []
    sender_allow = allowed_sender()
    for item in data.get("value", []):
        sender = item.get("from", {}).get("emailAddress", {}).get("address", "unknown")
        if sender.lower() != sender_allow:
            continue
        if item.get("isRead") and not include_read:
            continue
        body = item.get("body", {})
        messages.append(
            {
                "id": item.get("id"),
                "from": sender,
                "subject": item.get("subject", "(no subject)"),
                "body": body.get("content") or item.get("bodyPreview", ""),
                "receivedDateTime": item.get("receivedDateTime"),
            }
        )
        if len(messages) >= limit:
            break
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
        f"{mailbox_base()}/messages/{message_id}/reply",
        method="POST",
        payload={"comment": body},
    )


def mark_read(message_id: str) -> None:
    graph_request(
        f"{mailbox_base()}/messages/{message_id}",
        method="PATCH",
        payload={"isRead": True},
    )


def process_messages(
    args: argparse.Namespace, processed: set[str], processed_path: Path
) -> list[dict[str, Any]]:
    messages = (
        load_fixture(args.fixture)
        if args.fixture
        else load_graph_messages(args.limit, include_read=args.include_read)
    )
    results = []
    for message in messages[: args.limit]:
        message_id = str(message.get("id") or "")
        if message_id and message_id in processed:
            continue
        # Fixture mode must enforce the same sender boundary as Graph mode.
        if str(message.get("from", "")).lower() != allowed_sender():
            continue
        reply = ask_agent(args.base_url, message, args.timeout)
        if not reply.strip():
            raise RuntimeError("Hermes returned an empty Outlook reply")
        if args.reply_mode == "graph":
            if not message_id:
                raise RuntimeError("Graph reply mode requires message id")
            # Persist intent before the irreversible Graph call. A crash after
            # Graph accepts the reply remains at-most-once after restart.
            processed.add(message_id)
            save_processed(processed_path, processed)
            reply_graph(message_id, reply)
            mark_read(message_id)
        results.append(
            {
                "id": message.get("id"),
                "from": message.get("from"),
                "subject": message.get("subject"),
                "reply_excerpt": reply[:700],
                "reply_mode": args.reply_mode,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url", dest="base_url", default="http://127.0.0.1:8642/v1"
    )
    parser.add_argument("--fixture", type=Path, help="JSON fixture of email messages")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--reply-mode", choices=["print", "graph"], default="print")
    parser.add_argument("--poll", action="store_true", help="Continuously poll Outlook")
    parser.add_argument(
        "--interval", type=int, default=30, help="Poll interval in seconds"
    )
    parser.add_argument(
        "--include-read",
        action="store_true",
        help="Include read messages during validation. Ignored for fixture mode.",
    )
    args = parser.parse_args()

    processed_path = state_path()
    processed = load_processed(processed_path)
    results: list[dict[str, Any]] = []
    while True:
        batch = process_messages(args, processed, processed_path)
        results.extend(batch)
        if args.reply_mode == "graph":
            save_processed(processed_path, processed)
        if not args.poll:
            break
        print(
            json.dumps(
                {
                    "ok": True,
                    "processed": len(batch),
                    "target_mailbox": os.environ.get("OUTLOOK_TARGET_MAILBOX"),
                    "allowed_sender": os.environ.get("OUTLOOK_REPLY_TO"),
                },
                indent=2,
            ),
            flush=True,
        )
        time.sleep(max(args.interval, 5))

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
