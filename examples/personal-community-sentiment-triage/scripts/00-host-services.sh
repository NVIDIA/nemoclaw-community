#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Lifecycle utility for the host-side services in extras/docker-compose.yml.
# These services run on the host (not in the sandbox) and are reached by
# the agent via the L7 proxy. Outlook OAuth is handled directly by the
# OpenShell v2 outlook provider.
#
#   phoenix      — OpenInference trace collector (UI on :6006)
#   postgres     — backing store for source ETLs
#   github-etl   — pulls GitHub issues/comments into postgres
#   forums-etl   — pulls NVIDIA forum posts into postgres
#   postgrest    — REST API in front of postgres (host port 3100)
#
# When ATIF_EXPORT_MODE=relay, the atif-export-relay service is also brought up
# via the compose profile matching ATIF_RELAY_BACKEND (s3|minio). When the relay
# backend is minio, the minio container is brought up too — a one-shot mc client
# creates the bucket after MinIO is healthy.
#
# Verbs:
#   up                  Start the stack (default if no arg).
#   down                Stop and remove containers, preserve volumes.
#   down --volumes      Also remove named volumes
#                       (source-etls-postgres-data, github-etl-state).
#                       DESTRUCTIVE: forces ETL re-scrape on next `up`.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

COMPOSE_FILE="$EXAMPLE_DIR/extras/docker-compose.yml"
[[ -f "$COMPOSE_FILE" ]] || { echo "Missing $COMPOSE_FILE" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker not in PATH" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $(basename "$0") [up|down [--volumes]]

  up          Start host services (default if no arg).
  down        Stop and remove containers; preserve named volumes.
  down -v
  down --volumes
              Also remove named volumes (source-etls-postgres-data,
              github-etl-state). DESTRUCTIVE: forces ETL re-scrape
              on next up.
EOF
}

cmd_up() {
  local profile_args=() backend=""
  if atif_remote_enabled; then
    backend="$(atif_relay_backend)"   # validates s3|minio (loud error if unset)
    # Resolve + export the downstream bucket BEFORE `docker compose up`: s3 /
    # s3-compatible fail loud here if ATIF_RELAY_BUCKET is unset, and compose
    # inherits the resolved value.
    export ATIF_RELAY_BUCKET="$(atif_relay_bucket "$backend")"
    profile_args=(--profile "$backend")
    # Generate/read the per-VM bearer from the gitignored cache (not .env) so
    # the relay starts WITH it on the first `up` — no crash-then-recreate.
    export ATIF_RELAY_AUTH_TOKEN="${ATIF_RELAY_AUTH_TOKEN:-$(atif_relay_token)}"
    echo "ATIF export: relay → $backend (atif-export-relay + ${backend} will be brought up)"
    # Cert is bind-mounted into the relay container at startup; generate
    # it now so the relay doesn't crashloop on missing files. See
    # docs/atif-export.md "Sandbox→relay TLS via Python protocol-bridge
    # sidecar" for the wider architecture.
    bash "$EXAMPLE_DIR/extras/atif-export-relay/generate-tls-cert.sh"
  else
    echo "ATIF export: local (traces written to sandbox /tmp/atif; no host services for ATIF)"
  fi

  echo "Starting host services${profile_args:+ (profile=$backend)}"
  docker compose -f "$COMPOSE_FILE" "${profile_args[@]}" up -d --build

  # Wait for MinIO healthy + create the bucket (idempotent).
  if [[ "$backend" == "minio" ]]; then
    local bucket="$ATIF_RELAY_BUCKET"   # resolved/exported above
    local minio_user="${NEMOCLAW_MINIO_ROOT_USER:-minioadmin}"
    local minio_pw="${NEMOCLAW_MINIO_ROOT_PASSWORD:-minioadmin}"
    echo "Waiting for MinIO healthy then ensuring bucket $bucket exists"
    for _ in $(seq 1 30); do
      if curl -sf http://localhost:9000/minio/health/live >/dev/null 2>&1; then break; fi
      sleep 1
    done
    # MC_HOST_<alias> is mc's URL-embedded-credential form. Using it inline
    # avoids needing to persist mc's config.json between `docker run --rm`
    # invocations (each one starts with empty alias state otherwise).
    docker run --rm --network=host \
      -e "MC_HOST_local=http://${minio_user}:${minio_pw}@localhost:9000" \
      minio/mc mb --ignore-existing "local/$bucket" >/dev/null
    echo "Bucket ready: local/$bucket"
  fi

  echo
  echo "Status:"
  docker compose -f "$COMPOSE_FILE" "${profile_args[@]}" ps
}

cmd_down() {
  local with_volumes=0
  case "${1:-}" in
    -v|--volumes) with_volumes=1 ;;
    "") ;;
    *) echo "Unknown flag: $1" >&2; usage >&2; exit 2 ;;
  esac

  # --profile '*' wildcards across all profiles so profile-gated containers
  # (minio, atif-export-relay) get torn down regardless of which backend was
  # active at up time. Without this, `down` silently leaves them running.
  if [[ "$with_volumes" == "1" ]]; then
    echo "Stopping host services and REMOVING NAMED VOLUMES."
    echo "  - source-etls-postgres-data (mirrored GitHub + forum data — ETLs will re-scrape)"
    echo "  - github-etl-state (ETL cursor)"
    docker compose -f "$COMPOSE_FILE" --profile '*' down -v
  else
    echo "Stopping host services (volumes preserved)."
    docker compose -f "$COMPOSE_FILE" --profile '*' down
  fi
}

case "${1:-up}" in
  up)            shift || true; cmd_up   "$@" ;;
  down)          shift;          cmd_down "$@" ;;
  -h|--help)     usage; exit 0 ;;
  *)             echo "Unknown verb: $1" >&2; usage >&2; exit 2 ;;
esac
