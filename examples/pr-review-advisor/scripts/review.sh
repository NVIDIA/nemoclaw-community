#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Stable installed-runtime contract:
#   review.sh --repo PATH (--event EVENT | --base SHA --head SHA)
#             [--repository OWNER/REPO] [--pr-number N]
#             [--acceptance-context PR_CONTEXT_JSON]
#             [--output DIR]
#
# This command is artifact-only. It cannot publish to GitHub.

set -euo pipefail
umask 077
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

repo=""
base=""
head=""
event=""
repository=""
pr_number=""
acceptance_context=""
output=""

usage() {
  cat <<'EOF'
Usage:
  review.sh --repo PATH --event EVENT_JSON
            [--acceptance-context PR_CONTEXT_JSON] [--output DIR]
  review.sh --repo PATH --base SHA --head SHA [--repository OWNER/REPO]
            [--pr-number N] [--acceptance-context PR_CONTEXT_JSON] [--output DIR]

The trusted profile is always loaded from the exact target base commit at:
  .nemoclaw/review-advisor/profile.yaml

After the Hermes API session and its private working state are removed, the
command writes review.json, review.md, verification.json, and request.json. It
never persists the raw Hermes response or creates a GitHub review/comment.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="${2:-}"; shift 2 ;;
    --base) base="${2:-}"; shift 2 ;;
    --head) head="${2:-}"; shift 2 ;;
    --event) event="${2:-}"; shift 2 ;;
    --repository) repository="${2:-}"; shift 2 ;;
    --pr-number) pr_number="${2:-}"; shift 2 ;;
    --acceptance-context) acceptance_context="${2:-}"; shift 2 ;;
    --output) output="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$repo" ]] || { echo "--repo is required" >&2; exit 2; }
if [[ -n "$event" ]]; then
  [[ -z "$base" && -z "$head" ]] || {
    echo "Use --event or --base/--head, not both" >&2
    exit 2
  }
else
  [[ -n "$base" && -n "$head" ]] || {
    echo "Provide --event or both --base and --head" >&2
    exit 2
  }
fi

scrub_external_secrets
load_env
scrub_external_secrets
require_command curl
require_command git
require_command openshell
require_command python3
validate_name "$NEMOCLAW_SANDBOX_NAME"
validate_port "$HERMES_FORWARD_PORT"

repo="$(git -C "$repo" rev-parse --show-toplevel)"

if [[ -z "$output" ]]; then
  output="$PWD/review-advisor-output"
fi

acquire_review_lock
trap release_review_lock EXIT INT TERM
ensure_api_key
assert_sandbox_ready
work="$(mktemp -d "${TMPDIR:-/tmp}/review-advisor.XXXXXXXX")"
chmod 700 "$work"
session_id=""
remote_archive=""
remote_stage=""
api_session_attempted=0
privacy_cleanup_complete=0

