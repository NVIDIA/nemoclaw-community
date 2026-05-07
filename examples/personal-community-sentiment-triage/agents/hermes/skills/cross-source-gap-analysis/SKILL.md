---
name: cross-source-gap-analysis
description: Compare findings across Slack, GitHub, NVIDIA forums, and Outlook to identify alignment gaps, missing coverage, and follow-ups.
---

# cross-source-gap-analysis

Use this skill when the task is to compare or synthesize information across
multiple sources rather than merely access one source.

## When to use

- Compare Slack discussion against GitHub issues or PRs
- Compare Slack or GitHub findings against NVIDIA forum discussion
- Identify missing coverage, inconsistent narratives, or follow-up areas across sources
- Find external email discussions not reflected in internal meeting updates

## Inputs

Load the source skills you need first:

- `slack-channel-summarizer`
- `slack-channel-finder`
- `source-etl-query`
- `outlook-email-search`

This skill does not define how to access those systems. It defines how to
combine the findings once you have them.

## Procedure

### 1. Gather the minimum useful evidence from each source

Prefer a small, relevant slice from each source over broad collection. For example:

- a recent Slack window for the relevant channel
- mirrored GitHub issues, PRs, or discussions for the repo or feature area
- mirrored NVIDIA forum topics for the `nemoclaw` tag scope
- recent emails filtered to the relevant project and date range

**For Outlook**: Use `--external-only --since Xd` to scope to external-sender
emails, then `get_thread.py` to read the full conversation for any thread that
looks relevant. The "Comparing external emails to internal meeting topics" section
in the `outlook-email-search` skill has the step-by-step procedure for the common
"what are external devs discussing that we haven't covered?" pattern.

### 2. Normalize what each source is saying

Reduce each source to short bullets such as:

- active topics
- reported problems
- decisions or planned work
- requests for help
- unresolved questions

### 3. Compare across sources

Look for:

- topics active in one source but absent in another
- issues discussed informally in Slack but not tracked in GitHub
- GitHub work that appears to have little or no discussion in Slack
- repeated mirrored forum concerns that are not reflected in Slack or GitHub
- external email threads covering topics not mentioned in internal update emails
- conflicting descriptions of status, priority, or ownership

### 4. Present the result

A good default structure is:

- scope and time window
- what all sources agree on
- gaps or mismatches
- concrete follow-ups

Keep the comparison grounded in evidence from the sources you actually checked.
Do not invent gaps just because one source had less data available.

## Pitfalls

- Do not force a gap-analysis framing when the user only asked for source access
  or a plain summary.
- Do not over-collect. A narrow comparison is usually better than an exhaustive scrape.
- Distinguish between "not discussed" and "not observed in the sampled data".
- Distinguish between “not observed in the mirror” and “not present on the live source”.
