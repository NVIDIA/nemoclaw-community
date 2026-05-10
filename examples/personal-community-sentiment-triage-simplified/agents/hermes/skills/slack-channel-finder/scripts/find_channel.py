#!/usr/bin/python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
find_channel.py

Search and rank Slack channels matching a topic or team query.

Searches across ALL discoverable public channels in the workspace (not just
bot-member channels), then ranks results by how well the channel name, topic,
and purpose match the query. For channels the bot is a member of, membership is
flagged so the caller knows full history/pins signals are available via
describe_slack_channel.py.

Usage:
    /usr/bin/python3 find_channel.py --query "inference deployments"
    /usr/bin/python3 find_channel.py --query "nemoclaw" --top 5
    /usr/bin/python3 find_channel.py --query "k8s" --member-only

Environment:
    SLACK_BOT_TOKEN must be set.

Exit codes:
    0  ok (even if 0 results found)
    1  bad arguments or environment
    2  Slack API error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SLACK_API_BASE = "https://slack.com/api"
DEFAULT_TIMEOUT_SECONDS = 15
PAGE_LIMIT = 200

# Common engineering abbreviations (same set as describe_slack_channel.py).
TOKEN_EXPANSIONS: dict[str, str] = {
    "eng": "engineering",
    "infra": "infrastructure",
    "ops": "operations",
    "sre": "site reliability",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "k8s": "kubernetes",
    "qa": "quality assurance",
    "ux": "user experience",
    "ui": "user interface",
    "perf": "performance",
    "sec": "security",
    "infosec": "information security",
    "fe": "frontend",
    "be": "backend",
    "db": "database",
    "obs": "observability",
    "rel": "release",
    "dep": "deployment",
    "deps": "dependencies",
    "biz": "business",
    "proj": "project",
    "xfn": "cross functional",
    "inf": "inference",
    "nemo": "nvidia nemo",
    "claw": "nemoclaw",
}


def slack_get(method: str, params: dict[str, Any], token: str) -> dict[str, Any]:
    """Call a Slack Web API GET method and return parsed JSON. Retries on 429."""
    url = f"{SLACK_API_BASE}/{method}?{urlencode(params)}"
    req = Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 429 and attempt < 2:
                retry_after = min(int(e.headers.get("Retry-After", "1")), 5)
                time.sleep(retry_after)
                continue
            return {"ok": False, "error": f"http_{e.code}", "detail": str(e)}
        except URLError as e:
            return {"ok": False, "error": "url_error", "detail": str(e)}
        except json.JSONDecodeError as e:
            return {"ok": False, "error": "bad_json", "detail": str(e)}
    return {"ok": False, "error": "rate_limited"}


def tokenize(text: str) -> list[str]:
    """Split on delimiters and expand abbreviations."""
    if not text:
        return []
    raw = re.split(r"[-_./\s]+", text.lower())
    out: list[str] = []
    for tok in raw:
        tok = tok.strip()
        if not tok:
            continue
        expanded = TOKEN_EXPANSIONS.get(tok, tok)
        out.append(expanded)
        # Also add the original token if it was expanded (for partial matching)
        if expanded != tok:
            out.append(tok)
    return out


def query_tokens(query: str) -> list[str]:
    """Tokenise query text, including multi-word phrases and abbreviation expansions."""
    tokens = tokenize(query)
    # Also add the raw query words (lower) for substring matching
    raw_words = [w.lower() for w in query.split() if w]
    return list(dict.fromkeys(tokens + raw_words))  # deduplicate, preserve order


def score_channel(channel: dict[str, Any], q_tokens: list[str]) -> tuple[int, list[str]]:
    """
    Score how well a channel matches the query tokens.

    Scoring weights:
      name token match   : 3 points per matching token
      purpose match      : 2 points per matching query word
      topic match        : 1 point per matching query word
    """
    name = channel.get("name", "")
    purpose = (channel.get("purpose") or {}).get("value", "") if isinstance(channel.get("purpose"), dict) \
              else channel.get("purpose", "")
    topic = (channel.get("topic") or {}).get("value", "") if isinstance(channel.get("topic"), dict) \
            else channel.get("topic", "")

    name_tokens = tokenize(name)
    score = 0
    reasons: list[str] = []

    for q in q_tokens:
        q_lower = q.lower()
        # Name token match (highest weight)
        if any(q_lower in nt for nt in name_tokens):
            score += 3
            reasons.append(f"name:{q_lower}")
        # Purpose match
        if purpose and q_lower in purpose.lower():
            score += 2
            reasons.append(f"purpose:{q_lower}")
        # Topic match
        if topic and q_lower in topic.lower():
            score += 1
            reasons.append(f"topic:{q_lower}")

    # Deduplicate reasons (same token can match multiple ways)
    seen: set[str] = set()
    deduped: list[str] = []
    for r in reasons:
        _, val = r.split(":", 1)
        key = f"{r.split(':')[0]}:{val}"
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    return score, deduped


