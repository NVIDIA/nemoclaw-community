#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Orchestrator: runs 01-gateway.sh → 02-providers.sh → 03-sandbox.sh in
# order. This is the one-command path; if you want to learn the OpenShell
# CLI surface, run the three phase scripts individually instead — they
# print which commands they're about to issue and pause for nothing, so
# you can `openshell <thing> list` between steps to inspect state.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$DIR/01-gateway.sh"
bash "$DIR/02-providers.sh"
bash "$DIR/03-sandbox.sh"
