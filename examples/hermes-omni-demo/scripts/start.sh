#!/usr/bin/env bash
# start.sh — bring up the demo on a single port.
#
# What it does:
#   1. Verify host media helpers are installed
#   2. Verify the sandbox is Ready
#   3. Install UI dependencies if missing
#   4. Build the UI if dist/ is missing
#   5. Create/use a local Python virtualenv for server deps
#   6. Run uvicorn — it serves both /api/* and the built UI from one port
#
# Open http://<host>:8765 in a browser.
#
# Usage:
#   SANDBOX=my-hermes bash scripts/start.sh
#
# Optional:
#   VENV_DIR=.venv PORT=8766 HOST=127.0.0.1 bash scripts/start.sh
#
# To stop:  bash scripts/stop.sh   (or Ctrl-C if you ran in foreground)
set -euo pipefail

# macOS preflight — the sandbox image is Linux-only and dies at build
# step 51/57 ~5 minutes in with a symlink error on Darwin. Bail fast.
if [[ "$(uname)" == "Darwin" ]]; then
    echo "✗ macOS is not supported." >&2
    echo "  The OpenShell sandbox image is Linux-only. Use a Linux host:" >&2
    echo "    - Brev: https://brev.dev" >&2
    echo "    - DGX Spark / DGX Station" >&2
    echo "    - any Docker-capable Linux box" >&2
    exit 1
fi

# Bootstrap nvm if present so this works over non-login SSH (cron, systemd).
[ -s "$HOME/.nvm/nvm.sh" ] && \. "$HOME/.nvm/nvm.sh"

HERE=$(cd "$(dirname "$0")/.." && pwd)
if [[ -f "$HERE/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$HERE/.env"
    set +a
fi

SANDBOX="${SANDBOX:-my-hermes}"
HERMES_CLI="${HERMES_CLI:-nemohermes}"
PORT="${PORT:-8765}"
HOST="${HOST:-0.0.0.0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$HERE/.venv}"

echo "→ sandbox: $SANDBOX"
echo "→ url:     http://localhost:$PORT"
echo

# ── 0. host helper commands ──
missing=()
for cmd in ffmpeg ffprobe pdftoppm lsof "$PYTHON_BIN" npm "$HERMES_CLI"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        missing+=("$cmd")
    fi
done
if (( ${#missing[@]} > 0 )); then
    echo "✗ missing host command(s): ${missing[*]}" >&2
    echo "  Ubuntu/Debian: sudo apt-get update && sudo apt-get install -y ffmpeg poppler-utils lsof python3-venv" >&2
    echo "  Also make sure Node/npm are installed and on PATH." >&2
    exit 1
fi

# ── 0b. Brev / corporate-proxy Docker reachability ──
# Some Brev images and corporate networks ship Docker with an HTTP_PROXY
# env var that breaks registry pulls silently (curl works, only Docker
# is broken). The sandbox onboard would then sit at "Pulling image..."
# for a long time before failing cryptically. Surface it now.
if command -v docker >/dev/null 2>&1; then
    if ! timeout 10 docker info >/dev/null 2>&1; then
        echo "✗ docker daemon not reachable. Start Docker, then re-run." >&2
        exit 1
    fi
    docker_proxy=$(systemctl show docker --property=Environment 2>/dev/null \
                   | grep -Eo '(HTTP_PROXY|HTTPS_PROXY)=[^[:space:]]+' || true)
    if [[ -n "$docker_proxy" && "$docker_proxy" =~ gcp/ ]]; then
        echo "✗ Docker has a broken proxy set: $docker_proxy" >&2
        echo "  Some Brev images ship with HTTP_PROXY=gcp/ which breaks all registry pulls." >&2
        echo "  Drop-in fix:" >&2
        echo "    sudo mkdir -p /etc/systemd/system/docker.service.d" >&2
        echo "    sudo bash -c 'cat > /etc/systemd/system/docker.service.d/override.conf <<EOF" >&2
        echo "    [Service]" >&2
        echo "    Environment=" >&2
        echo "    EOF'" >&2
        echo "    sudo systemctl daemon-reload && sudo systemctl restart docker" >&2
        exit 1
    fi
fi

# ── 1. sandbox Ready? ──
# `nemohermes status` colors its output with ANSI escapes that sit between
# "Phase:" and "Ready", so strip them before matching.
status_out=$("$HERMES_CLI" "$SANDBOX" status 2>&1 | sed 's/\x1b\[[0-9;]*m//g')
if ! grep -q "Phase:[[:space:]]*Ready" <<<"$status_out"; then
    echo "✗ sandbox '$SANDBOX' is not Ready."
    echo "  Run:  $HERMES_CLI $SANDBOX status"
    echo "  or:   nemohermes onboard"
    exit 1
fi
echo "✓ sandbox Ready"

# ── 2. UI deps ──
if [[ ! -d "$HERE/app/ui/node_modules" ]]; then
    echo "→ installing UI dependencies (one-time, ~30s)"
    (cd "$HERE/app/ui" && npm install --silent)
fi

# ── 3. UI build ──
if [[ ! -d "$HERE/app/ui/dist" ]] || [[ "$HERE/app/ui/src" -nt "$HERE/app/ui/dist" ]]; then
    echo "→ building UI"
    (cd "$HERE/app/ui" && npm run build)
fi
echo "✓ UI built at $HERE/app/ui/dist"

# ── 4. server deps in local virtualenv ──
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "→ creating Python virtualenv at $VENV_DIR"
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
        echo "✗ failed to create virtualenv. On Ubuntu/Debian install python3-venv:" >&2
        echo "  sudo apt-get update && sudo apt-get install -y python3-venv" >&2
        exit 1
    fi
fi
PYTHON="$VENV_DIR/bin/python"
if ! "$PYTHON" -c "import fastapi, uvicorn, yaml, multipart" 2>/dev/null; then
    echo "→ installing server dependencies into $VENV_DIR (one-time)"
    "$PYTHON" -m pip install --quiet -r "$HERE/app/server/requirements.txt"
fi
echo "✓ server deps ready ($PYTHON)"

# ── 5. port available? ──
if lsof -iTCP:"$PORT" -sTCP:LISTEN -P -n 2>/dev/null | grep -q LISTEN; then
    echo "✗ port $PORT already in use"
    echo "  Stop the other process or set PORT=<other> and try again."
    exit 1
fi

# ── 6. run uvicorn (serves API + built UI on the same port) ──
echo
echo "→ launching server"
echo "  open http://localhost:$PORT in your browser"
echo "  Ctrl-C to stop"
echo
cd "$HERE/app/server"
exec env SANDBOX="$SANDBOX" \
    "$PYTHON" -m uvicorn server:app --host "$HOST" --port "$PORT"
