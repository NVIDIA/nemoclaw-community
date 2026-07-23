#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Explicit host-only publisher. This process never loads .env and scrubs
# supported inherited inference credentials before invoking GitHub tooling.

set -euo pipefail
unset \
  NVIDIA_INFERENCE_API_KEY NVIDIA_API_KEY NGC_API_KEY COMPATIBLE_API_KEY \
  OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY TOGETHER_API_KEY \
  GROQ_API_KEY MISTRAL_API_KEY COHERE_API_KEY GOOGLE_API_KEY GEMINI_API_KEY \
  AZURE_OPENAI_API_KEY AZURE_API_KEY DEEPINFRA_API_KEY \
  HF_TOKEN HUGGING_FACE_HUB_TOKEN \
  AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

artifact=""
receipt=""
repository=""
pr_number=""
expected_head=""
confirm=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact) artifact="${2:-}"; shift 2 ;;
    --receipt) receipt="${2:-}"; shift 2 ;;
    --repo) repository="${2:-}"; shift 2 ;;
    --pr) pr_number="${2:-}"; shift 2 ;;
    --head) expected_head="${2:-}"; shift 2 ;;
    --confirm-publish) confirm=1; shift ;;
    -h|--help)
      echo "Usage: publish.sh --artifact review.json [--receipt verification.json] --repo OWNER/REPO --pr N --head SHA --confirm-publish"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "$confirm" == 1 ]] || {
  echo "Publication is a write action. Rerun with --confirm-publish." >&2
  exit 2
}
[[ -f "$artifact" && ! -L "$artifact" ]] || { echo "--artifact must be a regular file" >&2; exit 2; }
if [[ -z "$receipt" ]]; then
  receipt="$(dirname "$artifact")/verification.json"
