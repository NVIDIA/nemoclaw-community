#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

interval="${ETL_INTERVAL_SECONDS:-3600}"

while true; do
  python /app/etl.py
  python /app/refresh_api_views.py
  now="$(date +%s)"
  sleep_for=$((interval - (now % interval)))
  if [ "${sleep_for}" -le 0 ]; then
    sleep_for="${interval}"
  fi
  sleep "$sleep_for"
done
