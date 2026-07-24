#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Tavily AI. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Show OpenClaw Cron Job status, registered jobs, recent run history, and latest
# Watchtower output artifacts through the supported paired OpenClaw CLI.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v openshell >/dev/null || { echo "openshell not in PATH" >&2; exit 1; }

WORKSPACE="${WORKSPACE:-/sandbox/.openclaw/workspace}"

if ! sandbox_exists "$NEMOCLAW_SANDBOX_NAME"; then
  echo "Sandbox '$NEMOCLAW_SANDBOX_NAME' not found" >&2
  exit 1
fi

echo "== OpenClaw cron scheduler =="
run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- openclaw cron status --json || true

echo
echo "== Cron jobs =="
set +e
JOBS_JSON="$(openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- openclaw cron list --all --json)"
JOBS_STATUS=$?
set -e
if (( JOBS_STATUS == 0 )); then
  printf '%s\n' "$JOBS_JSON"
else
  echo "Unable to list cron jobs (exit $JOBS_STATUS)." >&2
fi

echo
echo "== Recent cron runs =="
if (( JOBS_STATUS == 0 )); then
  while IFS=$'\t' read -r job_id job_name; do
    [[ -n "$job_id" ]] || continue
    echo "-- $job_name ($job_id) --"
    run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
      openclaw cron runs --id "$job_id" --limit 20 || true
  done < <(printf '%s\n' "$JOBS_JSON" | node -e '
    let input = "";
    process.stdin.on("data", chunk => input += chunk);
    process.stdin.on("end", () => {
      const parsed = JSON.parse(input);
      const jobs = Array.isArray(parsed?.jobs) ? parsed.jobs : [];
      for (const job of jobs) {
        if (job?.id && String(job.name || "").startsWith("watchtower-")) {
          process.stdout.write(`${job.id}\t${job.name || job.id}\n`);
        }
      }
    });
  ')
fi

echo
echo "== Watchtower outputs =="
run openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- sh -lc \
  "latest_digest=\$(ls -t '$WORKSPACE'/outputs/digest-* 2>/dev/null | head -n 1 || true); latest_changelog=\$(ls -t '$WORKSPACE'/outputs/changelog-* 2>/dev/null | head -n 1 || true); [ -n \"\$latest_digest\" ] && echo latest_digest: \"\$latest_digest\" || echo latest_digest: n/a; [ -n \"\$latest_changelog\" ] && echo latest_changelog: \"\$latest_changelog\" || echo latest_changelog: n/a"
