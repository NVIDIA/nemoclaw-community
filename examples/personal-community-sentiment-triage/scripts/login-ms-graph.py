#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run Microsoft device-code auth and print token material as JSON."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def post_form(url: str, fields: dict[str, str], timeout: int = 30) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"error": f"http_{exc.code}", "error_description": payload}
        data["_http_status"] = exc.code
        return data


BOLD = "\033[1m" if sys.stderr.isatty() else ""
CYAN = "\033[36m" if sys.stderr.isatty() else ""
GREEN = "\033[32m" if sys.stderr.isatty() else ""
DIM = "\033[2m" if sys.stderr.isatty() else ""
RESET = "\033[0m" if sys.stderr.isatty() else ""


def _print_banner(verification: str, user_code: str, login_hint: str | None) -> None:
    width = 68
    bar = "═" * width
    print("", file=sys.stderr)
    print(f"{CYAN}{bar}{RESET}", file=sys.stderr)
    print(f"  {BOLD}Microsoft Graph device-code login{RESET}", file=sys.stderr)
    print(f"{CYAN}{bar}{RESET}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"  {DIM}1.{RESET} Open this URL in your browser:", file=sys.stderr)
    print(f"        {BOLD}{verification}{RESET}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"  {DIM}2.{RESET} Enter this code:", file=sys.stderr)
    print(f"        {BOLD}{CYAN}{user_code}{RESET}", file=sys.stderr)
    if login_hint:
        print("", file=sys.stderr)
        print(f"  {DIM}3.{RESET} Sign in as: {BOLD}{login_hint}{RESET}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"{CYAN}{bar}{RESET}", file=sys.stderr)
    print(f"  Waiting for browser confirmation (Ctrl-C to cancel)...", file=sys.stderr)
    print("", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Authenticate to Microsoft Graph with device code")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--login-hint", default=None,
                        help="Mailbox to display as the suggested sign-in account (display only).")
    args = parser.parse_args()

    scopes = args.scope or ["offline_access", "https://graph.microsoft.com/.default"]
    scope = " ".join(scopes)
    base = f"https://login.microsoftonline.com/{args.tenant_id}/oauth2/v2.0"

    device = post_form(
        f"{base}/devicecode",
        {"client_id": args.client_id, "scope": scope},
    )
    if "device_code" not in device:
        print(json.dumps(device, indent=2), file=sys.stderr)
        return 1

    verification = device.get("verification_uri") or device.get("verification_url")
    user_code = device.get("user_code")
    _print_banner(verification, user_code, args.login_hint)

    token_url = f"{base}/token"
    deadline = time.monotonic() + args.timeout
    interval = int(device.get("interval", 5))
    while time.monotonic() < deadline:
        time.sleep(max(interval, 1))
        token = post_form(
            token_url,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": args.client_id,
                "device_code": device["device_code"],
            },
        )
        if "access_token" in token:
            now_ms = int(time.time() * 1000)
            expires_in = int(token.get("expires_in", 3600))
            result = {
                "access_token": token["access_token"],
                "refresh_token": token.get("refresh_token", ""),
                "expires_at_ms": now_ms + expires_in * 1000,
                "scope": token.get("scope", scope),
                "token_type": token.get("token_type", "Bearer"),
            }
            if not result["refresh_token"]:
                print("", file=sys.stderr)
                print(f"{BOLD}Token response did not include refresh_token.{RESET} Ensure offline_access is requested.", file=sys.stderr)
                return 1
            print("", file=sys.stderr)
            print(f"  {GREEN}✓{RESET} Microsoft Graph authenticated", file=sys.stderr)
            print("", file=sys.stderr)
            print(json.dumps(result, indent=2))
            return 0

        error = token.get("error")
        if error == "authorization_pending":
            print(".", end="", file=sys.stderr, flush=True)
            continue
        if error == "slow_down":
            interval += 5
            continue

        print("", file=sys.stderr)
        print(json.dumps(token, indent=2), file=sys.stderr)
        return 1

    print("", file=sys.stderr)
    print("Timed out waiting for Microsoft device-code authentication.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
