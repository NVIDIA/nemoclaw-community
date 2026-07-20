# SPDX-FileCopyrightText: Copyright (c) 2026 munnamihir
# SPDX-License-Identifier: Apache-2.0
---
name: github-pr-review
description: Watch a GitHub repository for new pull requests, review their diffs using NemoClaw inference, and post structured review comments automatically.
---

# github-pr-review

Use this skill to autonomously review GitHub pull requests on a schedule.

## When to use

- Periodically check for new open PRs (every 15 minutes by default)
- Fetch the unified diff for each unreviewed PR
- Generate a structured code review using NemoClaw inference
- Post the review as a GitHub comment
- Track which PRs have already been reviewed

## Access model

- The target repository is `$GITHUB_REPO` (owner/repo format)
- GitHub token is loaded from `GITHUB_TOKEN` — treat as a secret placeholder
- Only the following GitHub API calls are permitted by policy:
  - GET `/repos/$GITHUB_REPO/pulls` — list open PRs
  - GET `/repos/$GITHUB_REPO/pulls/<number>` — get PR diff
  - POST `/repos/$GITHUB_REPO/issues/<number>/comments` — post review comment
- Do not print, echo, or inspect the token variable

## Procedure

Run the bundled helper script via the terminal tool:

```bash
# Check for new PRs and review them
/usr/bin/python3 /sandbox/.hermes-data/skills/github-pr-review/scripts/pr_review.py check

# Run in always-on mode (polls every 15 minutes)
/usr/bin/python3 /sandbox/.hermes-data/skills/github-pr-review/scripts/pr_review.py watch

# Review a specific PR by number
/usr/bin/python3 /sandbox/.hermes-data/skills/github-pr-review/scripts/pr_review.py review <number>
```

## Review format

Each posted review follows this structure:🤖 NemoClaw PR Review Agent
Summary
One sentence describing what this PR does.
What looks good

Bullet points of positives

Suggestions

Specific, actionable improvements

Verdict
APPROVE / REQUEST_CHANGES / COMMENT
## Pitfalls

- Track reviewed PRs in `/tmp/reviewed_prs.json` to avoid double-reviewing
- If GitHub returns 403, the policy is blocking the request — check policy.yaml
- Diff truncated to 3000 chars to stay within inference context window
