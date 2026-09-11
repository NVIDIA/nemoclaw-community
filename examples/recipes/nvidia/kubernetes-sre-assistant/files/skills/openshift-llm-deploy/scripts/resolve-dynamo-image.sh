#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Resolve only official Dynamo backend images and preserve chart defaults on
# any release-metadata or registry-verification failure.
set -eu

usage() {
  echo "usage: resolve-dynamo-image.sh --default-image IMAGE --backend vllm|trtllm --default-runtime-version VERSION [--model MODEL] [--overrides-file FILE]" >&2
  exit 64
}

default_image=
backend=
default_runtime_version=
model_id=
overrides_file=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --default-image) default_image=${2:-}; shift 2 ;;
    --backend) backend=${2:-}; shift 2 ;;
    --default-runtime-version) default_runtime_version=${2:-}; shift 2 ;;
    --model) model_id=${2:-}; shift 2 ;;
    --overrides-file) overrides_file=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$default_image" ] && [ -n "$default_runtime_version" ] || usage
case "$backend" in vllm|trtllm) ;; *) usage ;; esac

emit_result() {
  printf '%s\n' \
    "DYNAMO_IMAGE=$1" \
    "DYNAMO_IMAGE_SOURCE=$2" \
    "DYNAMO_IMAGE_REASON=$3" \
    "DYNAMO_RUNTIME_VERSION=$4"
}

extract_override() {
  python3 - "$1" "$2" "$3" <<'PY'
import re
import sys

path, model, image_key = sys.argv[1:]
try:
    lines = open(path, encoding="utf-8").read().splitlines()
except OSError:
    raise SystemExit(1)

def indent(line):
    return len(line) - len(line.lstrip(" "))

root_indent = model_indent = None
values = {}
for raw in lines:
    stripped = raw.strip()
    if not stripped or stripped.startswith("#") or ":" not in stripped:
        continue
    key, value = stripped.split(":", 1)
    key = key.strip().strip("'\"")
    value = value.strip().strip("'\"")
    level = indent(raw)
    if root_indent is None:
        if key == "modelRuntimeOverrides" and not value:
            root_indent = level
        continue
    if level <= root_indent:
        break
    if model_indent is None:
        if key == model and not value:
            model_indent = level
        continue
    if level <= model_indent:
        break
    if key in {image_key, "dynamoRuntimeVersionOverride"}:
        values[key] = value

image = values.get(image_key, "")
version = values.get("dynamoRuntimeVersionOverride", "")
if not image or not version:
    raise SystemExit(1)
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9.-]+)?", version):
    raise SystemExit(1)
if "@sha256:" in image:
    if not re.search(r"@sha256:[0-9a-f]{64}$", image):
        raise SystemExit(1)
elif not re.search(r":[A-Za-z0-9._-]+$", image):
    raise SystemExit(1)
print(image)
print(version)
PY
}

if [ -n "$model_id" ] && [ -n "$overrides_file" ] && [ -f "$overrides_file" ]; then
  case "$backend" in
    vllm) override_key=dynamoVllmRuntimeImage ;;
    trtllm) override_key=dynamoTrtllmRuntimeImage ;;
  esac
  override=$(extract_override "$overrides_file" "$model_id" "$override_key" 2>/dev/null || true)
  override_image=$(printf '%s\n' "$override" | sed -n '1p')
  override_version=$(printf '%s\n' "$override" | sed -n '2p')
  if [ -n "$override_image" ] && [ -n "$override_version" ]; then
    emit_result "$override_image" model-override exact-model-runtime-image "$override_version"
    exit 0
  fi
fi

workdir=$(mktemp -d "${TMPDIR:-/tmp}/hermes-dynamo-resolve.XXXXXX") || exit 1
trap 'rm -rf "$workdir"' EXIT HUP INT TERM
release_json="$workdir/release.json"
if ! curl --fail --silent --show-error --location --max-time 15 \
  --output "$release_json" \
  https://api.github.com/repos/ai-dynamo/dynamo/releases/latest 2>/dev/null; then
  emit_result "$default_image" chart-default release-metadata-unavailable "$default_runtime_version"
  exit 0
fi
release_version=$(python3 - "$release_json" <<'PY'
import json
import re
import sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)
tag = data.get("tag_name", "")
if data.get("draft") or data.get("prerelease") or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
    raise SystemExit(1)
print(tag[1:])
PY
) || release_version=
if [ -z "$release_version" ]; then
  emit_result "$default_image" chart-default stable-release-unavailable "$default_runtime_version"
  exit 0
fi

if printf '%s\n' "$default_image" | grep -Eq ":$release_version@sha256:[0-9a-f]{64}$"; then
  emit_result "$default_image" github-latest-release chart-default-already-matches-release "$release_version"
  exit 0
fi

case "$backend" in
  vllm) repository=nvidia/ai-dynamo/vllm-runtime ;;
  trtllm) repository=nvidia/ai-dynamo/tensorrtllm-runtime ;;
esac
auth_json="$workdir/auth.json"
manifest_json="$workdir/manifest.json"
headers="$workdir/headers"
if ! curl --fail --silent --show-error --location --max-time 15 \
  --output "$auth_json" \
  "https://nvcr.io/proxy_auth?scope=repository:$repository:pull&service=nvcr.io" 2>/dev/null; then
  emit_result "$default_image" chart-default registry-auth-unavailable "$default_runtime_version"
  exit 0
fi
registry_token=$(python3 - "$auth_json" <<'PY'
import json
import sys
try:
    token = json.load(open(sys.argv[1], encoding="utf-8")).get("token", "")
except (OSError, json.JSONDecodeError):
    token = ""
if not isinstance(token, str) or not token or len(token) > 8192:
    raise SystemExit(1)
print(token)
PY
) || registry_token=
if [ -z "$registry_token" ] || ! curl --fail --silent --show-error --location --max-time 15 \
  --header "Authorization: Bearer $registry_token" \
  --header "Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json" \
  --dump-header "$headers" --output "$manifest_json" \
  "https://nvcr.io/v2/$repository/manifests/$release_version" 2>/dev/null; then
  emit_result "$default_image" chart-default registry-manifest-unavailable "$default_runtime_version"
  exit 0
fi
digest=$(python3 - "$manifest_json" "$headers" <<'PY'
import hashlib
import json
import re
import sys
body = open(sys.argv[1], "rb").read()
try:
    data = json.loads(body)
    headers = open(sys.argv[2], encoding="utf-8", errors="replace").read()
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)
match = re.search(r"(?im)^Docker-Content-Digest:\s*(sha256:[0-9a-f]{64})\s*$", headers)
if not match or match.group(1) != "sha256:" + hashlib.sha256(body).hexdigest():
    raise SystemExit(1)
if not any(
    isinstance(item, dict)
    and item.get("platform", {}).get("os") == "linux"
    and item.get("platform", {}).get("architecture") == "amd64"
    for item in data.get("manifests", [])
):
    raise SystemExit(1)
print(match.group(1))
PY
) || digest=
if [ -z "$digest" ]; then
  emit_result "$default_image" chart-default registry-digest-verification-failed "$default_runtime_version"
  exit 0
fi
emit_result "nvcr.io/$repository:$release_version@$digest" github-latest-release stable-release-and-index-digest-verified "$release_version"