privacy_cleanup() {
  local failed=0
  local cleanup_ids_file="$work/cleanup-session-ids"
  local -a cleanup_ids=()

  scrub_external_secrets
  run_openshell forward stop "$HERMES_FORWARD_PORT" "$NEMOCLAW_SANDBOX_NAME" \
    >/dev/null 2>&1 || true
  if curl -fsS --max-time 2 \
    "http://127.0.0.1:${HERMES_FORWARD_PORT}/health" >/dev/null 2>&1; then
    echo "Review privacy cleanup could not stop the Hermes forward" >&2
    failed=1
  fi
  rm -f -- "$STATE_DIR/hermes-forward.log" 2>/dev/null || failed=1

  if [[ -n "$session_id" ]]; then
    cleanup_ids+=("$session_id")
  fi
  if [[ -f "$work/canonical/.session-cleanup.json" \
      && ! -L "$work/canonical/.session-cleanup.json" ]]; then
    if python3 - "$work/canonical/.session-cleanup.json" >"$cleanup_ids_file" <<'PY'
import json
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
info = path.lstat()
if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 32_768:
    raise SystemExit("unsafe session cleanup record")
record = json.loads(path.read_text(encoding="utf-8"))
ids = record.get("deleted_session_ids")
requested = record.get("requested_session_id")
if record.get("schema_version") != 1 or not isinstance(ids, list):
    raise SystemExit("invalid session cleanup record")
if not isinstance(requested, str) or requested not in ids or len(ids) > 100:
    raise SystemExit("invalid session cleanup lineage")
pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
for value in ids:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise SystemExit("invalid session ID in cleanup record")
    print(value)
PY
    then
      while IFS= read -r cleanup_id; do
        cleanup_ids+=("$cleanup_id")
      done <"$cleanup_ids_file"
    else
      echo "Review privacy cleanup rejected the session cleanup record" >&2
      failed=1
    fi
  fi

  # shellcheck disable=SC2016
  if ! run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
    bash -c '
      set -euo pipefail
      compact=$1
      stage=$2
      archive=$3
      shift 3
      current=/sandbox/review-input
      sessions=/sandbox/.hermes/sessions

      case "$stage" in
        "") ;;
        /sandbox/review-staging/review-*) rm -rf -- "$stage" ;;
        *) echo "Unsafe remote review stage: $stage" >&2; exit 1 ;;
      esac
      case "$archive" in
        "") ;;
        /tmp/review-*.tar.gz) rm -f -- "$archive" ;;
        *) echo "Unsafe remote review archive: $archive" >&2; exit 1 ;;
      esac
      chmod -R u+w "$current" 2>/dev/null || true
      find "$current" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +

      count=0
      for session in "$@"; do
        case "$session" in
          ""|*[!A-Za-z0-9._-]*)
            echo "Unsafe session ID during privacy cleanup" >&2
            exit 1
            ;;
        esac
        count=$((count + 1))
        test "$count" -le 101
        rm -f -- "$sessions/$session.json" "$sessions/$session.jsonl"
        find "$sessions" -maxdepth 1 -type f \
          -name "request_dump_${session}_*.json" -delete
      done

      if [ "$compact" = 1 ]; then
        /opt/hermes/.venv/bin/python - \
          /sandbox/.hermes/state.db /sandbox/.hermes/sessions "$@" <<'"'"'PY'"'"'
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

path, sessions_text, *requested_ids = sys.argv[1:]
info = os.lstat(path)
if not stat.S_ISREG(info.st_mode):
    raise SystemExit("Hermes state database is not a regular file")
sessions_path = Path(sessions_text)
sessions_info = sessions_path.lstat()
if sessions_path.is_symlink() or not stat.S_ISDIR(sessions_info.st_mode):
    raise SystemExit("Hermes sessions path is not a regular directory")
pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
ids = list(dict.fromkeys(requested_ids))
if not ids or len(ids) > 100 or any(not pattern.fullmatch(value) for value in ids):
    raise SystemExit("invalid exact session cleanup set")

connection = sqlite3.connect(path, timeout=30, isolation_level=None)
try:
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    resolved = set(ids)
    frontier = list(ids)
    while frontier:
        placeholders = ",".join("?" for _ in frontier)
        children = [
            row[0]
            for row in connection.execute(
                f"SELECT id FROM sessions "
                f"WHERE parent_session_id IN ({placeholders})",
                frontier,
            )
        ]
        frontier = [value for value in children if value not in resolved]
        resolved.update(frontier)
        if len(resolved) > 100:
            raise RuntimeError("Hermes session lineage exceeds 100 rows")
    ids = sorted(resolved)
    for session_id in ids:
        for suffix in (".json", ".jsonl"):
            (sessions_path / f"{session_id}{suffix}").unlink(missing_ok=True)
        for transcript in sessions_path.glob(f"request_dump_{session_id}_*.json"):
            transcript_info = transcript.lstat()
            if transcript.is_symlink() or not stat.S_ISREG(transcript_info.st_mode):
                raise RuntimeError(f"unsafe exact-session transcript: {transcript}")
            transcript.unlink()
    placeholders = ",".join("?" for _ in ids)
    connection.execute(
        f"DELETE FROM compression_locks WHERE session_id IN ({placeholders})",
        ids,
    )
    connection.execute(
        f"DELETE FROM messages WHERE session_id IN ({placeholders})",
        ids,
    )
    connection.execute(
        f"DELETE FROM sessions WHERE id IN ({placeholders})",
        ids,
    )
    remaining_messages = connection.execute(
        f"SELECT COUNT(*) FROM messages WHERE session_id IN ({placeholders})",
        ids,
    ).fetchone()[0]
    remaining_sessions = connection.execute(
        f"SELECT COUNT(*) FROM sessions WHERE id IN ({placeholders})",
        ids,
    ).fetchone()[0]
    if remaining_messages or remaining_sessions:
        raise RuntimeError("exact Hermes session rows remain after deletion")
    connection.execute("COMMIT")
    first = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if first is None or first[0] != 0:
        raise RuntimeError(f"first SQLite checkpoint stayed busy: {first!r}")
    connection.execute("VACUUM")
    second = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if second is None or second[0] != 0:
        raise RuntimeError(f"second SQLite checkpoint stayed busy: {second!r}")