def fetch_all_channels(
    token: str, member_only: bool, max_pages: int = 5
) -> dict[str, Any]:
    """
    Return all discoverable public channels.

    member_only=True  → users.conversations (bot-member channels only)
    member_only=False → conversations.list  (all public channels in workspace)

    max_pages limits pagination to avoid exhausting rate limits in large workspaces.
    At PAGE_LIMIT=200 and max_pages=5, up to 1000 channels are scanned.
    """
    method = "users.conversations" if member_only else "conversations.list"
    channels: list[dict[str, Any]] = []
    member_ids: set[str] = set()
    cursor: str | None = None

    # First get bot-member channels so we can flag them in workspace mode
    if not member_only:
        r = slack_get("users.conversations", {"types": "public_channel", "limit": "200"}, token)
        if r.get("ok"):
            for c in r.get("channels", []):
                member_ids.add(c["id"])

    page = 0
    while page < max_pages:
        params: dict[str, Any] = {
            "types": "public_channel",
            "limit": str(PAGE_LIMIT),
            "exclude_archived": "true",
        }
        if cursor:
            params["cursor"] = cursor

        resp = slack_get(method, params, token)
        if not resp.get("ok"):
            return {
                "ok": False,
                "error": resp.get("error", "unknown_error"),
                "partial_channels": channels,
                "partial_count": len(channels),
            }

        for ch in resp.get("channels", []):
            channel_id = ch.get("id", "")
            channels.append({
                "id": channel_id,
                "name": ch.get("name", ""),
                "is_archived": ch.get("is_archived", False),
                "is_private": ch.get("is_private", False),
                "is_member": ch.get("is_member", False) or (channel_id in member_ids),
                "num_members": ch.get("num_members"),
                "topic": (ch.get("topic") or {}).get("value", "") if isinstance(ch.get("topic"), dict)
                         else ch.get("topic", ""),
                "purpose": (ch.get("purpose") or {}).get("value", "") if isinstance(ch.get("purpose"), dict)
                           else ch.get("purpose", ""),
            })

        cursor = (resp.get("response_metadata") or {}).get("next_cursor") or None
        page += 1
        if not cursor:
            break

    return {"ok": True, "channels": channels, "member_ids": member_ids}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query",
        required=True,
        help="Search query — matched against channel name, topic, and purpose",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Maximum number of results to return (default: 5)",
    )
    parser.add_argument(
        "--member-only",
        action="store_true",
        help="Restrict to channels the bot is a member of (faster, but misses channels "
             "the bot hasn't been added to)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=1,
        help="Minimum score to include in results (default: 1)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Max pagination pages for workspace-wide discovery (default: 5 = up to 1000 channels). "
             "Large workspaces may have thousands of channels; increase with care.",
    )
    args = parser.parse_args()

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print(json.dumps({"ok": False, "error": "missing_token"}))
        return 1

    fetch_result = fetch_all_channels(token, args.member_only, args.max_pages)
    if not fetch_result.get("ok"):
        print(json.dumps({
            "ok": False,
            "error": fetch_result.get("error"),
            "partial_count": len(fetch_result.get("partial_channels", [])),
        }))
        return 2

    channels = fetch_result["channels"]
    q_tokens = query_tokens(args.query)

    scored: list[tuple[int, list[str], dict[str, Any]]] = []
    for ch in channels:
        score, reasons = score_channel(ch, q_tokens)
        if score >= args.min_score:
            scored.append((score, reasons, ch))

    # Sort by score descending, then name alphabetically for ties
    scored.sort(key=lambda x: (-x[0], x[2].get("name", "")))

    results = [
        {
            "channel_id": ch["id"],
            "name": ch["name"],
            "is_member": ch.get("is_member", False),
            "num_members": ch.get("num_members"),
            "topic": ch.get("topic", ""),
            "purpose": ch.get("purpose", ""),
            "score": score,
            "match_reasons": reasons,
        }
        for score, reasons, ch in scored[: args.top]
    ]

    print(json.dumps({
        "ok": True,
        "query": args.query,
        "query_tokens": q_tokens,
        "total_searched": len(channels),
        "count": len(results),
        "discovery_mode": "member_only" if args.member_only else "workspace",
        "results": results,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
