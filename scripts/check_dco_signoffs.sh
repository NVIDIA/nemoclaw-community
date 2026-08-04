#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <base-commit> <head-commit>" >&2
  exit 2
fi

base_sha="$1"
head_sha="$2"

report_error() {
  if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    echo "::error::$1"
  else
    echo "DCO check failed: $1" >&2
  fi
}

if ! git rev-parse --verify --quiet "${base_sha}^{commit}" >/dev/null; then
  report_error "Base commit ${base_sha} is not available locally."
  exit 2
fi

if ! git rev-parse --verify --quiet "${head_sha}^{commit}" >/dev/null; then
  report_error "Head commit ${head_sha} is not available locally."
  exit 2
fi

commit_count=0
missing_signoff=0

while IFS= read -r sha; do
  commit_count=$((commit_count + 1))

  if ! git show -s --format=%B "$sha" \
    | git interpret-trailers --parse \
    | grep -Eq '^Signed-off-by: .+ <[^<>[:space:]]+@[^<>[:space:]]+>$'; then
    subject="$(git show -s --format=%s "$sha")"
    report_error "Commit ${sha} (${subject}) is missing a valid Signed-off-by trailer."
    missing_signoff=1
  fi
done < <(git rev-list --reverse "${base_sha}..${head_sha}")

if ((commit_count == 0)); then
  report_error "The commit range ${base_sha}..${head_sha} does not contain a commit to check."
  exit 1
fi

if ((missing_signoff != 0)); then
  echo "Create commits with 'git commit -s'. Repair the affected commit before pushing again." >&2
  exit 1
fi

echo "DCO sign-off check passed for ${commit_count} commit(s)."
