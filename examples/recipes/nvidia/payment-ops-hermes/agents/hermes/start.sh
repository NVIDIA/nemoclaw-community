#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

export HERMES_HOME="${HERMES_HOME:-/sandbox/.hermes}"
export HERMES_DISABLE_LAZY_INSTALLS=1
export HERMES_NEMO_RELAY_PLUGINS_TOML="${HERMES_NEMO_RELAY_PLUGINS_TOML:-/etc/nemo-relay/config/plugins.toml}"

mkdir -p /sandbox/atif
if [[ ! -r "${HERMES_NEMO_RELAY_PLUGINS_TOML}" ]]; then
  echo "Native NeMo Relay configuration is missing" >&2
  exit 1
fi

echo "[nemo-relay] native observability configured"
cd /etc/nemo-relay/runtime
exec hermes gateway run >>/tmp/hermes.log 2>&1
