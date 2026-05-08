#!/usr/bin/python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Validate Microsoft Graph API access for the outlook-email-search skill.

Fetches a live token from the token manager, decodes it to show what scopes
are present, then probes each Graph endpoint the skill uses. Run this when
debugging 403 errors or after changing auth config.

Usage (from host, token manager on localhost:8765):
    /usr/bin/python3 validate_graph_access.py \\
        --session-id f1ffdb3c-c2f5-475a-b81f-5b8109cf1285 \\
        --reply-to mpenn@nvidia.com \\
        --target-mailbox agt-mpenn@nvidia.com \\
        [--token-manager http://localhost:8765]

Usage (from sandbox, via sidecar):
    /usr/bin/python3 validate_graph_access.py \\
        --session-id "$OUTLOOK_SESSION_UUID" \\
        --reply-to "$OUTLOOK_REPLY_TO" \\
        --target-mailbox "$OUTLOOK_TARGET_MAILBOX" \\
        --sidecar "$MS_GRAPH_SIDECAR_URL" \\
        --token-manager http://host.docker.internal:8765
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _get(url: str, headers: dict | None = None, timeout: int = 20) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, body


def fetch_token(token_manager: str, session_id: str) -> str:
    url = f"{token_manager.rstrip('/')}/token?session_id={urllib.parse.quote(session_id)}"
    code, data = _get(url)
    if code != 200 or not isinstance(data, dict) or "access_token" not in data:
        print(f"{RED}Failed to fetch token from {url}: {code} {data}{RESET}")
        sys.exit(1)
    return data["access_token"]


def decode_jwt_scopes(token: str) -> str:
    """Decode the JWT payload to extract scopes without any crypto library."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return "(not a JWT)"
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        scp = payload.get("scp", payload.get("scope", ""))
        upn = payload.get("upn", payload.get("unique_name", "?"))
        exp = payload.get("exp")
        import datetime
        exp_str = datetime.datetime.utcfromtimestamp(exp).isoformat() + "Z" if exp else "?"
        return f"user={upn}  expires={exp_str}  scopes={scp}"
    except Exception as exc:
        return f"(decode error: {exc})"


def probe(label: str, url: str, token: str) -> bool:
    code, data = _get(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    ok = code == 200
    icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    print(f"  {icon} [{code}] {label}")
    if not ok:
        if isinstance(data, dict):
            err = data.get("error", {})
            msg = err.get("message", str(data))[:200] if isinstance(err, dict) else str(data)[:200]
            code_str = err.get("code", "?") if isinstance(err, dict) else "?"
            print(f"       {YELLOW}{code_str}: {msg}{RESET}")
        else:
            print(f"       {YELLOW}{str(data)[:200]}{RESET}")
    return ok


def probe_via_sidecar(label: str, path: str, sidecar: str) -> bool:
    """Probe via the credential sidecar (which injects the real token)."""
    url = f"{sidecar.rstrip('/')}/{path.lstrip('/')}"
    code, data = _get(url, headers={
        "Authorization": "Bearer MS_GRAPH_TOKEN_PLACEHOLDER_OUTLOOK",
        "Accept": "application/json",
    })
    ok = code == 200
    icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    print(f"  {icon} [{code}] {label} (via sidecar)")
    if not ok:
        if isinstance(data, dict):
            err = data.get("error", {})
            msg = err.get("message", str(data))[:200] if isinstance(err, dict) else str(data)[:200]
            code_str = err.get("code", "?") if isinstance(err, dict) else "?"
            print(f"       {YELLOW}{code_str}: {msg}{RESET}")
        else:
            print(f"       {YELLOW}{str(data)[:200]}{RESET}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Graph API access for outlook-email-search")
    parser.add_argument("--session-id",
                        default=os.environ.get("OUTLOOK_SESSION_UUID", ""),
                        help="Token manager session UUID")
    parser.add_argument("--reply-to",
                        default=os.environ.get("OUTLOOK_REPLY_TO", ""),
                        help="Human owner email (OUTLOOK_REPLY_TO)")
    parser.add_argument("--target-mailbox",
                        default=os.environ.get("OUTLOOK_TARGET_MAILBOX", ""),
                        help="Agent mailbox email (OUTLOOK_TARGET_MAILBOX)")
    parser.add_argument("--token-manager",
                        default="http://localhost:8765",
                        help="Token manager URL (default: http://localhost:8765)")
    parser.add_argument("--sidecar",
                        default=os.environ.get("MS_GRAPH_SIDECAR_URL", ""),
                        help="Sidecar URL if testing via sidecar (default: $MS_GRAPH_SIDECAR_URL)")
    args = parser.parse_args()

    if not args.session_id or args.session_id.startswith("openshell:"):
        print(f"{RED}--session-id required (or set OUTLOOK_SESSION_UUID){RESET}")
        return 1

    print(f"\n{BOLD}=== Outlook Graph API Validation ==={RESET}")
    print(f"Token manager : {args.token_manager}")
    print(f"Session ID    : {args.session_id[:8]}...")
    print(f"Reply-to      : {args.reply_to or '(not set)'}")
    print(f"Target mailbox: {args.target_mailbox or '(not set)'}")
    print(f"Sidecar       : {args.sidecar or '(not used — direct Graph calls)'}")

    # ── Fetch token ───────────────────────────────────────────────────────────
    print(f"\n{BOLD}1. Fetching token from token manager…{RESET}")
    token = fetch_token(args.token_manager, args.session_id)
    print(f"  {GREEN}✓{RESET} Token length: {len(token)} chars")
    info = decode_jwt_scopes(token)
    print(f"  {info}")

    has_mail_read = "Mail.Read" in info
    has_shared = "Mail.ReadWrite.Shared" in info
    if not has_mail_read:
        print(f"  {YELLOW}WARNING: Mail.Read not in token scopes — Graph calls will 403{RESET}")
    if not has_shared:
        print(f"  {YELLOW}NOTE: Mail.ReadWrite.Shared absent — cross-mailbox access may fail{RESET}")

    graph = "https://graph.microsoft.com/v1.0"

    # ── Direct Graph probes ───────────────────────────────────────────────────
    print(f"\n{BOLD}2. Direct Graph API probes (token from manager, no sidecar)…{RESET}")
    probe("/me (basic access)", f"{graph}/me", token)

    if args.target_mailbox and not args.target_mailbox.startswith("openshell:"):
        probe(f"/users/{args.target_mailbox}/inbox (agent mailbox)",
              f"{graph}/users/{args.target_mailbox}/mailFolders/inbox/messages?$top=1&$select=id,subject",
              token)

    if args.reply_to and not args.reply_to.startswith("openshell:"):
        probe(f"/users/{args.reply_to}/inbox (human mailbox — requires shared access)",
              f"{graph}/users/{args.reply_to}/mailFolders/inbox/messages?$top=1&$select=id,subject",
              token)
        probe(f"/users/{args.reply_to}/inbox with $search",
              f"{graph}/users/{args.reply_to}/mailFolders/inbox/messages?$search=%22test%22&$top=1&$select=id,subject",
              token)
        probe(f"/users/{args.reply_to}/inbox with $filter (date)",
              f"{graph}/users/{args.reply_to}/mailFolders/inbox/messages?$filter=receivedDateTime+ge+2026-04-01T00%3A00%3A00Z&$top=1&$select=id,subject",
              token)
        probe(f"/users/{args.reply_to}/messages with conversationId filter",
              f"{graph}/users/{args.reply_to}/messages?$filter=isRead+eq+false&$top=1&$select=id,subject,conversationId",
              token)

    # ── Sidecar probes ────────────────────────────────────────────────────────
    if args.sidecar:
        print(f"\n{BOLD}3. Sidecar probes (MS_GRAPH_TOKEN_PLACEHOLDER → live token)…{RESET}")

        code, data = _get(f"{args.sidecar.rstrip('/')}/v1.0/me",
                          headers={"Authorization": "Bearer WRONG_PLACEHOLDER", "Accept": "application/json"})
        if code in (401, 403):
            print(f"  {GREEN}✓{RESET} Sidecar reachable (wrong placeholder → {code}, expected)")
        elif code == 200:
            print(f"  {YELLOW}?{RESET} Sidecar reachable but returned 200 with wrong placeholder — "
                  "sidecar may not be checking the placeholder")
        else:
            print(f"  {RED}✗{RESET} Sidecar at {args.sidecar} returned {code}: {str(data)[:100]}")

        if args.reply_to and not args.reply_to.startswith("openshell:"):
            probe_via_sidecar(
                f"/users/{args.reply_to}/inbox",
                f"v1.0/users/{args.reply_to}/mailFolders/inbox/messages?$top=1&$select=id,subject",
                args.sidecar,
            )
            probe_via_sidecar(
                f"/users/{args.reply_to}/inbox with $search",
                f"v1.0/users/{args.reply_to}/mailFolders/inbox/messages?$search=%22test%22&$top=1",
                args.sidecar,
            )

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{BOLD}Done.{RESET}")
    if not args.sidecar:
        print(f"  Tip: add --sidecar $MS_GRAPH_SIDECAR_URL to also probe via the credential sidecar.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
