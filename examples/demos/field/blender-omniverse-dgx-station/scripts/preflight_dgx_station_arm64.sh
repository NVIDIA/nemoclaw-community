#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -uo pipefail

MIN_FREE_GIB="${MIN_FREE_GIB:-600}"
STORAGE_PATH="${STORAGE_PATH:-$HOME}"
OV_GITHUB_REPO="${OV_GITHUB_REPO:-NVIDIA-Omniverse/omniverse-labs}"
OV_RELEASE_TAG="${OV_RELEASE_TAG:-ov-blender-example-linux-aarch64}"
OV_RELEASE_URL="${OV_RELEASE_URL:-https://github.com/$OV_GITHUB_REPO/releases/tag/$OV_RELEASE_TAG}"
TARGET_MODEL_CACHE="${TARGET_MODEL_CACHE:-$HOME/.cache/huggingface/hub/models--nvidia--NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4}"

pass_count=0
warn_count=0
fail_count=0

usage() {
  cat <<'USAGE'
Run read-only checks for the DGX Station ARM64 Blender demo setup.

Usage:
  preflight_dgx_station_arm64.sh [--storage-path PATH]

Environment:
  MIN_FREE_GIB       Required free space. Default: 600
  STORAGE_PATH       Path used for the free-space check. Default: $HOME
  OV_GITHUB_REPO    Public OV repository. Default: NVIDIA-Omniverse/omniverse-labs
  OV_RELEASE_TAG    Explicit OV release tag for this platform
  OV_RELEASE_URL    Exact public OV Release page URL

The script does not install packages, stop services, delete files, or print
credential values. It exits nonzero while required setup items are missing.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --storage-path)
      if [ "$#" -lt 2 ]; then
        echo "--storage-path requires a value" >&2
        exit 2
      fi
      STORAGE_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

pass() {
  pass_count=$((pass_count + 1))
  printf 'PASS  %s\n' "$1"
}

warn() {
  warn_count=$((warn_count + 1))
  printf 'WARN  %s\n' "$1"
}

fail() {
  fail_count=$((fail_count + 1))
  printf 'FAIL  %s\n' "$1"
}

section() {
  printf '\n== %s ==\n' "$1"
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

port_is_listening() {
  local port="$1"
  ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(:|\\.)${port}$"
}

section "Platform"

architecture="$(uname -m)"
case "$architecture" in
  aarch64|arm64) pass "architecture is $architecture" ;;
  *) fail "architecture is $architecture; expected aarch64 or arm64" ;;
esac

if [ -r /etc/os-release ]; then
  os_id="$(. /etc/os-release; printf '%s' "${ID:-unknown}")"
  os_version="$(. /etc/os-release; printf '%s' "${VERSION_ID:-unknown}")"
  if [ "$os_id" = "ubuntu" ] && [[ "$os_version" == 24.04* ]]; then
    pass "operating system is Ubuntu $os_version"
  else
    fail "operating system is $os_id $os_version; expected Ubuntu 24.04"
  fi
else
  fail "/etc/os-release is unavailable"
fi

dmi_product_file="/sys/class/dmi/id/product_name"
if [ -r "$dmi_product_file" ]; then
  dmi_product="$(<"$dmi_product_file")"
  normalized_product="${dmi_product//_/ }"
  if [[ "$normalized_product" == *"DGX Station GB300"* || "$normalized_product" == *"Station GB300"* ]]; then
    pass "DMI product is $dmi_product"
  else
    fail "DMI product is $dmi_product; expected DGX Station GB300"
  fi
else
  fail "DMI product identity is unavailable"
fi

if has_command mokutil; then
  secure_boot_state="$(mokutil --sb-state 2>&1 || true)"
  if grep -qi 'disabled' <<<"$secure_boot_state"; then
    pass "Secure Boot is disabled"
  elif grep -qi 'enabled' <<<"$secure_boot_state"; then
    fail "Secure Boot is enabled; the Station open-driver preparation expects it disabled"
  else
    warn "Secure Boot state could not be determined: $secure_boot_state"
  fi
else
  warn "mokutil is not installed; Secure Boot state was not checked"
fi