fi
[[ -f "$receipt" && ! -L "$receipt" ]] || {
  echo "--receipt must be a regular file (defaults to verification.json beside the artifact)" >&2
  exit 2
}
[[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo "Invalid --repo" >&2; exit 2; }
[[ "$pr_number" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid --pr" >&2; exit 2; }
[[ "$expected_head" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid --head" >&2; exit 2; }
command -v gh >/dev/null 2>&1 || { echo "Required command not found: gh" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Required command not found: python3" >&2; exit 1; }

work="$(mktemp -d "${TMPDIR:-/tmp}/review-publish.XXXXXXXX")"
trap 'rm -rf "$work"' EXIT INT TERM
python3 - "$artifact" "$receipt" "$repository" "$pr_number" "$expected_head" >"$work/review.md" <<'PY'
import html
import hashlib
import hmac
import json
import os
import pathlib
import re
import stat
import sys

path_text, receipt_text, repository, pr_text, expected_head = sys.argv[1:]
path = pathlib.Path(path_text)
receipt_path = pathlib.Path(receipt_text)


def read_regular(input_path, label, maximum):
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(input_path, flags)
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


artifact_bytes = read_regular(path, "artifact", 16 * 1024 * 1024)
receipt_bytes = read_regular(receipt_path, "verification receipt", 64 * 1024)
artifact = json.loads(artifact_bytes)
receipt = json.loads(receipt_bytes.decode("utf-8"))
if receipt.get("schema_version") != "review-advisor-verification/v1":
    raise SystemExit("verification receipt schema is invalid")
if receipt.get("artifact") != path.name:
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
summary = artifact.get("summary")
findings = artifact.get("findings")
if not isinstance(run, dict) or not isinstance(summary, dict) or not isinstance(findings, list):
    raise SystemExit("artifact shape is invalid")
if run.get("repository") != repository:
    raise SystemExit("artifact repository does not match --repo")
if run.get("pull_request_number") != int(pr_text):
    raise SystemExit("artifact pull request number does not match --pr")
if run.get("head_sha") != expected_head:
    raise SystemExit("artifact head does not match --head")
if receipt.get("attestation_digest") != artifact.get("attestation", {}).get("digest"):
    raise SystemExit("verification receipt attestation does not match artifact")
if receipt.get("run") != {
    key: run.get(key)
    for key in (
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
}:
    raise SystemExit("verification receipt run identity does not match artifact")

def bounded_text(value: object) -> str:
    text = str(value if value is not None else "")
    return "".join(
        character
        if character in "\n\t" or (ord(character) >= 0x20 and ord(character) != 0x7F)
        else "\N{REPLACEMENT CHARACTER}"
        for character in text
    )

def markdown_text(value: object, *, single_line: bool = False) -> str:
    text = bounded_text(value)
    if single_line:
        text = " ".join(text.splitlines())
    text = text.replace("@", "@\N{ZERO WIDTH SPACE}")
    text = html.escape(text, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>~])", r"\\\1", text)

def code_span(value: object) -> str:
    text = " ".join(bounded_text(value).splitlines())
    text = text.replace("@", "@\N{ZERO WIDTH SPACE}")
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    delimiter = "`" * (longest + 1)
    if text.startswith(("`", " ")) or text.endswith(("`", " ")):
        text = f" {text} "
    return f"{delimiter}{text}{delimiter}"

print("<!-- nemoclaw-review-advisor:v1 -->")
print("# NemoClaw Review Advisor\n")
print(f"**Recommendation:** {code_span(summary.get('recommendation', 'unknown'))}  ")
print(f"**Confidence:** {code_span(summary.get('confidence', 'unknown'))}  ")
print(f"**Exact head:** {code_span(run['head_sha'])}\n")
print(markdown_text(summary.get("one_line", "")).strip())
print("\n## Findings\n")
if not findings:
    print("No open findings.")
for finding in findings:
    title = markdown_text(
        finding.get("title", "Untitled finding"),
        single_line=True,
    )
    print(
        f"### {markdown_text(finding.get('id', 'F-???'), single_line=True)} · "
        f"{markdown_text(finding.get('severity', 'unknown'), single_line=True)} · {title}\n"
    )
    location = (
        f"{finding.get('file', '')}:{finding.get('line', '')}"
    )
    print(
        f"{code_span(location)} "
        f"({code_span(finding.get('side', 'head'))} side)\n"
    )
    print(markdown_text(finding.get("description", "")).strip() + "\n")
    print(f"**Impact:** {markdown_text(finding.get('impact', '')).strip()}\n")
    print(
        f"**Recommendation:** "
        f"{markdown_text(finding.get('recommendation', '')).strip()}\n"
    )
limitations = artifact.get("limitations", [])
if limitations:
    print("## Limitations\n")
    for item in limitations:
        print(f"- {markdown_text(item.get('description', '')).strip()}")
    print()
print("---")
print(
    f"Profile {code_span(run.get('profile_digest', ''))} · "
    f"Context {code_span(run.get('context_digest', ''))}"
)
PY

comment_bytes="$(python3 -c 'import os,sys; print(os.lstat(sys.argv[1]).st_size)' "$work/review.md")"
(( comment_bytes <= 61440 )) || {
  echo "Rendered review comment exceeds the 61440-byte publication limit" >&2
  exit 1
}

read -r artifact_base acceptance_digest < <(
  python3 - "$artifact" <<'PY'
import json
import sys

run = json.load(open(sys.argv[1], encoding="utf-8"))["run"]
print(run["base_sha"], run.get("acceptance_context_digest") or "-")
PY
)

# The bounded acceptance snapshot is the final publication guard. It rechecks
# that the PR is open at the exact base/head and, when review-time acceptance
# evidence existed, that its mutable title/body/closing-issue content is
# byte-for-byte unchanged.
if [[ "$acceptance_digest" != "-" ]]; then
  live_acceptance="$work/live-acceptance.json"
  github_token="$(gh auth token)"
  [[ -n "$github_token" && ${#github_token} -le 4096 ]] || {
    echo "gh auth token did not return a bounded token" >&2
    exit 1
  }
  NEMOCLAW_GITHUB_TOKEN="$github_token" \
    python3 "$DIR/fetch-pr-context.py" \
      --repository "$repository" \
      --pr-number "$pr_number" \
      --base "$artifact_base" \
      --head "$expected_head" \
      --output "$live_acceptance" >/dev/null
  github_token=""
  unset github_token
  live_acceptance_digest="$(
    python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' \
      "$live_acceptance"
  )"
  [[ "$live_acceptance_digest" == "$acceptance_digest" ]] || {
    echo "Stale artifact: current PR acceptance context changed after review" >&2
    exit 1
  }
else
  live="$(gh api "repos/$repository/pulls/$pr_number" \
    --jq '[.state,.base.sha,.head.sha] | @tsv')"
  IFS=$'\t' read -r live_state live_base live_head <<<"$live"
  [[ "$live_state" == "open" ]] || {
    echo "PR is not open (state: $live_state)" >&2
    exit 1
  }
  [[ "$live_head" == "$expected_head" ]] || {
    echo "Stale artifact: live head is $live_head, expected $expected_head" >&2
    exit 1
  }
  [[ "$live_base" == "$artifact_base" ]] || {
    echo "Stale artifact: live base is $live_base, artifact base is $artifact_base" >&2
    exit 1
  }
fi

gh pr comment "$pr_number" --repo "$repository" --body-file "$work/review.md"
