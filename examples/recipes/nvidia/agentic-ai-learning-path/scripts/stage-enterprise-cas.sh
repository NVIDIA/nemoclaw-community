#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Stage locally installed TLS-inspection roots into the sandbox build context.
# The destination is covered by the repository-wide *.crt ignore rule. The
# standard local CA directory is separate from distribution-managed roots, so
# only operator-installed certificates are copied by default.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$DIR")"
SOURCE_DIR="${NEMOCLAW_ENTERPRISE_CA_SOURCE_DIR:-/usr/local/share/ca-certificates}"
DEST_DIR="${NEMOCLAW_ENTERPRISE_CA_DEST_DIR:-$EXAMPLE_DIR/certs}"

[[ -d "$SOURCE_DIR" ]] || exit 0
shopt -s nullglob
certificate_paths=("$SOURCE_DIR"/*.crt)
shopt -u nullglob

staged=0
for source_path in "${certificate_paths[@]}"; do
  [[ -f "$source_path" && -r "$source_path" ]] || continue
  certificate_name="$(basename "$source_path")"

  mkdir -p "$DEST_DIR"
  destination_path="$DEST_DIR/$certificate_name"
  if [[ -f "$destination_path" ]] && cmp -s "$source_path" "$destination_path"; then
    continue
  fi

  temporary_path="$destination_path.tmp.$$"
  trap 'rm -f "${temporary_path:-}"' EXIT
  cp "$source_path" "$temporary_path"
  chmod 0644 "$temporary_path"
  mv "$temporary_path" "$destination_path"
  trap - EXIT
  echo "Staged enterprise CA: $certificate_name"
  staged=$((staged + 1))
done

if (( staged > 0 )); then
  echo "Enterprise CA staging complete ($staged updated)."
fi
