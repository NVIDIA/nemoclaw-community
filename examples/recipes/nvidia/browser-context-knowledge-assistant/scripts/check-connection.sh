#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail

ORIGIN="${1:-}"
[ -n "$ORIGIN" ] || {
  printf 'Usage: %s HERMES_ORIGIN\n' "$0" >&2
  exit 2
}

ORIGIN="$(python3 - "$ORIGIN" <<'PY'
import sys
from urllib.parse import urlsplit

value = sys.argv[1]
parsed = urlsplit(value)
loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
valid_scheme = parsed.scheme == "https" or (parsed.scheme == "http" and loopback)
if (
    not valid_scheme
    or not parsed.hostname
    or parsed.username
    or parsed.password
    or parsed.query
    or parsed.fragment
    or parsed.path not in {"", "/"}
):
    raise SystemExit("ERROR: use an exact HTTPS origin or an HTTP loopback origin")
try:
    parsed.port
except ValueError as error:
    raise SystemExit(f"ERROR: invalid origin port: {error}")
print(f"{parsed.scheme}://{parsed.netloc}")
PY
)"

LOOPBACK="$(python3 - "$ORIGIN" <<'PY'
import sys
from urllib.parse import urlsplit

print("1" if urlsplit(sys.argv[1]).hostname in {"127.0.0.1", "localhost", "::1"} else "0")
PY
)"

probe() {
  local label url status
  label="$1"
  url="$2"
  status="$(curl --silent --show-error --output /dev/null \
    --write-out '%{http_code}' --max-time 10 "$url")" || {
      printf '%s: unreachable\n' "$label"
      return 1
    }
  printf '%s: HTTP %s\n' "$label" "$status"
  case "$status" in
    200|302|401|403) return 0 ;;
    *) return 1 ;;
  esac
}

probe 'Hermes dashboard route' "$ORIGIN/"

if [[ "$LOOPBACK" == 1 ]]; then
  python3 - "$ORIGIN" <<'PY'
import json
import re
import sys
import urllib.error
import urllib.request

origin = sys.argv[1]

try:
    with urllib.request.urlopen(f"{origin}/api/status", timeout=10) as response:
        print(f"Hermes status route: HTTP {response.status}")
        status = json.load(response)
except (OSError, urllib.error.URLError, ValueError) as error:
    raise SystemExit(f"ERROR: Hermes status route is unavailable: {error}") from None

if status.get("auth_required") is not False:
    providers = ", ".join(status.get("auth_providers") or []) or "none"
    raise SystemExit(
        "ERROR: loopback development mode is not active; "
        f"Hermes requires authentication (providers: {providers})"
    )

try:
    with urllib.request.urlopen(f"{origin}/", timeout=10) as response:
        dashboard = response.read(2_000_001).decode("utf-8", "replace")
except (OSError, urllib.error.URLError) as error:
    raise SystemExit(f"ERROR: Hermes dashboard route is unavailable: {error}") from None

match = re.search(
    r'window\.__HERMES_SESSION_TOKEN__\s*=\s*("(?:\\.|[^"\\])*")',
    dashboard,
)
if not match:
    raise SystemExit("ERROR: Hermes did not provide its ephemeral loopback session token")
try:
    token = json.loads(match.group(1))
except (TypeError, ValueError):
    raise SystemExit("ERROR: Hermes provided an invalid loopback session token") from None
if not isinstance(token, str) or not 16 <= len(token) <= 512:
    raise SystemExit("ERROR: Hermes provided an invalid loopback session token")

request = urllib.request.Request(
    f"{origin}/api/plugins/ask-nemoclaw/conversations",
    headers={"X-Hermes-Session-Token": token},
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(f"Ask NemoClaw API route: HTTP {response.status}")
        if response.status != 200:
            raise SystemExit("ERROR: Ask NemoClaw API route did not accept the loopback session")
except urllib.error.HTTPError as error:
    raise SystemExit(f"ERROR: Ask NemoClaw API route returned HTTP {error.code}") from None
except (OSError, urllib.error.URLError) as error:
    raise SystemExit(f"ERROR: Ask NemoClaw API route is unavailable: {error}") from None
PY
  printf 'Loopback development connection is ready. No Hermes login is required.\n'
else
  probe 'Ask NemoClaw API route' "$ORIGIN/api/plugins/ask-nemoclaw/conversations"
  printf 'The route responded. Complete authentication in Chrome to verify the signed-in extension session.\n'
fi
