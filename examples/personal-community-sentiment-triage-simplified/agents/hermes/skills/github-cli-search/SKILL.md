---
name: github-cli-search
description: Search GitHub issues and pull requests using the GitHub CLI for live project/community signals.
---

# github-cli-search

Use this skill when a user asks about GitHub issues, pull requests, repo
activity, tracked bugs, feature requests, or public discussion that should be
grounded in live GitHub data.

## Access model

- The sandbox includes the `gh` CLI.
- `GITHUB_TOKEN` / `GH_TOKEN` is available as `openshell:resolve:env:GITHUB_TOKEN`.
- Prefer the helper script for normalized JSON output.

## Procedure

### 1. Search across GitHub issues and PRs

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/github-cli-search/scripts/gh_search.py \
  search --query "NemoClaw bug OR error" --limit 20
```

This uses `gh search issues`, which can return both issues and pull requests.
Use GitHub search qualifiers in `--query` when useful:

```bash
/usr/bin/python3 .../gh_search.py search \
  --query "repo:NVIDIA/NemoClaw is:issue state:open label:bug"
```

### 2. Search issues or PRs inside a repo

```bash
/usr/bin/python3 .../gh_search.py issues --repo NVIDIA/NemoClaw --query "memory error" --limit 20
/usr/bin/python3 .../gh_search.py prs --repo NVIDIA/NemoClaw --query "sentiment triage" --limit 20
```

### 3. Interpret results

The helper returns JSON:

```json
{
  "ok": true,
  "mode": "issues",
  "count": 2,
  "items": [
    {
      "number": 42,
      "title": "Bug title",
      "state": "OPEN",
      "url": "https://github.com/...",
      "updatedAt": "2026-05-01T..."
    }
  ]
}
```

Use GitHub URLs and item numbers in answers. For deeper context, run `gh issue
view` or `gh pr view` directly with `--json body,comments`.

## Pitfalls

- GitHub search syntax matters. If results look weak, refine with `repo:`,
  `org:`, `is:issue`, `is:pr`, `state:open`, labels, or date qualifiers.
- Distinguish between GitHub's live state and sampled Slack/Tavily findings.
- If `gh` reports auth or rate-limit problems, tell the user `GITHUB_TOKEN`
  may need to be refreshed.
