#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Register the scheduled jobs through the supported cron interface.
#
# The jobs are created here rather than shipped inside the distribution. That
# is the supported path, and it has a second benefit: the distribution never
# owns the cron directory, so a profile update cannot replace the live job
# store along with its run history.
#
# Idempotent. Re-running updates the existing jobs in place rather than
# creating duplicates.

set -euo pipefail

# The scheduled path is Linux only. Every shipped skill declares
# `platforms: [linux]`, and Hermes refuses to load a skill outside its declared
# platforms — so on macOS the jobs fire, the model is called, and no skill
# loads. Registering them there buys a scheduled expense and no assistant.
# Refuse before anything is installed or registered rather than after.
require_linux() {
  local kernel
  kernel="$(uname -s)"
  if [[ "$kernel" != "Linux" ]]; then
    echo "This installs a scheduled path that only works on Linux." >&2
    echo "  detected: $kernel" >&2
    echo "" >&2
    echo "Every shipped skill declares 'platforms: [linux]'. On $kernel the" >&2
    echo "jobs would fire and the model would be called with no skill loaded." >&2
    echo "Windows Subsystem for Linux reports Linux and is supported." >&2
    echo "" >&2
    echo "The fixture path needs none of this and runs anywhere:" >&2
    echo "  python3 profile/scripts/walkthrough.py --fixtures fixtures" >&2
    exit 1
  fi
}
require_linux

PROFILE="${PROFILE_NAME:-memory-driven-chief-of-staff}"

# `|| true` matters: `hermes profile show` exits 1 for a profile that does not
# exist, and under `set -e` the assignment would abort the script before the
# check below could explain why.
PROFILE_HOME="$(hermes profile show "$PROFILE" 2>/dev/null \
  | sed -n 's/^Path:[[:space:]]*//p' || true)"
if [[ -z "$PROFILE_HOME" ]]; then
  echo "Could not resolve the profile home for '$PROFILE'." >&2
  echo "Install the profile first: scripts/install.sh" >&2
  exit 1
fi

# Look an existing job up by name.
#
# Writes go through the cron CLI, which is the supported interface. The lookup
# does not, because no cron subcommand emits machine-readable output — `list`
# prints a table for a person and takes no `--json`. Reading the store the
# scheduler itself writes (`cron/jobs.py` keeps `{"jobs": [...]}` there) is
# steadier than parsing that table, and it is a read.
#
# Without this the script cannot tell an existing job from a missing one, and
# every run creates another copy of all five.
job_id_for() {
  local name="$1" store="$PROFILE_HOME/cron/jobs.json"
  [[ -f "$store" ]] || return 0
  python3 - "$store" "$name" <<'PYFIND'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, ValueError):
    sys.exit(0)
jobs = data.get("jobs", []) if isinstance(data, dict) else data
for job in jobs if isinstance(jobs, list) else []:
    if isinstance(job, dict) and job.get("name") == sys.argv[2]:
        print(job.get("id", ""))
        break
PYFIND
}

# Every job runs as a selector script that emits JSON, then one agent turn over
# that output. A selector that finds nothing emits a wake gate and the agent
# turn is skipped entirely, so an idle tick costs no tokens.
register() {
  local name="$1" schedule="$2" skill="$3" script="${4:-}" prompt="$5"
  local existing
  existing="$(job_id_for "$name")"

  local args=(--name "$name" --deliver local --skill "$skill")
  [[ -n "$script" ]] && args+=(--script "$script")

  if [[ -n "$existing" ]]; then
    echo "  updating $name ($existing)"
    hermes -p "$PROFILE" cron edit "$existing" --schedule "$schedule" --prompt "$prompt" "${args[@]}"
  else
    echo "  creating $name"
    hermes -p "$PROFILE" cron create "$schedule" "$prompt" "${args[@]}"
  fi
}

echo "Registering scheduled jobs on profile '$PROFILE'"

register intake "*/30 * * * *" inbound-judging select_intake.py \
  "Judge the messages in the script output, following the inbound-judging skill exactly. Then WRITE the result: save your decision envelope to a file and run \`python3 \$HERMES_HOME/scripts/apply_decisions.py < that file\`. Report the counts it prints. Printing the envelope without running the writer stores nothing and is a failed run."

register review "0 */6 * * *" obligation-review select_review.py \
  "Re-judge and re-rank the obligations in the script output, following the obligation-review skill exactly. Then WRITE the result: save your decision envelope to a file and run \`python3 \$HERMES_HOME/scripts/apply_decisions.py < that file\`. Report the counts it prints. Printing the envelope without running the writer stores nothing and is a failed run."

register "memory repair" "0 3 * * *" memory-repair "" \
  "Check the memory under workspace/memory against its schema and repair what can be repaired safely. Append one log entry even when nothing changed."

register "memory consolidation" "0 4 * * *" memory-consolidation "" \
  "Compact any memory page over the ceilings in the schema growth-control table. Compact, never truncate; preserve unresolved commitments and provenance."

register "preference update" "30 4 * * *" preference-update "" \
  "Read the audit trail for user corrections since the last run and update the bounded preference policy. Never write to obligations."

echo
echo "Jobs registered. They fire only while a gateway is serving this profile."
hermes -p "$PROFILE" cron list 2>&1 || true
echo
echo "To undo, remove each job by the id shown above:"
echo "  hermes -p $PROFILE cron remove <id>"
echo
echo "Deleting the profile removes the store and the memory with it:"
echo "  hermes profile delete $PROFILE"
