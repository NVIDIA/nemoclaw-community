#!/usr/bin/env bash
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
