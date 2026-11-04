# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Agent-side client for the synthetic mail tool; it contains no guard logic."""

import argparse
import json
import os
import urllib.error
import urllib.request

from scenario import SCENARIOS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inbox", "send"])
    parser.add_argument("message", nargs="?")
    args = parser.parse_args()
    base = os.environ["TOOL_SERVICE_URL"].rstrip("/")
    scenario = SCENARIOS[os.environ.get("TASK_SCENARIO", "recovery-code")]
    if args.operation == "send":
        if not args.message:
            parser.error("send requires a JSON message with to, subject and body")
        data = json.dumps(json.loads(args.message)).encode()
        request = urllib.request.Request(
            base + scenario.action_path,
            data=data,
            headers={"Content-Type": "application/json"},
        )
    else:
        request = urllib.request.Request(base + scenario.read_path)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(response.read(256 * 1024).decode())
    except urllib.error.HTTPError as exc:
        print(exc.read(65536).decode())
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
