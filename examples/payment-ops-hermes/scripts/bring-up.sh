#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

recover_error=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --recover-error) recover_error=1 ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--recover-error]"
      echo "  --recover-error  replace an unhealthy or Error-state sandbox"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

load_env
require_command python3
require_command docker
require_command openshell

echo "═══ Phase 1/5: Preflight checks ═══"
smoke_output=""
if smoke_output="$(python3 "$EXAMPLE_DIR/scripts/smoke-payment.py" 2>&1)"; then
  echo "  [ok] payment fixtures and controls validated (6 scenarios)"
else
  echo "Payment fixture validation failed:" >&2
  printf '%s\n' "$smoke_output" >&2
  exit 1
fi
docker info >/dev/null 2>&1 || {
  echo "  [!!] Docker daemon is not ready" >&2
  exit 1
}
echo "  [ok] Docker daemon ready"
echo "  [ok] OpenShell CLI available"
echo
echo "═══ Phase 2/5: Host services ═══"
bash "$DIR/00-host-services.sh"
echo
echo "═══ Phase 3/5: Gateway and inference ═══"
bash "$DIR/01-gateway.sh"
bash "$DIR/02-provider.sh"
echo
echo "═══ Phase 4/5: Hermes + NeMo Relay sandbox ═══"
if [[ "$recover_error" == 1 ]]; then
  bash "$DIR/03-sandbox.sh" --recover-error
else
  bash "$DIR/03-sandbox.sh"
fi
echo
echo "═══ Phase 5/5: Payment-operations services ═══"
bash "$DIR/04-demo-services.sh"
echo
echo "Run 'bash scripts/verify.sh' to verify the complete deployment."