if [ -e "/lib/modules/$(uname -r)/build" ]; then
  pass "kernel headers are present for $(uname -r)"
else
  warn "kernel headers are missing for $(uname -r); install them before changing the NVIDIA driver"
fi

if has_command nvidia-smi; then
  gpu_inventory="$(nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader 2>/dev/null || true)"
  if [ -n "$gpu_inventory" ]; then
    while IFS= read -r gpu; do
      printf 'INFO  GPU %s\n' "$gpu"
    done <<<"$gpu_inventory"
    if grep -q 'NVIDIA GB300' <<<"$gpu_inventory"; then
      pass "GB300 inference GPU is present"
    else
      fail "GB300 inference GPU was not detected"
    fi
    if grep -Eq 'RTX PRO 6000.*Blackwell' <<<"$gpu_inventory"; then
      pass "RTX PRO 6000 Blackwell render GPU is present"
    else
      fail "RTX PRO 6000 Blackwell render GPU was not detected"
    fi
  else
    fail "nvidia-smi could not read the GPU inventory"
  fi
else
  fail "nvidia-smi is not installed"
fi

if [ -r /proc/meminfo ]; then
  memory_kib="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
  memory_gib=$((memory_kib / 1024 / 1024))
  pass "system memory is ${memory_gib} GiB"
else
  warn "could not read total system memory"
fi

section "Storage"

target_model_serving=false
if has_command curl; then
  model_response="$(curl -fsS --max-time 5 http://127.0.0.1:8000/v1/models 2>/dev/null || true)"
  if grep -Eqi 'nemotron([_-]3)?[_-]ultra' <<<"$model_response"; then
    target_model_serving=true
  fi
fi

