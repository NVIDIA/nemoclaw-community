#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
umask 077
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

action="${1:-inspect}"
destination="${2:-}"
scrub_external_secrets
load_env
scrub_external_secrets
require_command openshell
acquire_review_lock
trap release_review_lock EXIT INT TERM
assert_sandbox_ready

case "$action" in
  inspect)
    # shellcheck disable=SC2016
    run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
      bash -c 'for path in /sandbox/.hermes/memories/MEMORY.md /sandbox/.hermes/memories/USER.md; do
        if [ -f "$path" ]; then printf "\n== %s ==\n" "${path##*/}"; cat "$path"; fi
      done'
    ;;
  export)
    [[ -n "$destination" ]] || { echo "Usage: memory.sh export DIRECTORY" >&2; exit 2; }
    [[ ! -e "$destination" && ! -L "$destination" ]] || {
      echo "Memory export destination must not already exist: $destination" >&2
      exit 2
    }
    install -d -m 700 "$destination"
    run_openshell sandbox download "$NEMOCLAW_SANDBOX_NAME" \
      /sandbox/.hermes/memories "$destination/"
    if find "$destination" -type l -print -quit | grep -q .; then
      echo "Memory export unexpectedly contains a symlink" >&2
      exit 1
    fi
    find "$destination" -type d -exec chmod 700 {} +
    find "$destination" -type f -exec chmod 600 {} +
    ;;
  reset)
    [[ "$destination" == "--yes" ]] || {
      echo "Memory reset is destructive. Use: memory.sh reset --yes" >&2
      exit 2
    }
    backup="$(bash "$DIR/snapshot.sh" --lock-held)"
    # shellcheck disable=SC2016
    run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
      bash -c '
        set -euo pipefail
        root=/sandbox/.hermes/memories
        rm -f -- "$root/MEMORY.md" "$root/MEMORY.md.lock"
      '
    echo "Built-in review memory reset. Recoverable snapshot: $backup"
    ;;
  *)
    echo "Usage: memory.sh inspect | export DIRECTORY | reset --yes" >&2
    exit 2
    ;;
esac
