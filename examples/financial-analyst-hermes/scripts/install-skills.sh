#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX_NAME="${1:-${NEMOCLAW_SANDBOX_NAME:-financial-analyst}}"

echo "Installing finance policy preset into sandbox: ${SANDBOX_NAME}"
nemohermes "${SANDBOX_NAME}" policy-add \
  --from-file "${ROOT_DIR}/presets/finance-data-readonly.yaml" \
  --yes

echo "Installing Hermes skills into sandbox: ${SANDBOX_NAME}"
for skill_dir in "${ROOT_DIR}"/skills/*; do
  [ -d "${skill_dir}" ] || continue
  echo "  - $(basename "${skill_dir}")"
  nemohermes "${SANDBOX_NAME}" skill install "${skill_dir}"
done

echo "Configuring the sandbox to prefer the financial skill set"
bash "${ROOT_DIR}/scripts/configure-finance-skills.sh" "${SANDBOX_NAME}"

echo "Done. Try:"
echo "  nemohermes ${SANDBOX_NAME} exec -- /usr/bin/python3 /sandbox/.hermes/skills/financial-market-snapshot/scripts/finance_snapshot.py quote NVDA MSFT"
