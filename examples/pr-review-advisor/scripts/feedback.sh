#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
umask 077
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"
scrub_external_secrets

artifact=""
receipt=""
candidate=""
disposition=""
lesson=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact) artifact="${2:-}"; shift 2 ;;
    --receipt) receipt="${2:-}"; shift 2 ;;
    --candidate) candidate="${2:-}"; shift 2 ;;
    --disposition) disposition="${2:-}"; shift 2 ;;
    --lesson) lesson="${2:-}"; shift 2 ;;
    -h|--help)
      echo "Usage: feedback.sh --artifact review.json [--receipt verification.json] --candidate L-... --disposition accepted|dismissed|corrected --lesson TEXT"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -f "$artifact" && ! -L "$artifact" ]] || { echo "--artifact must be a regular file" >&2; exit 2; }
if [[ -z "$receipt" ]]; then
  receipt="$(dirname "$artifact")/verification.json"
fi
[[ -f "$receipt" && ! -L "$receipt" ]] || {
  echo "--receipt must be a regular file (defaults to verification.json beside the artifact)" >&2
  exit 2
}
[[ "$candidate" =~ ^L-[0-9a-f]{16}$ ]] || { echo "--candidate must be an L- identifier" >&2; exit 2; }
case "$disposition" in
  accepted|dismissed|corrected) ;;
  *) echo "--disposition must be accepted, dismissed, or corrected" >&2; exit 2 ;;
esac
[[ -n "$lesson" ]] || {
  echo "--lesson is required and must be authored by the maintainer" >&2
  exit 2
}

require_command python3
work="$(mktemp -d "${TMPDIR:-/tmp}/review-feedback.XXXXXXXX")"
trap 'rm -rf "$work"' EXIT INT TERM

python3 - "$artifact" "$receipt" "$candidate" "$disposition" "$lesson" >"$work/feedback.json" <<'PY'
import hashlib
import hmac
import json
import os
import pathlib
import re
import stat
import sys

artifact_text, receipt_text, candidate_id, disposition, lesson_value = sys.argv[1:]


