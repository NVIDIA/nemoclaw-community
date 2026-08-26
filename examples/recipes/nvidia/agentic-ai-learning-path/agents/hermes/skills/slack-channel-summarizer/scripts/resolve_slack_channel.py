#!/usr/bin/python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Resolve Slack channel names to IDs using a bot token.

This helper exists because the model was repeatedly choosing the wrong Slack API
lookup path. It implements the intended decision tree directly:

1. If a channel ID is already known, return it.
2. Search public channels first via conversations.list with pagination.
3. Only then try private-channel discovery via users.conversations.
4. Classify missing scopes and "not found" cleanly in JSON output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from slack_api_common import get_slack_bot_token


API_BASE = "https://slack.com/api"


def api_call(token: str, method: str, params: Dict[str, str]) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{API_BASE}/{method}?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def normalize_name(value: str) -> str:
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
    return value.lower()


def looks_like_channel_id(value: str) -> bool:
    return bool(re.fullmatch(r"[CGD][A-Z0-9]+", value.strip()))


def extract_channel_id(value: str) -> Optional[str]:
    value = value.strip()
    mention = re.search(r"<#([CGD][A-Z0-9]+)(?:\|[^>]+)?>", value)
    if mention:
        return mention.group(1)
    raw = re.search(r"\b([CGD][A-Z0-9]{8,})\b", value)
    if raw:
        return raw.group(1)
    return None


def find_in_public_channels(token: str, channel_name: str, page_cap: int) -> Dict[str, Any]:
    cursor = ""
    for page in range(1, page_cap + 1):
        params = {"types": "public_channel", "limit": "200"}
        if cursor:
            params["cursor"] = cursor
        data = api_call(token, "conversations.list", params)
        if not data.get("ok"):
            return {
                "ok": False,
                "stage": "public_lookup",
                "error": data.get("error", "unknown_error"),
                "needed": data.get("needed"),
                "provided": data.get("provided"),
                "page": page,
            }
        for channel in data.get("channels", []):
            if normalize_name(channel.get("name", "")) == channel_name:
                return {
                    "ok": True,
                    "stage": "public_lookup",
                    "channel_id": channel.get("id"),
                    "channel_name": channel.get("name"),
                    "channel_type": "public_channel",
                    "page": page,
                }
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return {
        "ok": False,
        "stage": "public_lookup",
        "error": "channel_not_found",
    }


def find_in_private_channels(token: str, channel_name: str, page_cap: int) -> Dict[str, Any]:
    cursor = ""
    for page in range(1, page_cap + 1):
        params = {"types": "private_channel", "limit": "200"}
        if cursor:
            params["cursor"] = cursor
        data = api_call(token, "users.conversations", params)
        if not data.get("ok"):
            return {
                "ok": False,
                "stage": "private_lookup",
                "error": data.get("error", "unknown_error"),
                "needed": data.get("needed"),
                "provided": data.get("provided"),
                "page": page,
            }
        for channel in data.get("channels", []):
            if normalize_name(channel.get("name", "")) == channel_name:
                return {
                    "ok": True,
                    "stage": "private_lookup",
                    "channel_id": channel.get("id"),
                    "channel_name": channel.get("name"),
                    "channel_type": "private_channel",
                    "page": page,
                }
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return {
        "ok": False,
        "stage": "private_lookup",
        "error": "channel_not_found",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", help="Slack channel name like nemoclaw-situation-room")
    parser.add_argument("--id", dest="channel_id", help="Known Slack channel ID like C0123456789")
    parser.add_argument("--input", help="Raw user-provided channel value; can be name, mention, URL, or ID")
    parser.add_argument("--page-cap", type=int, default=25)
    args = parser.parse_args()

    token = get_slack_bot_token()
    if not token:
        print(json.dumps({"ok": False, "error": "missing_token"}))
        return 1

    raw_value = args.input or args.channel_id or args.name or ""
    extracted_id = extract_channel_id(raw_value)
    if extracted_id:
        print(json.dumps({
            "ok": True,
            "stage": "direct_id",
            "channel_id": extracted_id,
        }))
        return 0

    if args.channel_id and looks_like_channel_id(args.channel_id):
        print(json.dumps({
            "ok": True,
            "stage": "direct_id",
            "channel_id": args.channel_id.strip(),
        }))
        return 0

    channel_name = normalize_name(args.name or args.input or "")
    if not channel_name:
        print(json.dumps({"ok": False, "error": "missing_channel_name"}))
        return 1

    try:
        public_result = find_in_public_channels(token, channel_name, args.page_cap)
        if public_result.get("ok"):
            print(json.dumps(public_result))
            return 0

        private_result = find_in_private_channels(token, channel_name, args.page_cap)
        if private_result.get("ok"):
            print(json.dumps(private_result))
            return 0

        if private_result.get("error") == "missing_scope" and private_result.get("needed") == "groups:read":
            print(json.dumps({
                "ok": False,
                "stage": "private_lookup",
                "error": "missing_private_discovery_scope",
                "needed": "groups:read",
                "searched_public_pages": args.page_cap,
                "public_lookup": public_result,
            }))
            return 2

        print(json.dumps({
            "ok": False,
            "error": "channel_not_found",
            "searched_public_pages": args.page_cap,
            "public_lookup": public_result,
            "private_lookup": private_result,
        }))
        return 3
    except urllib.error.HTTPError as err:
        print(json.dumps({
            "ok": False,
            "error": "http_error",
            "status": err.code,
            "reason": err.reason,
        }))
        return 4
    except Exception as err:  # pragma: no cover - defensive
        print(json.dumps({
            "ok": False,
            "error": "exception",
            "detail": str(err),
        }))
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
