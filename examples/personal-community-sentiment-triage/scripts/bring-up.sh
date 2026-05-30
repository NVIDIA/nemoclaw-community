#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Orchestrator: 00-host-services.sh → 01-gateway.sh → 02-providers.sh → 03-sandbox.sh.
# Run the phase scripts individually instead if you want to learn the OpenShell
# CLI surface — they print the commands they're about to issue. 00-host-services
# is idempotent, so re-running bring-up.sh on an already-up host is a no-op for
# the host stack and only re-runs the sandbox-side phases.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

load_env
assert_messaging_config

echo
echo "═══ Phase 1/4: Host services ═══"
bash "$DIR/00-host-services.sh" up
echo
echo "═══ Phase 2/4: Gateway ═══"
bash "$DIR/01-gateway.sh"
echo
echo "═══ Phase 3/4: Providers ═══"
bash "$DIR/02-providers.sh"
echo
echo "═══ Phase 4/4: Sandbox ═══"
bash "$DIR/03-sandbox.sh"
