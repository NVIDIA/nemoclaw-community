#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026 Merge. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Create the reader Tool Pack and re-read its allowlist before reporting success.
# Use tool_names: alternative fields can be silently ignored by the API.
# Requires a management key on the trusted host, never in the sandbox.

set +x
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v curl    >/dev/null || { echo "curl not in PATH" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not in PATH" >&2; exit 1; }
# Discard inherited/exported values; keep the prompted key local to this shell.
unset MERGE_AH_ADMIN_KEY
printf 'Agent Handler MANAGEMENT key (input hidden), then press Enter: ' >&2
read -rs MERGE_AH_ADMIN_KEY; echo >&2
[[ -n "$MERGE_AH_ADMIN_KEY" ]] || { echo "error: no key entered" >&2; exit 1; }
trap 'unset MERGE_AH_ADMIN_KEY' EXIT

READER_TOOLS='["list_workers","get_worker","list_organizations","get_organization_workers","get_absence_balances","list_time_off_entries"]'

create_pack() {
  local name="$1" desc="$2" tools="$3" body out id got
  body="$(python3 -c '
import json,sys
name,desc,tools=sys.argv[1],sys.argv[2],json.loads(sys.argv[3])
print(json.dumps({"name":name,"description":desc,
  "connectors":[{"slug":"workday","tool_names":tools}]}))' "$name" "$desc" "$tools")"

  out="$(curl -s --max-time 40 -X POST "$AH_BASE_URL/api/v1/tool-packs/" \
    -H @- \
    -H "Content-Type: application/json" --data "$body" <<< "Authorization: Bearer $MERGE_AH_ADMIN_KEY")"

  id="$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)"
  if [[ -z "$id" ]]; then
    echo "  failed to create '$name': $(printf '%s' "$out" | head -c 200)" >&2
    return 1
  fi

  # Re-read, because a silently-ignored tool filter is the failure mode here.
  got="$(curl -s --max-time 30 "$AH_BASE_URL/api/v1/tool-packs/$id/" \
    -H @- <<< "Authorization: Bearer $MERGE_AH_ADMIN_KEY" \
    | python3 -c '
import json,sys
d=json.load(sys.stdin)
print(",".join(sorted(t["name"] for c in d.get("connectors",[]) for t in c.get("tools",[]))))')"

  local want
  want="$(printf '%s' "$tools" | python3 -c 'import json,sys; print(",".join(sorted(json.load(sys.stdin))))')"
  if [[ "$got" != "$want" ]]; then
    echo "  WARNING '$name' ($id) did not scope as requested." >&2
    echo "    wanted: $want" >&2
    echo "    got:    $got" >&2
    return 1
  fi
  echo "  $name -> $id"
  echo "    tools ($(printf '%s' "$got" | tr ',' '\n' | grep -c .)): $got"
}

echo "Creating reader Tool Pack under $AH_BASE_URL"
create_pack "workday-hr-reader" \
  "Read-only Workday HR assistant: org chart and time-off. No compensation, payslips, or payments." \
  "$READER_TOOLS"

echo
echo "Put the reader pack id in .env as MERGE_AH_TOOL_PACK_ID, then:"
echo "  bash scripts/issue-runtime-key.sh"