except BaseException:
    if connection.in_transaction:
        connection.execute("ROLLBACK")
    raise
finally:
    connection.close()
PY
      fi

      rm -f -- /tmp/hermes.log /tmp/socat.log
      if [ -d /sandbox/.hermes/logs ]; then
        find /sandbox/.hermes/logs -maxdepth 1 -type f \
          \( -name "agent.log" -o -name "agent.log.*" \
             -o -name "errors.log" -o -name "errors.log.*" \
             -o -name "gateway.log" -o -name "gateway.log.*" \) -delete
      fi
    ' bash "$api_session_attempted" "$remote_stage" "$remote_archive" \
      "${cleanup_ids[@]}"; then
    echo "Review privacy cleanup failed inside the sandbox" >&2
    failed=1
  fi

  if [[ "$failed" == 0 ]]; then
    privacy_cleanup_complete=1
    return 0
  fi
  return 1
}

cleanup() {
  local status=$?
  local privacy_status=0
  trap - EXIT
  if [[ "$privacy_cleanup_complete" != 1 ]]; then
    privacy_cleanup || privacy_status=$?
  fi
  release_review_lock
  chmod -R u+w "$work" 2>/dev/null || true
  rm -rf "$work"
  if [[ "$status" == 0 && "$privacy_status" != 0 ]]; then
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -L "$output" || ( -e "$output" && ! -d "$output" ) ]]; then
  echo "Refusing unsafe review output directory: $output" >&2
  exit 1
fi
mkdir -p "$output"
chmod 700 "$output"
output="$(cd "$output" && pwd -P)"
for artifact_name in \
  review.json review.md verification.json request.json hermes-response.json; do
  artifact_path="$output/$artifact_name"
  if [[ -L "$artifact_path" || ( -e "$artifact_path" && ! -f "$artifact_path" ) ]]; then
    echo "Refusing unsafe review output target: $artifact_path" >&2
    exit 1
  fi
  rm -f -- "$artifact_path"
done

prepared="$work/prepared"

prepare_args=(
  --repo "$repo"
  --output "$prepared"
  --max-files "$REVIEW_ADVISOR_MAX_FILES"
  --max-context-bytes "$REVIEW_ADVISOR_MAX_CONTEXT_BYTES"
  --max-checkout-files "$REVIEW_ADVISOR_MAX_CHECKOUT_FILES"
  --max-checkout-bytes "$REVIEW_ADVISOR_MAX_CHECKOUT_BYTES"
)
if [[ -n "$event" ]]; then
  prepare_args+=(--event "$event")
else
  prepare_args+=(--base "$base" --head "$head")
  [[ -z "$repository" ]] || prepare_args+=(--repository "$repository")
  [[ -z "$pr_number" ]] || prepare_args+=(--pr-number "$pr_number")
fi
if [[ -n "$acceptance_context" ]]; then
  prepare_args+=(--acceptance-context "$acceptance_context")
fi

python3 "$DIR/prepare-review.py" "${prepare_args[@]}" >"$work/request.json"
python3 -m json.tool "$work/request.json" >/dev/null
resolved_head="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["head_sha"])' "$work/request.json")"
session_id="review-${resolved_head:0:12}-$(python3 -c 'import secrets; print(secrets.token_hex(6))')"
validate_name "$session_id"

archive="$prepared/review-input.tar.gz"
remote_archive="/tmp/${session_id}.tar.gz"
remote_stage="/sandbox/review-staging/${session_id}"

