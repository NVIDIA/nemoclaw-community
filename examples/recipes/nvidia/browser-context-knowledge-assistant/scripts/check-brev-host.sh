#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail

failures=0
brev_handoff_ready=0

if [[ -r /etc/nemoclaw/gateway-management.env \
      && "$(systemctl is-active openshell-gateway.service 2>/dev/null || true)" != active ]]; then
  brev_handoff_ready=1
fi

report_failure() {
  printf 'FAIL: %s\n' "$1" >&2
  failures=$((failures + 1))
}

report_ok() {
  printf 'OK:   %s\n' "$1"
}

command_version() {
  "$1" --version 2>&1 | head -1
}

for required in docker nemoclaw nemohermes openshell; do
  if ! command -v "$required" >/dev/null 2>&1; then
    report_failure "Required command is unavailable: $required"
  else
    report_ok "$required: $(command -v "$required")"
  fi
done

if ((failures > 0)); then
  exit 1
fi

printf '\nInstalled versions\n'
printf '  %s\n' "$(command_version nemoclaw)"
printf '  %s\n' "$(command_version nemohermes)"
printf '  %s\n' "$(command_version openshell)"

driver_status="$(docker info --format '{{json .DriverStatus}}')"
driver_name="$(docker info --format '{{.Driver}}')"
if [[ "$driver_status" == *'io.containerd.snapshotter.v1'* ]]; then
  report_failure "Docker uses the containerd snapshotter; configure classic overlay2 before onboarding"
else
  report_ok "Docker storage driver: $driver_name"
fi

if sandbox_output="$(openshell sandbox list 2>&1)"; then
  if grep -Fq 'No sandboxes found.' <<<"$sandbox_output"; then
    report_ok "The selected OpenShell gateway is reachable and contains no sandboxes"
  elif awk 'NR > 1 && NF > 0 { found=1 } END { exit !found }' <<<"$sandbox_output"; then
    report_failure "The selected gateway already contains a sandbox; use a fresh instance for this procedure"
  else
    report_ok "The selected OpenShell gateway is reachable and contains no sandboxes"
  fi
else
  if ((brev_handoff_ready == 1)); then
    report_ok "The legacy Brev gateway is stopped; the current gateway will start during onboarding"
  else
    report_failure "The selected OpenShell gateway is unavailable: $sandbox_output"
  fi
fi

if systemctl list-unit-files openshell-gateway.service >/dev/null 2>&1; then
  if [[ "$(systemctl is-active openshell-gateway.service 2>/dev/null || true)" != active ]]; then
    if ((brev_handoff_ready == 1)); then
      report_ok "The legacy Brev openshell-gateway.service is inactive after the explicit handoff"
    else
      report_failure "The Brev-owned openshell-gateway.service is not active"
    fi
  else
    report_ok "The Brev-owned openshell-gateway.service is active"
  fi

  service_exec="$(systemctl show openshell-gateway.service --property=ExecStart --value 2>/dev/null || true)"
  printf '  gateway service: %s\n' "${service_exec:-unknown}"

  if [[ -x /usr/local/bin/openshell-gateway ]]; then
    system_gateway_version="$(command_version /usr/local/bin/openshell-gateway || true)"
    user_gateway_version="$(command_version "$(dirname "$(command -v openshell)")/openshell-gateway" || true)"
    printf '  system gateway:  %s\n' "${system_gateway_version:-unavailable}"
    printf '  updated gateway: %s\n' "${user_gateway_version:-unavailable}"
    if [[ -z "$system_gateway_version" || -z "$user_gateway_version" ]]; then
      report_failure "An OpenShell gateway version could not be inspected"
    elif [[ "$system_gateway_version" != "$user_gateway_version" ]]; then
      printf 'INFO: The retired Brev gateway and current user-local gateway binaries differ; onboarding will start the current version.\n'
    fi
  else
    report_failure "/usr/local/bin/openshell-gateway is unavailable"
  fi
fi

if ((failures > 0)); then
  cat >&2 <<'EOF'

Host compatibility checks failed. Do not copy replacement OpenShell binaries
over /usr/local/bin: a binary built for a newer glibc can make the Brev-owned
gateway unusable. Follow the maintained installer and managed compatibility
gateway procedure in this recipe.
EOF
  exit 1
fi

printf '\nBrev host compatibility checks passed.\n'
