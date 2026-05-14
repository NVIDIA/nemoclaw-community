#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -eu

ETL_HOME="${ETL_HOME:-/app}"
ETL_RUNTIME_DIR="${ETL_RUNTIME_DIR:-${ETL_HOME}/.runtime}"
ETL_STATE_DIR="${ETL_STATE_DIR:-/var/lib/github-etl/state}"
STATE_PATH="${STATE_PATH:-${ETL_STATE_DIR}/state.json}"
BACKFILL_HOURS="${BACKFILL_HOURS:-72}"
ETL_LOG_LEVEL="${ETL_LOG_LEVEL:-INFO}"

mkdir -p "${ETL_RUNTIME_DIR}" "${ETL_STATE_DIR}"

if [ -z "${POSTGRES_SQLALCHEMY_URL:-}" ]; then
  : "${POSTGRES_HOST:?POSTGRES_HOST is required when POSTGRES_SQLALCHEMY_URL is unset}"
  : "${POSTGRES_USER:?POSTGRES_USER is required when POSTGRES_SQLALCHEMY_URL is unset}"
  : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required when POSTGRES_SQLALCHEMY_URL is unset}"
  : "${POSTGRES_DB:?POSTGRES_DB is required when POSTGRES_SQLALCHEMY_URL is unset}"
fi

GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-NVIDIA/NemoClaw}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_SCHEMA="${POSTGRES_SCHEMA:-github_raw}"

export ETL_RUNTIME_DIR ETL_STATE_DIR STATE_PATH BACKFILL_HOURS ETL_LOG_LEVEL
export GITHUB_REPOSITORY GITHUB_TOKEN="${GITHUB_TOKEN:-}"
export POSTGRES_SQLALCHEMY_URL="${POSTGRES_SQLALCHEMY_URL:-}"
export POSTGRES_HOST="${POSTGRES_HOST:-}"
export POSTGRES_PORT POSTGRES_USER="${POSTGRES_USER:-}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}" POSTGRES_DB="${POSTGRES_DB:-}"
export POSTGRES_SCHEMA

python3 - <<'PY'
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

runtime_dir = Path(os.environ["ETL_RUNTIME_DIR"])
state_path = Path(os.environ["STATE_PATH"])
tap_path = runtime_dir / "tap-github.json"
target_path = runtime_dir / "target-postgres.json"

backfill_hours = int(os.environ["BACKFILL_HOURS"])
repo = os.environ["GITHUB_REPOSITORY"]
log_level = os.environ["ETL_LOG_LEVEL"]

tap_config = {
    "repositories": [repo],
    "metrics_log_level": log_level,
}

token = os.environ.get("GITHUB_TOKEN")
if token:
    tap_config["auth_token"] = token

if not state_path.exists() or state_path.stat().st_size == 0:
    start_date = datetime.now(UTC) - timedelta(hours=backfill_hours)
    tap_config["start_date"] = start_date.replace(microsecond=0).isoformat().replace("+00:00", "Z")

target_config = {
    "default_target_schema": os.environ["POSTGRES_SCHEMA"],
    "load_method": "upsert",
    "add_record_metadata": True,
}

sqlalchemy_url = os.environ.get("POSTGRES_SQLALCHEMY_URL")
if sqlalchemy_url:
    target_config["sqlalchemy_url"] = sqlalchemy_url
else:
    target_config.update(
        {
            "host": os.environ["POSTGRES_HOST"],
            "port": int(os.environ["POSTGRES_PORT"]),
            "user": os.environ["POSTGRES_USER"],
            "password": os.environ["POSTGRES_PASSWORD"],
            "database": os.environ["POSTGRES_DB"],
        }
    )

tap_path.write_text(json.dumps(tap_config, indent=2) + "\n", encoding="utf-8")
target_path.write_text(json.dumps(target_config, indent=2) + "\n", encoding="utf-8")
PY

tap-github --config "${ETL_RUNTIME_DIR}/tap-github.json" --discover > "${ETL_RUNTIME_DIR}/catalog.json"

python3 - <<'PY'
import json
import os
from pathlib import Path

catalog_path = Path(os.environ["ETL_RUNTIME_DIR"]) / "catalog.json"
catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

selected_streams = {
    "repositories",
    "issues",
    "issue_comments",
    "issue_events",
    "pull_requests",
    "reviews",
    "review_comments",
    "discussions",
    "discussion_comments",
    "discussion_comment_replies",
}

for stream in catalog.get("streams", []):
    selected = stream.get("stream") in selected_streams
    for metadata_entry in stream.get("metadata", []):
        if metadata_entry.get("breadcrumb") == []:
            metadata_entry.setdefault("metadata", {})["selected"] = selected
            break

catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
PY

echo "github-etl starting sync for ${GITHUB_REPOSITORY}"

TAP_CMD="tap-github --config ${ETL_RUNTIME_DIR}/tap-github.json --catalog ${ETL_RUNTIME_DIR}/catalog.json"
if [ -s "${STATE_PATH}" ]; then
  TAP_CMD="${TAP_CMD} --state ${STATE_PATH}"
fi

set -o pipefail
sh -c "${TAP_CMD}" \
  | python3 "${ETL_HOME}/scripts/persist_state.py" "${STATE_PATH}" \
  | target-postgres --config "${ETL_RUNTIME_DIR}/target-postgres.json"
