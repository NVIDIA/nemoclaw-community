---
name: gitlab-readonly-live
description: Read one of the configured GitLab projects through authenticated, policy-scoped REST GET requests.
---

# gitlab-readonly-live

Use this skill for current live data from the GitLab projects listed in
`$GITLAB_READONLY_PROJECTS`.

## Access model

- The allowlist may contain multiple comma-separated projects.
- If there is one project, the helper selects it automatically. With multiple
  projects, pass `--project group/project` explicitly.
- Requests use the OpenShell provider placeholder from `GITLAB_TOKEN`. Never
  print or inspect that variable or any `.env` file.
- Access is limited to GET requests for project metadata, issues, merge
  requests, repository content and history, labels, milestones, and releases.
- Membership, CI/CD variables, hooks, deploy tokens, runners, and every write
  method are outside policy.
- Do not use `glab`, `git`, alternate GitLab hosts, GraphQL, or custom requests.

## Procedure

Always invoke the bundled helper:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/gitlab-readonly-live/scripts/gitlab_readonly.py identity
/usr/bin/python3 /sandbox/.hermes-data/skills/gitlab-readonly-live/scripts/gitlab_readonly.py get . --fields path_with_namespace,description,visibility
/usr/bin/python3 /sandbox/.hermes-data/skills/gitlab-readonly-live/scripts/gitlab_readonly.py get issues --param state=opened --paginate --count
/usr/bin/python3 /sandbox/.hermes-data/skills/gitlab-readonly-live/scripts/gitlab_readonly.py get merge_requests --param state=opened --paginate --fields iid,title,state,web_url
/usr/bin/python3 /sandbox/.hermes-data/skills/gitlab-readonly-live/scripts/gitlab_readonly.py get repository/tree --param recursive=true --paginate --limit 50 --fields name,path,type
```

Add `--project group/project` to any `get` command when more than one project is
configured. Put query parameters in `--param KEY=VALUE`, not in the route. Use
`%2F` for slashes inside a repository file-path segment, for example
`repository/files/docs%2Fguide.md`.

If OpenShell returns a policy 403, report the configured project and route
scope. Do not retry through a different host, binary, or endpoint.
