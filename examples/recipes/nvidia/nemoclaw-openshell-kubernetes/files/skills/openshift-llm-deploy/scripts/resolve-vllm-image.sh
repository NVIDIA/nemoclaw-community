#!/bin/sh
# Resolve a standard vLLM image without deriving image tags from model names.
# Priority:
#   1. Exact, chart-owned standardVllmImage model override
#   2. Latest stable vLLM GitHub release, verified and digest-pinned via Docker Hub
#   3. Chart default image
set -eu

usage() {
  echo "usage: resolve-vllm-image.sh --default-image IMAGE [--model MODEL_ID] [--overrides-file FILE]" >&2
  exit 64
}

default_image=
model_id=
overrides_file=

while [ "$#" -gt 0 ]; do
  case "$1" in
    --default-image) default_image=${2:-}; shift 2 ;;
    --model) model_id=${2:-}; shift 2 ;;
    --overrides-file) overrides_file=${2:-}; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[ -n "$default_image" ] || usage

emit_result() {
  image=$1
  source=$2
  reason=$3
  printf '%s\n' \
    "VLLM_IMAGE=$image" \
    "VLLM_IMAGE_SOURCE=$source" \
    "VLLM_IMAGE_REASON=$reason"
}

extract_model_override() {
  file=$1
  wanted_model=$2
  wanted_key=$3
  python3 - "$file" "$wanted_model" "$wanted_key" <<'PY'
from __future__ import annotations

import re
import sys


def indentation(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


path, wanted_model, wanted_key = sys.argv[1:]
try:
    lines = open(path, encoding="utf-8").read().splitlines()
except OSError:
    raise SystemExit(1)

overrides_indent = None
model_indent = None
for raw_line in lines:
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    indent = indentation(raw_line)
    key, separator, value = stripped.partition(":")
    if not separator:
        continue
    key = key.strip().strip('"\'')
    if overrides_indent is None:
        if key == "modelRuntimeOverrides" and not value.strip():
            overrides_indent = indent
        continue
    if indent <= overrides_indent:
        break
    if model_indent is None:
        if key == wanted_model and not value.strip():
            model_indent = indent
        continue
    if indent <= model_indent:
        break
    if key != wanted_key:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if re.search(r"\s", value) or "/" not in value:
        raise SystemExit(1)
    if "@sha256:" in value:
        if not re.search(r"@sha256:[0-9a-f]{64}$", value):
            raise SystemExit(1)
    elif ":" not in value.rsplit("/", 1)[-1]:
        raise SystemExit(1)
    print(value)
    raise SystemExit(0)
raise SystemExit(1)
PY
}

# An exact full-image override is an explicit recipe. It is not reinterpreted
# as a tag and does not require a network lookup.
if [ -n "$model_id" ] && [ -n "$overrides_file" ] && [ -f "$overrides_file" ]; then
  model_image=$(extract_model_override "$overrides_file" "$model_id" standardVllmImage 2>/dev/null || true)
  if [ -n "$model_image" ]; then
    emit_result "$model_image" model-override exact-model-runtime-image
    exit 0
  fi
fi

workdir=$(mktemp -d "${TMPDIR:-/tmp}/hermes-vllm-resolve.XXXXXX") || exit 1
trap 'rm -rf "$workdir"' EXIT HUP INT TERM
release_json="$workdir/release.json"
tag_json="$workdir/tag.json"

parse_stable_release_json() {
  python3 - "$1" <<'PY'
import json
import re
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)

tag = payload.get("tag_name", "")
if payload.get("draft") or payload.get("prerelease"):
    raise SystemExit(1)
if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
    raise SystemExit(1)
print(tag)
PY
}

release_tag=
if curl --fail --silent --show-error --location --max-time 15 \
  --output "$release_json" \
  'https://api.github.com/repos/vllm-project/vllm/releases/latest' 2>/dev/null; then
  release_tag=$(parse_stable_release_json "$release_json" 2>/dev/null || true)
fi

# GitHub's unauthenticated API is rate-limited. The public redirect is a
# credential-free fallback, but it is accepted only for an exact stable tag.
if [ -z "$release_tag" ]; then
  release_url=$(curl --fail --silent --show-error --location --max-time 15 \
    --output /dev/null --write-out '%{url_effective}' \
    'https://github.com/vllm-project/vllm/releases/latest' 2>/dev/null || true)
  release_tag=$(printf '%s\n' "$release_url" | python3 -c '
import re
import sys

url = sys.stdin.read().strip()
match = re.fullmatch(r"https://github\.com/vllm-project/vllm/releases/tag/(v[0-9]+\.[0-9]+\.[0-9]+)", url)
if match:
    print(match.group(1))
' || true)
fi

if [ -n "$release_tag" ] && curl --fail --silent --show-error --location --max-time 15 \
  --output "$tag_json" \
  "https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags/$release_tag" 2>/dev/null; then
  release_digest=$(python3 - "$tag_json" "$release_tag" <<'PY'
import json
import re
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)

tag = sys.argv[2]
digest = payload.get("digest", "")
images = payload.get("images", [])
has_linux_amd64 = any(
    image.get("os") == "linux" and image.get("architecture") == "amd64"
    for image in images
    if isinstance(image, dict)
)
if payload.get("name") != tag or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or not has_linux_amd64:
    raise SystemExit(1)
print(digest)
PY
) || true
  if [ -n "$release_digest" ]; then
    emit_result \
      "docker.io/vllm/vllm-openai:$release_tag@$release_digest" \
      github-latest-release \
      stable-release-tag-and-linux-amd64-index-digest-verified
    exit 0
  fi
fi

emit_result \
  "$default_image" \
  chart-default \
  stable-release-or-registry-digest-unavailable
exit 0
