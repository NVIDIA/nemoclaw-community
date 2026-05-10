#!/usr/bin/python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


SEARCH_FIELDS = [
    "number",
    "title",
    "state",
    "url",
    "repository",
    "body",
    "createdAt",
    "updatedAt",
    "commentsCount",
    "isPullRequest",
]
ISSUE_FIELDS = ["number", "title", "state", "url", "body", "createdAt", "updatedAt", "comments"]
PR_FIELDS = ["number", "title", "state", "url", "body", "createdAt", "updatedAt", "comments"]


def with_auth_env() -> dict[str, str]:
    env = dict(os.environ)
    token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or "openshell:resolve:env:GITHUB_TOKEN"
    env["GITHUB_TOKEN"] = token
    env["GH_TOKEN"] = token
    return env


def run_gh(cmd: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=60,
        env=with_auth_env(),
    )
    return result.returncode, result.stdout, result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description="Search GitHub with gh and return JSON")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    search = subparsers.add_parser("search", help="Search across GitHub issues and PRs")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=20)

    issues = subparsers.add_parser("issues", help="Search issues within a repo")
    issues.add_argument("--repo", required=True)
    issues.add_argument("--query", default="")
    issues.add_argument("--state", choices=["open", "closed", "all"], default="all")
    issues.add_argument("--limit", type=int, default=20)

    prs = subparsers.add_parser("prs", help="Search pull requests within a repo")
    prs.add_argument("--repo", required=True)
    prs.add_argument("--query", default="")
    prs.add_argument("--state", choices=["open", "closed", "merged", "all"], default="all")
    prs.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    limit = str(max(1, min(args.limit, 100)))

    if args.mode == "search":
      cmd = [
          "gh", "search", "issues", args.query,
          "--limit", limit,
          "--json", ",".join(SEARCH_FIELDS),
      ]
    elif args.mode == "issues":
      cmd = [
          "gh", "issue", "list",
          "--repo", args.repo,
          "--state", args.state,
          "--limit", limit,
          "--json", ",".join(ISSUE_FIELDS),
      ]
      if args.query:
          cmd.extend(["--search", args.query])
    else:
      cmd = [
          "gh", "pr", "list",
          "--repo", args.repo,
          "--state", args.state,
          "--limit", limit,
          "--json", ",".join(PR_FIELDS),
      ]
      if args.query:
          cmd.extend(["--search", args.query])

    returncode, stdout, stderr = run_gh(cmd)
    if returncode != 0:
        print(json.dumps({
            "ok": False,
            "mode": args.mode,
            "command": cmd[:3],
            "error": stderr.strip()[:2000],
        }, indent=2))
        return returncode

    try:
        items = json.loads(stdout or "[]")
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "mode": args.mode, "error": f"invalid gh JSON: {exc}"}))
        return 1

    print(json.dumps({
        "ok": True,
        "mode": args.mode,
        "count": len(items),
        "items": items,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
