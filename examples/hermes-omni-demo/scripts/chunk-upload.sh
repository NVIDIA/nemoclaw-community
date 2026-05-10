#!/usr/bin/env bash
# chunk-upload.sh — split a long video into ~2-min chunks at 480p and upload
# the chunk directory into the OpenShell sandbox.
#
# Usage:
#   chunk-upload.sh /path/to/long-video.mp4 [chunk-seconds]
#
# After upload, paste this into Hermes:
#   Analyze the video at <printed-sandbox-path> — what's happening?
#
# Defaults:
#   chunk seconds : 120
#   sandbox       : my-hermes   (override with SANDBOX env var)
set -euo pipefail

VIDEO="${1:-}"
CHUNK_SEC="${2:-120}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "$DIR/.." && pwd)"
if [[ -f "$EXAMPLE_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$EXAMPLE_DIR/.env"
    set +a
fi
SANDBOX="${SANDBOX:-my-hermes}"

if [[ -z "$VIDEO" || ! -f "$VIDEO" ]]; then
    echo "usage: $0 <video> [chunk-seconds]" >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
    echo "ffmpeg/ffprobe not found on host" >&2
    exit 1
fi

if ! command -v openshell >/dev/null; then
    echo "openshell CLI not found on host" >&2
    exit 1
fi

BASE=$(basename "$VIDEO")
BASE="${BASE%.*}"
CHUNK_DIR="/tmp/${BASE}-chunks"
mkdir -p "$CHUNK_DIR"
rm -f "$CHUNK_DIR"/chunk_*.mp4 "$CHUNK_DIR"/chunks.json 2>/dev/null || true

echo "→ probing $VIDEO"
DURATION=$(ffprobe -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 "$VIDEO")
echo "  duration: ${DURATION}s, chunking into ${CHUNK_SEC}s segments at 480p"

# Re-encode with regular keyframes so each chunk is independently decodable.
# 480p, 24fps, CRF 28, AAC 64k — keeps each chunk under the gateway's body cap.
ffmpeg -y -i "$VIDEO" \
    -vf "scale=854:480,fps=24" \
    -c:v libx264 -crf 28 -preset veryfast \
    -force_key_frames "expr:gte(t,n_forced*${CHUNK_SEC})" \
    -c:a aac -b:a 64k \
    -f segment -segment_time "$CHUNK_SEC" -reset_timestamps 1 \
    -segment_format mp4 \
    "${CHUNK_DIR}/chunk_%03d.mp4" \
    -hide_banner -loglevel warning

echo "→ writing chunks.json manifest"
python3 - "$VIDEO" "$CHUNK_DIR" <<'PY'
import json, os, subprocess, sys
src, chunk_dir = sys.argv[1], sys.argv[2]
files = sorted(f for f in os.listdir(chunk_dir) if f.startswith("chunk_") and f.endswith(".mp4"))
manifest = {"source": src, "chunks": []}
offset = 0.0
for f in files:
    path = os.path.join(chunk_dir, f)
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ]).decode().strip()
    dur = float(out)
    manifest["chunks"].append({"name": f, "start": offset, "end": offset + dur})
    offset += dur
with open(os.path.join(chunk_dir, "chunks.json"), "w") as out:
    json.dump(manifest, out, indent=2)
total_mb = sum(os.path.getsize(os.path.join(chunk_dir, c["name"])) for c in manifest["chunks"]) / 1e6
print(f"  {len(manifest['chunks'])} chunks, {offset:.1f}s total, {total_mb:.1f} MB on disk")
PY

echo "→ uploading $CHUNK_DIR into sandbox '$SANDBOX'"
openshell sandbox upload "$SANDBOX" "$CHUNK_DIR" "$CHUNK_DIR"

echo
echo "✓ ready. In Hermes, paste:"
echo
echo "    Analyze the video at $CHUNK_DIR — what's happening?"
echo
echo "Or run the skill directly:"
echo "    python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py $CHUNK_DIR"
