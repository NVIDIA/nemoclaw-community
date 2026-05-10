#!/usr/bin/env bash
# Smoke-test the configured Hermes + Omni sandbox without launching the UI.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "$DIR/.." && pwd)"

if [[ -f "$EXAMPLE_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$EXAMPLE_DIR/.env"
  set +a
fi

SANDBOX="${SANDBOX:-my-hermes}"
HERMES_CLI="${HERMES_CLI:-nemohermes}"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

need ffmpeg
need openshell
need "$HERMES_CLI"

echo "→ checking sandbox: $SANDBOX"
status_out="$("$HERMES_CLI" "$SANDBOX" status 2>&1 | sed 's/\x1b\[[0-9;]*m//g')"
if ! grep -q "Phase:[[:space:]]*Ready" <<<"$status_out"; then
  echo "sandbox '$SANDBOX' is not Ready" >&2
  echo "$status_out" >&2
  exit 1
fi

tmp_video="$(mktemp /tmp/hermes-omni-smoke.XXXXXX.mp4)"
trap 'rm -f "$tmp_video"' EXIT

echo "→ creating synthetic video"
ffmpeg -y -f lavfi -i "testsrc=duration=10:size=320x240:rate=15" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v libx264 -pix_fmt yuv420p -shortest "$tmp_video" \
  -hide_banner -loglevel error

echo "→ uploading video into sandbox"
openshell sandbox upload "$SANDBOX" "$tmp_video" /tmp/

echo "→ running Omni analyzer"
openshell sandbox exec -n "$SANDBOX" -- python3 \
  "/sandbox/.hermes-data/workspace/omni-video-analyze.py" \
  "/tmp/$(basename "$tmp_video")" \
  "Describe this synthetic smoke-test clip in one sentence."

echo "✓ Hermes + Omni smoke test completed"
