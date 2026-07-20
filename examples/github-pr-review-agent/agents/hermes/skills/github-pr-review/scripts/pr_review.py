#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 munnamihir
# SPDX-License-Identifier: Apache-2.0
#
# PR Review helper script for the github-pr-review Hermes skill.
# Watches a GitHub repo for new PRs, reviews diffs, posts comments.
#
# Usage:
#   python3 pr_review.py check          # check once for new PRs
#   python3 pr_review.py watch          # poll every 15 minutes (always-on)
#   python3 pr_review.py review <num>   # review a specific PR

import os
import sys
import json
import time
import urllib.request
import urllib.error

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")
INFERENCE_URL = os.environ.get(
    "INFERENCE_URL",
    "https://integrate.api.nvidia.com/v1/chat/completions"
)
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
MODEL = os.environ.get("MODEL", "nvidia/llama-3.1-nemotron-ultra-253b-v1")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "900"))  # 15 min
REVIEWED_PATH = "/tmp/reviewed_prs.json"

if not GITHUB_REPO:
    print("ERROR: GITHUB_REPO not set (owner/repo format)")
    sys.exit(1)


def load_reviewed():
    try:
        with open(REVIEWED_PATH) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_reviewed(reviewed):
    with open(REVIEWED_PATH, "w") as f:
        json.dump(list(reviewed), f)


def gh(path, method="GET", body=None, accept="application/vnd.github+json"):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "nemoclaw-pr-review-agent/2.0",
        },
        method=method,
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read()) if accept != "application/vnd.github.diff" else r.read().decode("utf-8", errors="replace")


def get_open_prs():
    return gh(f"/repos/{GITHUB_REPO}/pulls?state=open&per_page=20")


def get_diff(number):
    return gh(
        f"/repos/{GITHUB_REPO}/pulls/{number}",
        accept="application/vnd.github.diff"
    )


def review_diff(title, diff):
    truncated = diff[:3000]
    if len(diff) > 3000:
        truncated += "\n... (diff truncated)"

    prompt = f"""You are reviewing a pull request as a senior engineer.

PR: {title}

{truncated}

Write a concise review covering:
- What this PR does (1 sentence)
- What looks good
- Anything to change or flag
- Verdict: APPROVE, REQUEST_CHANGES, or COMMENT

Keep it under 250 words. Be direct."""

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.3,
    }

    headers = {
        "Content-Type": "application/json",
    }
    if NVIDIA_API_KEY:
        headers["Authorization"] = f"Bearer {NVIDIA_API_KEY}"

    req = urllib.request.Request(
        INFERENCE_URL,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    return result["choices"][0]["message"]["content"]


def post_comment(number, review):
    gh(
        f"/repos/{GITHUB_REPO}/issues/{number}/comments",
        method="POST",
        body={"body": f"🤖 **NemoClaw PR Review Agent**\n\n{review}"},
    )


def check_once(reviewed):
    print(f"checking PRs for {GITHUB_REPO}...")
    prs = get_open_prs()

    if not prs:
        print("no open PRs")
        return reviewed

    new_count = 0
    for pr in prs:
        num = pr["number"]
        title = pr["title"]
        author = pr["user"]["login"]

        if num in reviewed:
            print(f"  PR #{num} already reviewed, skipping")
            continue

        print(f"\nPR #{num} by @{author}: {title}")
        diff = get_diff(num)
        print("  got diff, reviewing...")
        review = review_diff(title, diff)
        print("  posting comment...")
        post_comment(num, review)
        reviewed.add(num)
        save_reviewed(reviewed)
        print(f"  done — PR #{num} reviewed")
        new_count += 1

    print(f"\nfinished — {new_count} new PRs reviewed")
    return reviewed


def main():
    if len(sys.argv) < 2:
        print("usage: pr_review.py [check|watch|review <number>]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "review" and len(sys.argv) >= 3:
        number = int(sys.argv[2])
        pr = gh(f"/repos/{GITHUB_REPO}/pulls/{number}")
        diff = get_diff(number)
        review = review_diff(pr["title"], diff)
        post_comment(number, review)
        print(f"reviewed PR #{number}")

    elif cmd == "check":
        reviewed = load_reviewed()
        check_once(reviewed)

    elif cmd == "watch":
        print(f"starting always-on watch mode (polling every {POLL_INTERVAL}s)")
        reviewed = load_reviewed()
        while True:
            try:
                reviewed = check_once(reviewed)
            except Exception as e:
                print(f"error: {e}")
            print(f"sleeping {POLL_INTERVAL}s...")
            time.sleep(POLL_INTERVAL)

    else:
        print(f"unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
