---
name: source-etl-query
description: Query the host-side source-etls REST mirror for GitHub and NVIDIA forums research.
---

# source-etl-query

Use this skill to query the host-side REST bridge served by `source-etls`.

## When to use

- Inspect mirrored GitHub issues
- Inspect mirrored pull requests
- Inspect mirrored GitHub discussions
- Inspect mirrored NVIDIA forum topics

## Access model

- Use the helper script in this skill.
- Do not hand-write REST queries unless the user explicitly asks for them.
- The sandbox should treat this bridge as the default source for mirrored GitHub
  and forum data in the NVIDIA setup path.

## Required Environment

- `SOURCE_ETL_API_URL`, or
- `SOURCE_ETL_API_HOST` plus `SOURCE_ETL_API_PORT`

## Procedure

Always run these commands via the terminal tool — do not invoke `source-etl-query`
as a named skill tool.

### 1. Query the mirrored source through the REST bridge

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py github-issues --limit 20
/usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py github-prs --limit 20
/usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py github-discussions --limit 20
/usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py forum-topics --limit 20
```

### 2. Narrow the result set when needed

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py github-issues --search <keyword> --limit 10
/usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py forum-topics --search <keyword> --limit 10
```

### 3. Interpret the results and handle empty or mismatched data

The ETL is configured to mirror a specific GitHub repo and forum tag — these
are set by whoever deployed this sandbox, and may differ from what the user
is asking about.

**If the query returns zero rows:**
- The database may be empty because the ETL has not completed its first sync
  yet (it runs on an interval, typically hourly). Tell the user: "The mirror
  appears empty — the ETL may not have completed its first sync yet. Try again
  in a few minutes."
- Alternatively the ETL target repo or forum tag may not match what the user
  is asking about (see below).

**If results exist but are not relevant to the user's question:**
- Run a broad unfiltered query first to show what IS in the database:
  ```bash
  /usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py github-issues --limit 5
  /usr/bin/python3 /sandbox/.hermes-data/skills/source-etl-query/scripts/query_source_etl.py forum-topics --limit 5
  ```
- Then tell the user what repo/topics the mirror actually contains, e.g.:
  "The ETL mirror contains issues from `NVIDIA/NemoClaw` and forum topics
  tagged `nemoclaw`. If you need data from a different repo or topic, the
  ETL target would need to be reconfigured."

**Do not fall back to live GitHub or forum requests** — the sandbox has no
egress to those hosts.

## Pitfalls

- The mirror is refreshed hourly, so it is not guaranteed to match the live
  source instantly.
- The ETL scope is configured per-deployment — forum topics follow the
  configured tag, and GitHub issues follow the configured repo. Neither covers
  the whole of GitHub or the entire forums site.
