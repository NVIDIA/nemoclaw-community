#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# The platform prerequisite, in one place for every connector.
#
# `register-jobs.sh` refuses to run anywhere but Linux, so a machine that
# cannot register the jobs cannot run the recipe on a schedule. Connecting a
# source there costs the user a real authorization — a Slack install, or an
# Entra consent — for a scheduler that will never exist. Checking first is
# cheap; the consent is not, and it is granted in a browser to a tenant an
# administrator may have to be asked about.
#
# This lived in setup-slack.sh alone, which is why setup-graph.sh happily ran
# the entire device-code flow on macOS.
require_linux() {
  local kernel
  kernel="$(uname -s)"
  if [[ "$kernel" != "Linux" ]]; then
    echo "The scheduled path is Linux only; detected $kernel." >&2
    echo "The fixture walkthrough needs no credential and runs anywhere." >&2
    exit 1
  fi
}
