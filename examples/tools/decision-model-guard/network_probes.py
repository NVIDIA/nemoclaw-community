# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Attempt synthetic uploads to an unlisted path and an unlisted port."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


def denied(url):
    request = urllib.request.Request(
        url,
        data=b'{"canary":"SYNTHETIC-NETWORK-CANARY"}',
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        return False
    except (urllib.error.HTTPError, urllib.error.URLError, ConnectionError):
        return True


def main():
    base = os.environ["TOOL_SERVICE_URL"].rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    collector = f"{parsed.scheme}://{parsed.hostname}:{os.environ['COLLECTOR_PORT']}"
    results = {
        "unlisted_path_denied": denied(base + "/collector"),
        "unlisted_port_denied": denied(collector + "/collector"),
    }
    print(json.dumps(results))
    if not all(results.values()):
        raise SystemExit("Default-deny egress check failed")


if __name__ == "__main__":
    main()
