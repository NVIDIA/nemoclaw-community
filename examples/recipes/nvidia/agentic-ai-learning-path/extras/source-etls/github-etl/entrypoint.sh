#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -eu

SYNC_INTERVAL_SECONDS="${SYNC_INTERVAL_SECONDS:-3600}"

# singer-sdk sends prepared requests directly through Session.send(), which
# bypasses Requests' normal REQUESTS_CA_BUNDLE environment merge. Align
# certifi with the managed host bundle mounted by docker-compose so GitHub
# GraphQL calls trust the same inspection roots as the Omnistation host.
CERTIFI_BUNDLE="$(python3 -c 'import certifi; print(certifi.where())')"
SYSTEM_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
if [ "$CERTIFI_BUNDLE" != "$SYSTEM_CA_BUNDLE" ]; then
  cp "$SYSTEM_CA_BUNDLE" "$CERTIFI_BUNDLE"
fi

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