# Close the host entrypoint while trusted inputs are replaced. The plugin also
# pins context/profile digests and one detached HEAD marker when the new session
# begins, so later drift fails closed.
run_openshell forward stop "$HERMES_FORWARD_PORT" "$NEMOCLAW_SANDBOX_NAME" >/dev/null 2>&1 || true
run_openshell sandbox upload --no-git-ignore \
  "$NEMOCLAW_SANDBOX_NAME" "$archive" "$remote_archive"
# shellcheck disable=SC2016
run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  bash -c '
    set -euo pipefail
    archive=$1
    stage=$2
    current=/sandbox/review-input
    rm -rf -- "$stage"
    mkdir -p -- "$stage"
    tar -xzf "$archive" -C "$stage"
    rm -f -- "$archive"
    test -f "$stage/context.json"
    test -f "$stage/profile.yaml"
    test "$(wc -c <"$stage/attestation.key")" -eq 32
    test -f "$stage/repo/.git/HEAD"
    if find "$stage" -type l -print -quit | grep -q .; then
      echo "Trusted payload unexpectedly contains a symlink" >&2
      exit 1
    fi
    chmod -R u+w "$current" 2>/dev/null || true
    find "$current" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    cp -a "$stage"/. "$current"/
    rm -rf -- "$stage"
    find "$current" -type d -exec chmod 500 {} +
    find "$current" -type f -exec chmod 400 {} +
  ' bash "$remote_archive" "$remote_stage"

start_forward
assert_inference_route
api_session_attempted=1
python3 "$DIR/call-hermes.py" \
  --url "http://127.0.0.1:${HERMES_FORWARD_PORT}" \
  --api-key-file "$STATE_DIR/api-key" \
  --session-id "$session_id" \
  --request "$work/request.json" \
  --attestation-key-file "$prepared/payload/attestation.key" \
  --output "$work/canonical"
python3 - "$work/request.json" "$work/canonical/review.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    request = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    artifact = json.load(stream)
run = artifact.get("run")
if not isinstance(run, dict):
    raise SystemExit("artifact identity is missing")
for request_key, run_key in (
    ("repository", "repository"),
    ("base_sha", "base_sha"),
    ("merge_base_sha", "merge_base_sha"),
    ("head_sha", "head_sha"),
    ("profile_digest", "profile_digest"),
    ("profile_source_commit", "profile_source_commit"),
    ("acceptance_context_digest", "acceptance_context_digest"),
    ("pull_request_number", "pull_request_number"),
):
    if request.get(request_key) != run.get(run_key):
        raise SystemExit(
            f"artifact identity mismatch for {run_key}: "
            f"expected {request.get(request_key)!r}, got {run.get(run_key)!r}"
        )
PY

privacy_cleanup

python3 - \
  "$output" \
  "$work/request.json" \
  "$work/canonical/review.json" \
  "$work/canonical/review.md" \
  "$work/canonical/verification.json" <<'PY'
import os
import secrets
import stat
import sys
from pathlib import Path

output = Path(sys.argv[1])
info = output.lstat()
if output.is_symlink() or not stat.S_ISDIR(info.st_mode):
    raise SystemExit("unsafe review output directory")
if info.st_uid != os.geteuid():
    raise SystemExit("review output directory is not owned by the current uid")
output.chmod(0o700)

names = ("request.json", "review.json", "review.md", "verification.json")
sources = [Path(value) for value in sys.argv[2:]]
temporary: list[tuple[Path, Path]] = []
try:
    for name, source in zip(names, sources, strict=True):
        source_info = source.lstat()
        if source.is_symlink() or not stat.S_ISREG(source_info.st_mode):
            raise SystemExit(f"unsafe private review artifact: {source}")
        destination = output / name
        temporary_path = output / f".{name}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as target:
                descriptor = -1
                with source.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        temporary.append((temporary_path, destination))
    for temporary_path, destination in temporary:
        os.replace(temporary_path, destination)
        destination.chmod(0o600)
    directory_fd = os.open(output, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    for temporary_path, _destination in temporary:
        temporary_path.unlink(missing_ok=True)
PY

echo "Review artifacts:"
echo "  $output/review.json"
echo "  $output/review.md"
echo "  $output/verification.json"
echo "Publication remains disabled. Use publish.sh as a separate explicit step."
