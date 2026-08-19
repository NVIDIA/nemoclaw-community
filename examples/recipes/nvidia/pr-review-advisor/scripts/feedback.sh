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


def canonical_repo_path(value, label, maximum=4_096):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise SystemExit(f"{label} must be a nonempty bounded string")
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise SystemExit(f"{label} must be a checkout-relative POSIX path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise SystemExit(f"{label} must be a canonical checkout-relative path")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise SystemExit(f"{label} contains a control character")
    portable = tuple(part.casefold().rstrip(" .") for part in parts)
    if any(not part for part in portable) or ".git" in portable:
        raise SystemExit(f"{label} is not a portable review path")
    return value


def validate_review_scope(value):
    if not isinstance(value, dict) or set(value) != {
        "mode",
        "roots",
        "support_paths",
    }:
        raise SystemExit("artifact review scope has an invalid shape")
    mode = value["mode"]
    if mode not in ("repository", "scoped"):
        raise SystemExit("artifact review scope mode is invalid")

    def paths(key):
        raw = value[key]
        if not isinstance(raw, list) or len(raw) > 10_000:
            raise SystemExit(f"artifact review scope {key} is invalid")
        result = [
            canonical_repo_path(path, f"artifact review scope {key}[{index}]")
            for index, path in enumerate(raw)
        ]
        portable = [
            tuple(part.casefold().rstrip(" .") for part in path.split("/"))
            for path in result
        ]
        if result != sorted(result) or len(result) != len(set(result)):
            raise SystemExit(f"artifact review scope {key} is not canonical")
        if len(portable) != len(set(portable)):
            raise SystemExit(f"artifact review scope {key} has portable collisions")
        return result

    roots = paths("roots")
    support_paths = paths("support_paths")
    if mode == "repository":
        if roots or support_paths:
            raise SystemExit("repository review scope must have no selected paths")
    elif not roots:
        raise SystemExit("scoped review scope must have at least one root")
    for index, root in enumerate(roots):
        if any(other.startswith(f"{root}/") for other in roots[index + 1 :]):
            raise SystemExit("artifact review scope roots overlap")
    for index, support in enumerate(support_paths):
        if any(
            other.startswith(f"{support}/")
            for other in support_paths[index + 1 :]
        ):
            raise SystemExit("artifact review scope support paths overlap")
        if any(
            support == root
            or support.startswith(f"{root}/")
            or root.startswith(f"{support}/")
            for root in roots
        ):
            raise SystemExit("artifact review scope roots and support paths overlap")
    return {
        "mode": mode,
        "roots": roots,
        "support_paths": support_paths,
    }


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
review_scope = validate_review_scope(run.get("review_scope"))
scope_digest = run.get("scope_digest")
if not isinstance(scope_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", scope_digest):
    raise SystemExit("artifact scope digest is invalid")
expected_scope_digest = hashlib.sha256(
    json.dumps(
        review_scope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
).hexdigest()
if not hmac.compare_digest(scope_digest, expected_scope_digest):
    raise SystemExit("artifact scope digest does not match its review scope")
canonical_repo_path(run.get("profile_path"), "artifact profile path")
if run.get("profile_origin") not in ("target_base", "operator_bootstrap"):
    raise SystemExit("artifact profile origin is invalid")
profile_object_id = run.get("profile_object_id")
if not isinstance(profile_object_id, str) or not re.fullmatch(
    r"(?:[0-9a-f]{40}|[0-9a-f]{64})",
    profile_object_id,
):
    raise SystemExit("artifact profile object ID is invalid")
if receipt.get("attestation_digest") != artifact.get("attestation", {}).get("digest"):
    raise SystemExit("verification receipt attestation does not match artifact")
run_keys = (
    "repository",
    "base_sha",
    "merge_base_sha",
    "head_sha",
    "profile_digest",
    "profile_source_commit",
    "review_scope",
    "scope_digest",
    "profile_path",
    "profile_origin",
    "profile_object_id",
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
):
    raise SystemExit("candidate paths are invalid")
try:
    paths = [
        canonical_repo_path(path, f"candidate paths[{index}]", maximum=256)
        for index, path in enumerate(paths)
    ]
except SystemExit as error:
    raise SystemExit("candidate paths are invalid") from error
if review_scope["mode"] == "scoped":
    roots = review_scope["roots"]
    support_paths = review_scope["support_paths"]
    for path in paths:
        if not (
            any(path == root or path.startswith(f"{root}/") for root in roots)
            or any(
                path == support or path.startswith(f"{support}/")
                for support in support_paths
            )
        ):
            raise SystemExit(
                f"candidate path is outside the configured review scope: {path}"
            )
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
    "scope_digest",
    "profile_path",
    "profile_origin",
    "profile_object_id",
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
    "review_scope": review_scope,
    "scope_digest": run["scope_digest"],
    "profile_path": run["profile_path"],
    "profile_origin": run["profile_origin"],
    "profile_object_id": run["profile_object_id"],
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
artifact_scope_digest="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["scope_digest"])' "$work/feedback.json")"
[[ "$artifact_scope_digest" == "$REVIEW_ADVISOR_SCOPE_DIGEST" ]] || {
  echo "Feedback artifact belongs to a different configured review scope" >&2
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
