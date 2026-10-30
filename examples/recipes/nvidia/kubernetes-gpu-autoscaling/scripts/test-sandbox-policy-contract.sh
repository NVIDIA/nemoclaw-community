#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Local contract: skipping create-time smoke tests still applies and verifies
# the on-premises sandbox policy. Setup stops when that policy cannot be
# applied or verified.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=agent-common.sh
source "${SCRIPT_DIR}/agent-common.sh"

fake_bin="$(mktemp -d)"
log_dir="$(mktemp -d)"
trap 'rm -rf "${fake_bin}" "${log_dir}"' EXIT

cat >"${fake_bin}/openshell" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >>"${FAKE_OPENSHELL_RECORD:?}"
case "$1 $2" in
  "policy update")
    exit "${FAKE_POLICY_UPDATE_RC:-0}"
    ;;
  "policy get")
    if [[ "${FAKE_POLICY_GET_RC:-0}" != 0 ]]; then
      exit "${FAKE_POLICY_GET_RC}"
    fi
    printf '%s' "${FAKE_POLICY_GET_BODY}"
    exit 0
    ;;
  "sandbox exec")
    exit 0
    ;;
  *)
    echo "unexpected openshell $*" >&2
    exit 99
    ;;
esac
EOF
chmod +x "${fake_bin}/openshell"
PATH="${fake_bin}:${PATH}"
export FAKE_POLICY_UPDATE_RC=0
export FAKE_POLICY_GET_RC=0
export FAKE_POLICY_GET_BODY='{"endpoints":[{"host":"inference.local"}]}'
export SKIP_CREATE_SMOKE=1

assert_stopped() {
  local name="$1"
  shift
  if "$@"; then
    echo "ERROR: ${name} must stop setup" >&2
    exit 1
  fi
}

run_enforce() {
  local record="${log_dir}/record"
  local log="${log_dir}/policy.log"
  : >"${record}"
  : >"${log}"
  FAKE_OPENSHELL_RECORD="${record}" \
    agent_common_enforce_onprem_sandbox_policy "$1" "$2" "${log}"
}

run_enforce sandbox-a hermes
record="$(<"${log_dir}/record")"
grep -Fq 'policy update sandbox-a --remove-endpoint integrate.api.nvidia.com:443 --wait --timeout 20' <<<"${record}"
grep -Fq 'policy get sandbox-a --full -o json' <<<"${record}"
if grep -Fq 'sandbox exec' <<<"${record}"; then
  echo "ERROR: policy enforcement must not run create-time smoke" >&2
  exit 1
fi

FAKE_POLICY_UPDATE_RC=1
assert_stopped "failed policy update" run_enforce sandbox-a hermes
record="$(<"${log_dir}/record")"
update_count="$(grep -c 'policy update ' <<<"${record}" || true)"
[[ "${update_count}" -eq 3 ]]
if grep -Fq 'policy get ' <<<"${record}"; then
  echo "ERROR: failed policy apply must stop before verification" >&2
  exit 1
fi

FAKE_POLICY_UPDATE_RC=0
FAKE_POLICY_GET_BODY='{"endpoints":[{"host":"integrate.api.nvidia.com"}]}'
assert_stopped "endpoint still granted" run_enforce sandbox-a openclaw

FAKE_POLICY_GET_RC=1
FAKE_POLICY_GET_BODY='{"endpoints":[{"host":"inference.local"}]}'
assert_stopped "policy get failed" run_enforce sandbox-a hermes

FAKE_POLICY_GET_RC=0
FAKE_POLICY_GET_BODY=''
assert_stopped "empty policy" run_enforce sandbox-a hermes

FAKE_POLICY_GET_BODY='{"endpoints":[{"host":"inference.local"}]}'
run_enforce sandbox-b deepagents
record="$(<"${log_dir}/record")"
if grep -Fq 'policy update ' <<<"${record}"; then
  echo "ERROR: Deep Agents must not rewrite a policy that does not grant the endpoint" >&2
  exit 1
fi
grep -Fq 'policy get sandbox-b --full -o json' <<<"${record}"

FAKE_POLICY_GET_BODY='{"endpoints":[{"host":"integrate.api.nvidia.com"}]}'
assert_stopped "deepagents endpoint still granted" run_enforce sandbox-b deepagents

python3 - "${SCRIPT_DIR}/create-agent-sandbox.sh" <<'PY'
import sys

text = open(sys.argv[1], encoding="utf-8").read()
enforce = text.find("agent_common_enforce_onprem_sandbox_policy")
skip = text.find('SKIP_CREATE_SMOKE:-0}" == "1"')
if enforce < 0 or skip < 0 or enforce > skip:
    raise SystemExit("policy enforcement must run before SKIP_CREATE_SMOKE can return")
if "skipping supervisor/policy/smoke" in text:
    raise SystemExit("smoke skip must not skip sandbox policy")
if "policy still applying (continuing" in text or "WARNING: effective sandbox policy still lists" in text:
    raise SystemExit("policy apply and verify must stop setup")
PY

echo "OK: smoke skip still applies and verifies sandbox policy; apply and verify failures stop setup"
