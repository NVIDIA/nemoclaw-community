#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Orchestrator: 01-gateway.sh → 02-providers.sh → 03-sandbox.sh. Run the
# phase scripts individually instead if you want to learn the OpenShell CLI
# surface — they print the commands they're about to issue.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env
assert_messaging_config

echo
echo "═══ Phase 1/3: Gateway ═══"
bash "$DIR/01-gateway.sh"
echo
echo "═══ Phase 2/3: Providers ═══"
bash "$DIR/02-providers.sh"
echo
echo "═══ Phase 3/3: Sandbox ═══"
bash "$DIR/03-sandbox.sh"
