#!/usr/bin/env bash
# pdf-upload.sh — render a PDF into per-page PNGs on the host, then upload the
# directory into the OpenShell sandbox so Hermes/Omni can read it as a
# multi-image payload.
#
# Usage:
#   pdf-upload.sh /path/to/document.pdf
#
# After upload, paste this into Hermes:
#   What's the main argument in the document at <printed-sandbox-path>?
#
# Defaults:
#   sandbox : my-hermes   (override with SANDBOX env var)
set -euo pipefail

PDF="${1:-}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "$DIR/.." && pwd)"
if [[ -f "$EXAMPLE_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$EXAMPLE_DIR/.env"
    set +a
fi
SANDBOX="${SANDBOX:-my-hermes}"

if [[ -z "$PDF" || ! -f "$PDF" ]]; then
    echo "usage: $0 <pdf-file>" >&2
    exit 1
fi

if ! command -v pdftoppm >/dev/null; then
    echo "pdftoppm not found on host. Install poppler-utils:" >&2
    echo "  apt install -y poppler-utils" >&2
    exit 1
fi

if ! command -v openshell >/dev/null; then
    echo "openshell CLI not found on host" >&2
    exit 1
fi

BASE=$(basename "$PDF")
BASE="${BASE%.*}"
PAGES_DIR="/tmp/${BASE}-pages"
mkdir -p "$PAGES_DIR"
rm -f "$PAGES_DIR"/page-*.png 2>/dev/null || true

echo "→ rendering $PDF → $PAGES_DIR (150 dpi)"
pdftoppm -png -r 150 "$PDF" "$PAGES_DIR/page"

PAGE_COUNT=$(ls "$PAGES_DIR"/page-*.png 2>/dev/null | wc -l)
TOTAL_MB=$(du -sm "$PAGES_DIR" | cut -f1)
echo "  $PAGE_COUNT pages, ${TOTAL_MB} MB on disk"

echo "→ uploading $PAGES_DIR into sandbox '$SANDBOX'"
openshell sandbox upload "$SANDBOX" "$PAGES_DIR" "$PAGES_DIR"

echo
echo "✓ ready. In Hermes, paste:"
echo
echo "    Read the document at $PAGES_DIR — what's the main argument?"
echo
echo "Or run the skill directly:"
echo "    python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py $PAGES_DIR"
