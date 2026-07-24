---
name: "watchtower"
description: "Run a scheduled web-surveillance sweep over a watchlist of topics using Tavily web_search, optional Tavily extraction, deterministic dedup/exclusion filtering, and a cited Markdown digest. Use when the user asks to run a sweep, run a watchtower sweep, monitor the watchlist, check the watchlist, or asks what changed since the last run. Trigger keywords - run a sweep, watchtower sweep, monitor watchlist, what changed."
license: "Apache-2.0"
---

# watchtower

Sweep every topic in the active watchlist for genuinely new items, judge their
relevance and significance, and write a cited digest plus a structured
changelog.

## Design principle

**Scripts enforce mechanics; the agent makes editorial judgments.** You choose
search queries, assess source credibility, and judge relevance/significance.
The scripts only decide mechanical questions: is this URL already seen, is the
topic known, or is the host explicitly excluded? Never re-implement dedup or
exclude filtering with your own judgment: always pipe candidates through
`diff_state.py`, and always advance state through `commit_state.py`.

Hard rules:

- Never fabricate URLs. Cite only URLs returned by `web_search` or fetched with
  `tavily_extract` from a surviving `web_search` URL in this run.
- Optional `seed_sources` are search hints, not a hard allowlist. Interesting
  off-source results may be included when they are credible and relevant.
- Optional `exclude_domains` are a hard negative filter. Do not resurrect items
  dropped by `diff_state.py`.
- If you need page text beyond the `web_search` snippet, fetch only surviving
  URLs with `tavily_extract`. Never fetch result URLs with `web_fetch`, browser
  tools, `curl`, or custom HTTP scripts.
- Never advance state before both output files are written.

## Workspace root

Treat `/sandbox/.openclaw/workspace` as the run root. Resolve the supplied
watchlist path relative to that directory, and write `state/` and `outputs/`
directly beneath it. Do not create a nested `workspace/watchtower/` directory.
Because each `exec` call starts a new shell, use absolute paths or prefix each
relative-path command with `cd /sandbox/.openclaw/workspace &&`.

## Run identity

Set a run id at the start of the sweep: UTC date plus a short random suffix,
e.g. `2026-07-06-k3f9`. Use it in both output filenames and in every item
committed to state.

## Procedure

In the commands below, replace `<watchlist_path>` with the watchlist path
supplied in the sweep request.

### 1. Validate the active watchlist

```bash
cd /sandbox/.openclaw/workspace && \
  python3 ~/.openclaw/skills/watchtower/scripts/validate_watchlist.py "<watchlist_path>"
```

If validation fails, stop and report the error. Do not sweep an invalid
watchlist.

### 2. Search each topic broadly

For each topic, run 1-2 `web_search` queries built from the topic's `query`.
Use optional fields as hints:

- `lookback_days`: bias the query toward recent results, e.g. "past 30 days" or
  an equivalent time phrase.
- `seed_sources`: run one source-biased query with `site:` operators when useful,
  but also allow a broader query so the sweep can find coverage elsewhere.
- `exclude_domains`: do not manually apply these during search; `diff_state.py`
  enforces them in step 3.

Example query pair:

```text
new sanctions designation specially designated nationals list update past 14 days
new sanctions designation specially designated nationals list update site:ofac.treasury.gov
```

### 3. Collect candidates and filter deterministically

Collect every result as a JSON line with fields `topic_id`, `url`, `title`, and
any useful search-provided fields such as `snippet` or `content`; then pipe the
batch through `diff_state.py`:

```bash
cd /sandbox/.openclaw/workspace && \
  <candidates.jsonl python3 ~/.openclaw/skills/watchtower/scripts/diff_state.py \
  --watchlist "<watchlist_path>" \
  --state state/seen.json >survivors.jsonl
```

Only items that are unseen, belong to a known topic, and do not match that
topic's `exclude_domains` survive. Everything dropped here is dropped for a
mechanical reason — do not resurrect filtered items.

### 4. Extract and judge survivors only

For each surviving item, judge relevance, source credibility, and significance
against the topic's `why_it_matters`. Use the title and snippet/content returned
by `web_search`; when you need fuller page text, call `tavily_extract` on the
surviving URL. Do not extract anything that did not survive `diff_state.py`.
Assign `high`, `medium`, or `low`.

If an item is real but noise (a minor patch note, a duplicate announcement of
something already digested under another URL, an incidental page match), log it
as skipped with a one-line reason instead of digesting it. When in doubt,
include it as `low` rather than omitting it silently.

### 5. Write the digest and changelog

Write both files before touching state:

- `outputs/digest-<run-id>.md` — per topic: what changed, why it matters
  (grounded in the topic's `why_it_matters`), source/credibility notes, and
  source links. If no topic produced anything new, write a short "no changes"
  digest saying which topics were swept.
- `outputs/changelog-<run-id>.json` — a JSON array of
  `{topic_id, url, title, significance, summary}` for every digested item
  (empty array when nothing changed).

### 6. Commit state — only after both outputs exist

Pipe the digested items (now including `run_id`) to `commit_state.py`:

```bash
cd /sandbox/.openclaw/workspace && \
  <confirmed.jsonl python3 ~/.openclaw/skills/watchtower/scripts/commit_state.py --state state/seen.json
```

This ordering is the crash-safety contract: if the run dies before step 6,
state has not advanced and the next sweep re-processes the same candidates
instead of losing them. A re-processed item is cheap; a silently lost item is
not.

## Completion gate

Do not paste the digest body into the final chat response. A chat-only digest is
a failed sweep. Before replying, verify that the current run's digest and
changelog are non-empty files under `/sandbox/.openclaw/workspace/outputs/` and
that `/sandbox/.openclaw/workspace/state/seen.json` exists after the commit.
If any check fails, continue working until all three artifacts pass. The final
response should only summarize the run id, counts, and verified artifact paths.
