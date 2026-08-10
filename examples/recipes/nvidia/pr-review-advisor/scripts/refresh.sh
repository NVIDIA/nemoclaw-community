#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

repo="${1:-.}"
shift || true
trusted_ref=()
yes=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --trusted-ref)
      [[ -n "${2:-}" ]] || {
        echo "--trusted-ref requires a value" >&2
        exit 2
      }
      trusted_ref=(--trusted-ref "$2")
      shift 2
      ;;
    --yes) yes=(--yes); shift ;;
    -h|--help)
      echo "Usage: refresh.sh [REPO] [--trusted-ref REF] [--yes]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

command -v node >/dev/null 2>&1 || { echo "Required command not found: node" >&2; exit 1; }
cli="$DIR/../installer/bin/cli.mjs"
[[ -f "$cli" && ! -L "$cli" ]] || { echo "Installer CLI not found: $cli" >&2; exit 1; }

exec node "$cli" refresh "$repo" "${trusted_ref[@]}" "${yes[@]}"
