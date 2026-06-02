#!/usr/bin/env python3
# Quick script to auto-review GitHub PRs using a local llama model via Ollama.
# Runs inside NemoClaw/OpenShell sandbox - only talks to github and inference.local
#
# Usage:
#   export GITHUB_TOKEN=...
#   export GITHUB_REPO=owner/repo
#   python3 agent.py
#
# For local testing without sandbox, make sure ollama is running first:
#   ollama serve
#   ollama pull llama3.2

import os
import sys
import json
import urllib.request
import urllib.error

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")

# inside openshell sandbox this gets overridden to inference.local automatically
INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://localhost:11434/api/chat")
MODEL = os.environ.get("MODEL", "llama3.2")

if not GITHUB_TOKEN or not GITHUB_REPO:
    print("need GITHUB_TOKEN and GITHUB_REPO set")
    sys.exit(1)


def gh(path, method="GET", body=None):
    # wrapper around github api calls so I don't repeat headers everywhere
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "pr-review-bot",
        },
        method=method,
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def get_prs():
    return gh(f"/repos/{GITHUB_REPO}/pulls?state=open&per_page=10")


def get_diff(pr_number):
    # github needs a different accept header to return raw diff
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_number}",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.diff",
            "User-Agent": "pr-review-bot",
        },
    )
    with urllib.request.urlopen(req) as r:
        return r.read().decode("utf-8", errors="replace")


def ask_model(pr_title, diff):
    # truncate diff so we don't blow up context window
    truncated = diff[:3000]
    if len(diff) > 3000:
        truncated += "\n... (diff truncated)"

    prompt = f"""You are reviewing a pull request as a senior engineer.

PR: {pr_title}

{truncated}

Give a short review covering:
- what this PR does (1 sentence)
- what looks good
- anything you'd change or flag
- your verdict: APPROVE, REQUEST_CHANGES, or COMMENT

Keep it under 250 words, be direct."""

    req = urllib.request.Request(
        INFERENCE_URL,
        data=json.dumps({
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["message"]["content"]


def post_comment(pr_number, review):
    gh(
        f"/repos/{GITHUB_REPO}/issues/{pr_number}/comments",
        method="POST",
        body={"body": f"**NemoClaw PR Review Agent**\n\n{review}"},
    )


def main():
    print(f"checking PRs for {GITHUB_REPO}")
    prs = get_prs()

    if not prs:
        print("no open PRs")
        return

    for pr in prs:
        num = pr["number"]
        title = pr["title"]
        author = pr["user"]["login"]
        print(f"\nPR #{num} by @{author}: {title}")

        diff = get_diff(num)
        print("  got diff, sending to model...")

        review = ask_model(title, diff)
        print("  posting comment...")

        post_comment(num, review)
        print(f"  done")

    print("\nfinished")


if __name__ == "__main__":
    main()
