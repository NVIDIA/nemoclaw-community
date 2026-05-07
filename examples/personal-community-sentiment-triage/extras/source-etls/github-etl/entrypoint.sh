#!/usr/bin/env bash
set -eu

SYNC_INTERVAL_SECONDS="${SYNC_INTERVAL_SECONDS:-3600}"

if [ "${SYNC_INTERVAL_SECONDS}" -le 0 ] 2>/dev/null; then
  echo "SYNC_INTERVAL_SECONDS must be a positive integer" >&2
  exit 1
fi

while true; do
  /app/run-etl.sh
  python3 /app/scripts/refresh_api_views.py

  now="$(date +%s)"
  sleep_for=$((SYNC_INTERVAL_SECONDS - (now % SYNC_INTERVAL_SECONDS)))
  if [ "${sleep_for}" -le 0 ]; then
    sleep_for="${SYNC_INTERVAL_SECONDS}"
  fi

  echo "github-etl sleeping ${sleep_for}s until next scheduled run"
  sleep "${sleep_for}"
done
