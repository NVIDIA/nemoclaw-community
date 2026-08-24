#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB
# SPDX-License-Identifier: Apache-2.0
#
# Run inside the OpenShell sandbox. GET-only against the host Bot API.

set -euo pipefail

BASE="${GBR_BOT_BASE:-http://host.openshell.internal:8788}"

if [[ "$BASE" == *ekobrott* ]] || [[ "$BASE" == *gbr-relay* ]]; then
  echo "refusing vendor relay base: $BASE" >&2
  exit 1
fi

echo "== GET $BASE/health =="
curl -fsS --max-time 10 "$BASE/health"
echo
echo "== GET $BASE/v1/sessions =="
curl -fsS --max-time 10 "$BASE/v1/sessions"
echo
echo "GBR_OPERATOR_PING: host Bot API reachable. Waiting for remote-control client inject on this TTY."