target_model_cache_complete=false
target_model_cache_gib=0
if [ -d "$TARGET_MODEL_CACHE" ]; then
  cached_config="$(find "$TARGET_MODEL_CACHE/snapshots" -name config.json -print -quit 2>/dev/null || true)"
  incomplete_blob="$(find "$TARGET_MODEL_CACHE" -type f -name '*.incomplete' -print -quit 2>/dev/null || true)"
  if [ -s "$cached_config" ] && [ -z "$incomplete_blob" ]; then
    snapshot_dir="$(dirname "$cached_config")"
    first_shard="$(find "$snapshot_dir" -maxdepth 1 -name 'model-*-of-*.safetensors' -print -quit 2>/dev/null || true)"
    shard_total_padded="$(basename "$first_shard" | sed -n 's/^model-[0-9][0-9]*-of-\([0-9][0-9]*\)\.safetensors$/\1/p')"
    if [ -n "$shard_total_padded" ]; then
      shard_total=$((10#$shard_total_padded))
      target_model_cache_complete=true
      for ((shard_index = 1; shard_index <= shard_total; shard_index++)); do
        printf -v shard_index_padded '%05d' "$shard_index"
        for extension in safetensors json; do
          shard_path="$snapshot_dir/model-${shard_index_padded}-of-${shard_total_padded}.${extension}"
          if [ ! -s "$shard_path" ]; then
            target_model_cache_complete=false
            break 2
          fi
        done
      done
    fi
  fi
  if $target_model_cache_complete; then
    target_model_cache_kib="$(du -sk "$TARGET_MODEL_CACHE" 2>/dev/null | awk '{print $1}')"
    if [ -n "$target_model_cache_kib" ]; then
      target_model_cache_gib=$((target_model_cache_kib / 1024 / 1024))
    else
      target_model_cache_complete=false
    fi
  fi
fi

if [ -d "$STORAGE_PATH" ]; then
  available_kib="$(df -Pk "$STORAGE_PATH" | awk 'NR == 2 {print $4}')"
  available_gib=$((available_kib / 1024 / 1024))
  if [ "$available_gib" -ge "$MIN_FREE_GIB" ]; then
    pass "$STORAGE_PATH has ${available_gib} GiB free (minimum ${MIN_FREE_GIB} GiB)"
  elif $target_model_serving; then
    pass "$STORAGE_PATH has ${available_gib} GiB free; the target model is already serving on port 8000"
  elif $target_model_cache_complete && [ $((available_gib + target_model_cache_gib)) -ge "$MIN_FREE_GIB" ]; then
    pass "$STORAGE_PATH has ${available_gib} GiB free plus ${target_model_cache_gib} GiB of complete reusable target-model cache"
  else
    fail "$STORAGE_PATH has ${available_gib} GiB free; the guide requires ${MIN_FREE_GIB} GiB"
  fi
else
  fail "storage path does not exist: $STORAGE_PATH"
fi

if [ "$STORAGE_PATH" = "$HOME" ] && [ -d /raid ]; then
  raid_available_kib="$(df -Pk /raid | awk 'NR == 2 {print $4}')"
  raid_available_gib=$((raid_available_kib / 1024 / 1024))
  if [ "$raid_available_gib" -ge "$MIN_FREE_GIB" ]; then
    warn "/raid has ${raid_available_gib} GiB free if the documented home-directory paths cannot be cleared"
  fi
fi

section "Required host packages"

active_package_managers="$(ps -eo pid=,comm= 2>/dev/null | awk '$2 ~ /^(apt|apt-get|dpkg|unattended-upgrade)$/ {print}' || true)"
if [ -z "$active_package_managers" ]; then
  pass "no package-manager process is active"
else
  fail "a package-manager process is active: $active_package_managers"
fi

if has_command dpkg-query; then
  for package in \
    ca-certificates \
    curl \
    git \
    git-lfs \
    jq \
    unzip \
    zip \
    xz-utils \
    file \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    nvidia-container-toolkit; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q '^install ok installed$'; then
      pass "$package package is installed"
    else
      fail "$package package is not installed"
    fi
  done
else
  fail "dpkg-query is unavailable; required Debian packages were not checked"
fi

if has_command nvidia-ctk; then
  if nvidia-ctk cdi list 2>/dev/null | grep -Fxq 'nvidia.com/gpu=all'; then
    pass "NVIDIA CDI device nvidia.com/gpu=all is available"
  else
    warn "nvidia-ctk is installed but the all-GPU CDI device was not reported"
  fi
else
  fail "nvidia-ctk is not installed"
fi

if has_command sudo; then
  if sudo -n true >/dev/null 2>&1; then
    pass "sudo is available non-interactively"
  else
    warn "sudo requires an interactive password; the guide's privileged steps need a human terminal"
  fi
else
  fail "sudo is not installed"
fi

section "Docker and NVIDIA runtime"

if has_command docker; then
  if docker info >/dev/null 2>&1; then
    pass "Docker daemon is reachable by $USER"
    if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q 'nvidia'; then
      pass "Docker reports the NVIDIA runtime"
    elif has_command nvidia-ctk && \
      nvidia-ctk cdi list 2>/dev/null | grep -Fxq 'nvidia.com/gpu=all'; then
      pass "Docker can use NVIDIA GPUs through the available CDI devices"
    else
      fail "Docker reports neither the NVIDIA runtime nor usable NVIDIA CDI devices"
    fi
  else
    fail "Docker is installed but $USER cannot reach the daemon"
  fi
else
  fail "Docker is not installed; the guide installs docker.io when no Docker CLI is present"
fi

if id -nG | tr ' ' '\n' | grep -qx docker; then
  pass "$USER belongs to the docker group"
else
  fail "$USER does not belong to the docker group"
fi

section "Credentials and public OV distribution"

if has_command git; then
  if git ls-remote --exit-code \
    "https://github.com/$OV_GITHUB_REPO.git" refs/heads/main >/dev/null 2>&1; then
    pass "public Git checkout is reachable: $OV_GITHUB_REPO"
  else
    fail "public Git checkout is not reachable: $OV_GITHUB_REPO"
  fi
else
  fail "public OV repository access cannot be checked without git"
fi

if has_command curl; then
  if curl -fsSL --max-time 20 -o /dev/null "$OV_RELEASE_URL"; then
    pass "public OV Release page is reachable: $OV_RELEASE_TAG"
  else
    fail "public OV Release page is not reachable: $OV_RELEASE_URL"
  fi
else
  fail "public OV Release access cannot be checked without curl"
fi

if [ -n "${HF_TOKEN:-}" ] || [ -n "${HUGGING_FACE_HUB_TOKEN:-}" ]; then
  pass "a Hugging Face token is present in the environment (value not displayed)"
elif [ -s "$HOME/.cache/huggingface/token" ]; then
  warn "a cached Hugging Face token exists, but the guide expects HF_TOKEN in the launch shell"
elif $target_model_serving; then
  pass "no Hugging Face token is present; the target model is already serving"
elif $target_model_cache_complete; then
  pass "no Hugging Face token is present; the target model cache is complete"
else
  fail "no Hugging Face token was detected; export HF_TOKEN in the model launch shell"
fi

section "Required network names"

if has_command getent; then
  for host in \
    github.com \
    raw.githubusercontent.com \
    huggingface.co \
    download.blender.org \
    download.nomachine.com \
    www.nvidia.com; do
    if getent ahosts "$host" >/dev/null 2>&1; then
      pass "DNS resolves $host"
    else
      fail "DNS does not resolve $host"
    fi
  done
else
  fail "getent is not installed; required network names were not checked"
fi

section "Ports and existing services"

if ! has_command ss; then
  fail "ss is not installed; required ports could not be checked"
else
  if port_is_listening 8000; then
    if $target_model_serving; then
      pass "port 8000 already serves the target Nemotron Ultra model"
    else
      fail "port 8000 is occupied and does not report the target Nemotron Ultra model"
    fi
  else
    pass "port 8000 is available for Nemotron Ultra vLLM"
  fi

  for port in 9876 9877 18081; do
    if port_is_listening "$port"; then
      warn "port $port is already listening; confirm it belongs to this demo before reuse"
    else
      pass "port $port is available"
    fi
  done
fi

if has_command docker && docker info >/dev/null 2>&1; then
  old_vllm="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^(nemoclaw-vllm|nemotron-ultra-vllm)$' || true)"
  if [ -n "$old_vllm" ]; then
    while IFS= read -r container_name; do
      warn "model container is already running: $container_name"
    done <<<"$old_vllm"
  else
    pass "no conflicting named model container is running"
  fi
fi

if has_command nemohermes; then
  sandbox_names="$(nemohermes list --json 2>/dev/null | sed -n 's/^[[:space:]]*"name": "\([^"]*\)".*/\1/p' || true)"
  if [ -n "$sandbox_names" ]; then
    while IFS= read -r sandbox_name; do
      warn "existing NemoClaw sandbox: $sandbox_name"
    done <<<"$sandbox_names"
  else
    pass "no existing NemoClaw sandboxes were reported"
  fi
else
  warn "nemohermes is not installed yet; existing sandbox registry was not checked"
fi

section "Desktop and guide paths"

if [ -x /usr/NX/bin/nxserver ]; then
  pass "NoMachine server is installed"
else
  fail "NoMachine server is not installed"
fi

if has_command blender; then
  blender_version="$(blender --version 2>/dev/null | head -n 1 || true)"
  if grep -q 'Blender 5.1' <<<"$blender_version"; then
    pass "$blender_version is installed"
  else
    fail "installed Blender is not version 5.1.x: ${blender_version:-unknown}"
  fi
else
  fail "Blender 5.1.x is not installed"
fi

guide_repo="${GUIDE_REPO:-$HOME/work/nemoclaw-community/examples/demos/field/blender-omniverse-dgx-station}"
demo_root="$HOME/work/ov-blender-hermes-demo"
if [ -f "$guide_repo/README.md" ]; then
  pass "guide repository exists at $guide_repo"
else
  fail "guide repository is missing at $guide_repo"
fi

if [ -d "$demo_root" ]; then
  pass "demo root exists at $demo_root"
else
  warn "demo root does not exist yet: $demo_root"
fi

printf '\n== Summary ==\n'
printf 'PASS=%d WARN=%d FAIL=%d\n' "$pass_count" "$warn_count" "$fail_count"

if [ "$fail_count" -gt 0 ]; then
  printf 'RESULT=not-ready\n'
  exit 1
fi

printf 'RESULT=ready\n'