def bounded_text(value, label, maximum):
    if not isinstance(value, str):
        raise SystemExit(f"{label} must be a string")
    normalized = " ".join(value.split())
    if not normalized:
        raise SystemExit(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise SystemExit(f"{label} exceeds {maximum} characters")
    return normalized


lesson = bounded_text(lesson_value, "--lesson", 700)
artifact_path = pathlib.Path(artifact_text)
receipt_path = pathlib.Path(receipt_text)


def read_regular(path, label, maximum):
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SystemExit(f"{label} must be a readable regular non-symlink file") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SystemExit(f"{label} must be a regular non-symlink file")
        if info.st_size > maximum:
            raise SystemExit(f"{label} exceeds {maximum} bytes")
        content = bytearray()
        while len(content) <= maximum:
            chunk = os.read(descriptor, min(65_536, maximum + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        if len(content) > maximum:
            raise SystemExit(f"{label} exceeds {maximum} bytes")
        return bytes(content)
    finally:
        os.close(descriptor)


artifact_bytes = read_regular(artifact_path, "artifact", 16 * 1024 * 1024)
receipt_bytes = read_regular(receipt_path, "verification receipt", 64 * 1024)
artifact = json.loads(artifact_bytes)
receipt = json.loads(receipt_bytes.decode("utf-8"))
if receipt.get("schema_version") != "review-advisor-verification/v1":
    raise SystemExit("verification receipt schema is invalid")
if receipt.get("artifact") != artifact_path.name:
    raise SystemExit("verification receipt artifact name does not match")
expected_digest = receipt.get("artifact_sha256")
if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
    raise SystemExit("verification receipt artifact digest is invalid")
if not hmac.compare_digest(hashlib.sha256(artifact_bytes).hexdigest(), expected_digest):
    raise SystemExit("artifact changed after host verification")
if receipt.get("verified") != [
    "hmac-sha256",
    "trusted-request-identity",
    "hermes-session-deleted",
]:
    raise SystemExit("verification receipt does not record required checks")
if artifact.get("schema_version") != "review-advisor/v1":
    raise SystemExit("artifact is not review-advisor/v1")
run = artifact.get("run")
if not isinstance(run, dict):
    raise SystemExit("artifact.run is invalid")
if receipt.get("attestation_digest") != artifact.get("attestation", {}).get("digest"):
    raise SystemExit("verification receipt attestation does not match artifact")
run_keys = (
    "repository",
    "base_sha",
    "merge_base_sha",
    "head_sha",
    "profile_digest",
    "profile_source_commit",
    "acceptance_context_digest",
    "context_digest",
    "pull_request_number",
)
if receipt.get("run") != {key: run.get(key) for key in run_keys}:
    raise SystemExit("verification receipt run identity does not match artifact")
candidates = artifact.get("lesson_candidates")
if not isinstance(candidates, list):
    raise SystemExit("artifact.lesson_candidates is invalid")
match = next(
    (item for item in candidates if isinstance(item, dict) and item.get("candidate_id") == candidate_id),
    None,
)
if match is None:
    raise SystemExit(f"candidate not found: {candidate_id}")
evidence = match.get("evidence")
if (
    not isinstance(evidence, list)
    or not evidence
    or len(evidence) > 100
    or any(
        not isinstance(item, str)
        or not item.strip()
        or len(item) > 4_096
        for item in evidence
    )
):
    raise SystemExit("candidate evidence is invalid")
paths = match.get("paths")
if (
    not isinstance(paths, list)
    or len(paths) > 20
    or any(
        not isinstance(path, str)
        or not path
        or len(path) > 256
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or ".." in pathlib.PurePosixPath(path).parts
        for path in paths
    )
):
    raise SystemExit("candidate paths are invalid")
source = match.get("source")
if not isinstance(source, dict):
    raise SystemExit("candidate source is invalid")
for key in (
    "repository",
    "base_sha",
    "merge_base_sha",
    "head_sha",
    "profile_digest",
    "profile_source_commit",
    "acceptance_context_digest",
    "context_digest",
):
    if source.get(key) != run.get(key):
        raise SystemExit(f"candidate source does not match artifact run: {key}")
evidence_digest = hashlib.sha256(
    json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
).hexdigest()
payload = {
    "repository": run["repository"],
    "base_sha": run["base_sha"],
    "merge_base_sha": run["merge_base_sha"],
    "head_sha": run["head_sha"],
    "profile_digest": run["profile_digest"],
    "profile_source_commit": run["profile_source_commit"],
    "acceptance_context_digest": run["acceptance_context_digest"],
    "context_digest": run["context_digest"],
    "candidate_id": candidate_id,
    "disposition": disposition,
    "lesson": lesson,
    "paths": paths,
    "evidence_digest": evidence_digest,
}
json.dump(payload, sys.stdout, sort_keys=True)
sys.stdout.write("\n")
PY

load_env
scrub_external_secrets
acquire_review_lock
trap 'release_review_lock; rm -rf "$work"' EXIT INT TERM
expected_repository="$REVIEW_ADVISOR_REPOSITORY"
artifact_repository="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["repository"])' "$work/feedback.json")"
[[ "$artifact_repository" == "$expected_repository" ]] || {
  echo "Feedback artifact belongs to $artifact_repository, not this installation ($expected_repository)" >&2
  exit 1
}
require_command openshell
assert_sandbox_ready

remote="/tmp/review-feedback-${candidate}.json"
run_openshell sandbox upload --no-git-ignore \
  "$NEMOCLAW_SANDBOX_NAME" "$work/feedback.json" "$remote"
set +e
result="$(run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  /opt/hermes/.venv/bin/python /opt/review-advisor/record-feedback.py "$remote")"
status=$?
set -e
run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  rm -f "$remote" >/dev/null
printf '%s\n' "$result"
[[ "$status" == 0 ]] || exit "$status"
echo "Feedback recorded. It becomes visible to the next fresh Hermes review session."
