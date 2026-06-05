---
name: github-readonly-live
description: Read the configured live GitHub repository through authenticated, policy-scoped GitHub REST GET requests.
---

# github-readonly-live

Use this skill for current live GitHub REST data from the single repository
allowed by the sandbox policy.

## When to use

- Inspect the currently allowed live GitHub repository.
- Read current issues, issue comments, pull requests, pull request files,
  reviews, commits, branches, labels, milestones, README, or repository
  contents.
- Check live state when the source ETL mirror may be stale or empty.

Do not use this skill for GitHub discussions or NVIDIA forums. Use
`source-etl-query` for those mirrored sources.

## Access model

- The allowed repository is `$GITHUB_READONLY_REPO`.
- Requests use the OpenShell GitHub provider placeholder from `GITHUB_TOKEN`.
  Treat it as a secret placeholder: do not print
  it, modify it, or copy it into responses.
- Do not run `env`, `printenv`, `echo`, or similar commands against
  `GITHUB_TOKEN`. The helper loads the placeholder itself.
- Do not inspect `.env` files, shell environments, proxy settings, or token
  variables to troubleshoot GitHub. If the helper cannot authenticate or reach
  GitHub, it will report the error itself.
- Only repo-scoped `GET` requests to `api.github.com` are allowed.
- Do not use `gh`, `git`, `github.com`, `raw.githubusercontent.com`,
  `codeload.github.com`, GraphQL, or GitHub search endpoints.
- If a request returns an OpenShell policy 403, report the policy scope instead
  of trying another GitHub host, another binary, or a write-like method.
- If explicitly asked to validate that a write is blocked, do not inspect the
  token variable. Use direct shell expansion in the Authorization header and
  report only the policy error.

Write-block validation pattern:

```bash
auth="${GITHUB_TOKEN:-}"
curl -sS -o /tmp/github-write-denied.json -w 'HTTP Status: %{http_code}\n' \
  -X POST \
  -H "Authorization: Bearer ${auth}" \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  "https://api.github.com/repos/${GITHUB_READONLY_REPO:-NVIDIA/OpenShell}/issues/<number>/comments" \
  -d '{"body":"policy-validation-test"}'
cat /tmp/github-write-denied.json
```

## Procedure

Always run the bundled helper script via the terminal tool. It constructs only
repo-scoped GitHub REST GET requests. Prefer the generic `get` command and map
the user's question to a repo-relative REST route plus query params.
Do not invoke `github-readonly-live` as a shell command; it is the skill name,
not an executable. Do not call a tool named `github-readonly-live`; use
`skill_view` only if you need to read this instruction file.
Do not search for GitHub binaries with `which`, `command -v`, `ls /usr/bin`,
or similar commands. The canonical helper path below is the only supported live
GitHub access path.

On transient helper failures such as DNS resolution errors, connection resets,
or timeouts, retry the exact same helper command once. If the retry fails, give
the user the helper error and stop. Do not diagnose by inspecting token env vars,
`.env` files, proxy env vars, DNS tools, `curl`, `gh`, `git`, custom Python
requests, or alternate GitHub hosts.

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/github-readonly-live/scripts/github_readonly.py rate-limit
/usr/bin/python3 /sandbox/.hermes-data/skills/github-readonly-live/scripts/github_readonly.py get . --fields full_name,description,open_issues_count
/usr/bin/python3 /sandbox/.hermes-data/skills/github-readonly-live/scripts/github_readonly.py get issues --param state=open --limit 20 --exclude-pulls --fields number,title,state,html_url
/usr/bin/python3 /sandbox/.hermes-data/skills/github-readonly-live/scripts/github_readonly.py get issues/<number>/comments --paginate --fields user.login,created_at,body
/usr/bin/python3 /sandbox/.hermes-data/skills/github-readonly-live/scripts/github_readonly.py get pulls --param state=open --paginate --count
/usr/bin/python3 /sandbox/.hermes-data/skills/github-readonly-live/scripts/github_readonly.py get pulls/<number>/files --paginate --fields filename,status,changes
/usr/bin/python3 /sandbox/.hermes-data/skills/github-readonly-live/scripts/github_readonly.py get contents/<path>
```

Generic route rules:

- Use repo-relative REST routes only: `.`, `issues`, `issues/<number>`,
  `issues/<number>/comments`, `pulls`, `pulls/<number>`,
  `pulls/<number>/files`, `commits`, `branches`, `contents/<path>`, etc.
- Put query strings in `--param KEY=VALUE`, not in the route.
- Use `--paginate --count` for exact counts. Use `--limit` only when the user
  asks for a sample or "latest N" items.
- Use `--fields` to keep output small instead of piping to `python -c`, `jq`,
  or custom scripts.
- Use `--exclude-pulls` on the `issues` route when the user asks for issues
  rather than PRs, because GitHub's issues endpoint includes pull requests.

Compatibility aliases such as `issues`, `issue-counts`, `pulls`,
`pull-counts`, and `contents` are available, but the generic `get` command is
the default pattern for new GitHub questions.

## Pitfalls

- For "how many issues" questions, use generic count:
  `get issues --param state=all --paginate --count --exclude-pulls`. Do not use
  GitHub search endpoints; they are outside policy by design.
- For "how many PRs" or "how many pull requests" questions, use generic count:
  `get pulls --param state=open --paginate --count` or the requested state. Do
  not estimate from a single page.
- The live GitHub scope and the source ETL mirror scope can be different repos.
  Do not merge their results without naming which source each fact came from.
- If the helper is rate-limited, report that GitHub auth was absent or
  exhausted; use `source-etl-query` only when the user's task can tolerate
  mirrored data.
- The helper filters pull requests out of the `issues` command. Use `pulls` or
  `pull-counts` when the user specifically asks for PRs.
