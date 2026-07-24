#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Remove Watchtower OpenClaw Cron Jobs through the supported paired CLI. With
# no argument, remove every job whose name starts with "watchtower-". Pass a
# specific job name to remove only that job.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }

JOB_SELECTOR="${1:-${WATCHTOWER_JOB_NAME:-watchtower-}}"

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found" >&2
  exit 1
fi

JOBS_JSON="$(openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- openclaw cron list --all --json)"
MATCHES="$(printf '%s\n' "$JOBS_JSON" | JOB_SELECTOR="$JOB_SELECTOR" node -e '
  let input = "";
  process.stdin.on("data", chunk => input += chunk);
  process.stdin.on("end", () => {
    const parsed = JSON.parse(input);
    const jobs = Array.isArray(parsed?.jobs) ? parsed.jobs : [];
    const selector = process.env.JOB_SELECTOR || "watchtower-";
    for (const job of jobs) {
      const name = String(job?.name || "");
      const matches = selector === "watchtower-" ? name.startsWith(selector) : name === selector;
      if (matches && job?.id) process.stdout.write(`${job.id}\t${name}\n`);
    }
  });
')"

if [[ -z "$MATCHES" ]]; then
  echo "No cron jobs matched '$JOB_SELECTOR'."
  exit 0
fi

while IFS=$'\t' read -r job_id job_name; do
  [[ -n "$job_id" ]] || continue
  echo "Removing $job_name ($job_id)"
  run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
    openclaw cron rm "$job_id" --json
done <<< "$MATCHES"
