---
type: schema
version: 1
updated: 2026-08-18
---

# Memory Schema

The contract for the agent's memory of one person. Every page under
`workspace/memory/` is written against this file, and the repair job checks
pages against it. A page that violates a rule here is a defect the repair job
is expected to fix, not a variation to tolerate.

Read this file before writing any memory page.

## Why the structure exists

An append-only note store needs no schema, and gets none of these properties:

- **The repair job has something to check.** Index drift, broken links, a
  missing provenance footnote and an oversized section are all detectable only
  against a contract.
- **The ranking job has something to gate on.** The top priority tier is
  reserved for work the person has chosen, which is a question only
  `attention/` and `goals/` can answer. Without them, ranking can only measure
  how loudly the outside world is asking.
- **A claim can be traced.** Every non-obvious statement carries where it came
  from, so a wrong page can be corrected at its source rather than argued with.

## General rules

- Markdown with YAML frontmatter. No exceptions, including `index.md`.
- Filenames are `snake_case.md`. A person's page is named from their display
  name (`dana_okoro.md`), a project's from its slug (`billing_migration.md`).
- Links between pages are relative: `[Dana Okoro](../people/dana_okoro.md)`.
- Update `index.md` in the same pass that creates or deletes a page.
- Append to `log.md` after any write. The log is how the repair job explains
  itself later.
- Dates are `YYYY-MM-DD`. Timestamps that need a time use ISO-8601 UTC.

## What writes these pages

Not every page type has a writer yet, and the difference matters when reading
the rest of this file: a rule about a page nothing creates is a rule about a
page somebody would have to write by hand.

| Page type | Written by |
| --- | --- |
| `people/` | the memory-writing job |
| `attention/current_priorities.md` | the memory-writing job, from user corrections only |
| `attention/active_threads.md` | the memory-writing job |
| `attention/event_triggers.md` | nothing yet |
| `projects/` | nothing yet |
| `patterns/` | nothing yet |
| `concepts/` | nothing yet |
| `goals/` | nothing yet — deliberately, see below |
| `index.md`, `log.md` | seeded at bootstrap, maintained by every writer |

The repair job checks all of them regardless, because a page written by hand
is held to the same contract as one written by a job.

`goals/` is the one absence that is a decision rather than a gap. Together
with `attention/`, it gates the ranking job's top tier, so a goal inferred
from somebody's inbox promotes work they never chose — the same failure
`current_priorities.md` is careful to avoid. Goals come from the person.

## Page types

### People (`people/`)

```yaml
---
name: Full Name
identities:                        # every account this person writes from
  - email:person@example.com
  - slack:U01EXAMPLE
email: person@example.com          # optional
role: Job title or function
relationship: How they relate to the user, 1-2 sentences
importance: high | medium | low
last_interaction: YYYY-MM-DD
interaction_frequency: daily | weekly | monthly | rare
status: active | departing | departed   # optional, default active
---
```

**Sections, in order:** Relationship · Communication Style · Key Context ·
Projects (linked) · Recent Interactions.

**`identities` is what makes the page durable, and it is not the same field
as `email`.** `email` is contact information a reader might use; `identities`
is what the selector matches on, copied verbatim from what it hands over.
Without it a page is found only by its filename, so the day a second
`Sam Ruiz` appears the pages have to be renamed to tell them apart — and a
renamed page is a page whose history was lost. With it, whoever was there
first keeps their name and the newcomer gets a new one. Never edit an entry
to tidy it up: a value that no longer matches the store is the same as no
page.

**It is a list because a person is not one account.** Each entry is
`source:key` — the connector that collected it, then the identity that
connector gave. A colleague who writes from Slack and from mail has two
entries; a third connector adds a third, and nothing about the page's shape
changes. Split on the *first* colon only: a key may contain colons of its
own.

**Only the user adds an entry, and only through
`profile/scripts/link_identity.py`.** A matching display name is not
evidence — the reason the store keeps a stable identity at all is that
guessing from a name puts two people on one page. A matching handle is a
reason to *ask*, which the memory job does by reporting
`identity_candidates`; it is never a reason to write. Pages written before
the list existed carry a single `source_key:` and are read as a list of one;
they are not rewritten, because the page belongs to the user.

**Importance is about working proximity, not seniority.**

- `high` — direct collaborators, the person's manager, anyone they interact
  with daily or weekly, anyone whose silence would block a project.
- `medium` — regular but not constant contact; team members; stakeholders who
  need to be kept informed.
- `low` — occasional contact, mailing-list-only, peripheral.

**Recent Interactions** holds at most 30 bullets, newest first. Past 30, the
oldest are summarized into a `## Relationship Arc` section — a few sentences on
how the working relationship has changed — and dropped. The arc is written
once and revised, never appended to.

### Projects (`projects/<slug>/`)

Each project is a folder, because its history outgrows its description.

```
projects/<slug>/
├── <slug>.md        # the current picture
├── log.md           # append-only history
└── log.archive.md   # created when log.md rotates
```

```yaml
---
name: Project Name
aliases: [Codename]                # optional; only true alternate names
priority: high | medium | low
role: owner | contributor | team member | observer
updated: YYYY-MM-DD
---
```

**Sections, in order:**

1. `## Overview` — at most 5 sentences. What the project is and why it matters
   to this person. Stable across weeks. Never contains dated events.
2. `## Role` — what the person actually does here, 1-3 sentences.
3. `## Key People` — one bullet each, linked to `people/`, with a
   one-sentence relationship.
4. `## Resources` — links with a short description and a provenance footnote.
   The repair job flags entries whose `verified` date is over 90 days old; it
   does not go and re-check them itself.
5. `## Current State` — a snapshot, rewritten in full on every ingest pass,
   never appended to. Carries `**Health:** green | amber | red` with a
   one-line reason, then the open workstreams, blockers, pending decisions and
   next milestones.

**A project is active** when `updated` is within the last 30 days and Health is
not a closing state. The ranking job uses exactly this test, so an abandoned
project stops conferring priority on its own without anyone having to
remember to archive it.

`log.md` is append-only, newest entry last, one entry per line-group:

```markdown
## [2026-08-18] ingest | Vendor confirmed the migration window
- Slack #billing-migration: vendor proposed 2026-09-02, awaiting sign-off
^[source: slack, 2026-08-18, trust: high]
```

It rotates into `log.archive.md` at 1000 entries.

### Patterns (`patterns/`)

```yaml
---
type: patterns
updated: YYYY-MM-DD
decay: monthly | quarterly
---
```

How this person works, as opposed to what they work on. One file per pattern
family — `communication_style.md`, `work_habits.md`, `decision_making.md`.

Patterns are the pages most likely to drift into flattery. Every claim needs
either a provenance footnote pointing at observed behaviour, or an explicit
`(inferred)` marker. A pattern page with no footnotes and no markers is a
defect.

### Concepts (`concepts/`)

```yaml
---
type: concept
updated: YYYY-MM-DD
---
```

Domain vocabulary this person uses that a newcomer would not understand —
internal system names, team shorthand, recurring acronyms.

**Admission rule:** a term earns a page once it has appeared in at least two
distinct sources. A term seen once is noise; the ingest job leaves it alone.

### Goals (`goals/`)

```yaml
---
type: goals
timeframe: monthly | quarterly | long-term
updated: YYYY-MM-DD
decay: monthly | quarterly
---
```

Three pages: `monthly.md`, `quarterly.md`, `vision.md`. Each states objectives
with measurable targets and links the projects that serve them.

**Monthly goals outrank quarterly ones** for near-term priority, because they
are concrete enough to act on this week. `vision.md` never drives ranking on
its own; it is context for interpreting the other two.

### Attention (`attention/`)

```yaml
---
type: current_priorities | active_threads | event_triggers
updated: YYYY-MM-DD
decay: daily | weekly | monthly | quarterly
---
```

The short-lived layer: what this person is actually doing right now.

- **`current_priorities.md`** — what they have chosen to work on, in their own
  framing. This page is load-bearing: it is the primary signal the ranking job
  gates the top tier on. Use `decay: daily`.
- **`active_threads.md`** — conversations awaiting a reply or a decision.
  Use `decay: weekly`.
- **`event_triggers.md`** — "when X happens, do Y" reminders. An Active
  section for pending triggers, a Completed section for fired ones. Use
  `decay: weekly`; a long decay defeats the purpose. Nothing shipped writes
  or reads this page yet: it is a page type a person can keep by hand, and
  the schema defines it so that one written by hand is checkable. An earlier
  version of this file said ingest checks active triggers against every
  incoming message, which no shipped job does.

**Decay windows:** `daily` must be refreshed each day or it is stale.
`weekly` is good for ~7 days from `updated`, `monthly` ~30, `quarterly` ~90.
The repair job flags anything past its window rather than deleting it —
stale-and-labelled beats silently-wrong.

## Cross-reference rules

- A person mentioned on a project page links to their `people/` page. If the
  page does not exist yet, create a stub with `importance: low` rather than
  leaving a bare name.
- A project mentioned on a person's page links back to the project folder.
- Links are relative and must resolve. The repair job treats a broken link as
  a defect and fixes it by creating the missing stub or removing the
  reference, then records which it chose in `log.md`.
- No page links to itself, and no two pages describe the same entity. Merging
  duplicates is a repair-job responsibility; it requires strong identity
  evidence, not a name match.

## Provenance

Every claim that is not self-evident carries a footnote:

```markdown
Prefers async review over meetings.^[source: slack, 2026-08-11, trust: high]
```

- `source` — which system it came from.
- date — when the evidence is from, not when the page was written.
- `trust: high` — stated directly by the person. `medium` — inferred from
  repeated behaviour. `low` — a single ambiguous signal.

**An inference must never be promoted to a sourced fact.** If a page says
something the evidence does not, that is the most damaging defect in this
schema, because everything downstream reads these pages as ground truth.

## Index rules

`index.md` is the entry point. Any read of the memory starts here and then
opens only the pages the index names.

```yaml
---
type: index
updated: YYYY-MM-DD
---
```

Sections, in this order: `## People` · `## Projects` · `## Patterns` ·
`## Goals` · `## Attention`. One line per page: a relative link, then a
half-line of what it holds and why someone would open it.

An index entry pointing at a missing page, or a page with no index entry, is a
defect. The repair job resolves it in the direction that loses no information:
create the entry, not delete the page.

## Growth control

Every page has a soft ceiling. Past it, the consolidation job compacts rather
than truncates: dated events move to the project log, superseded state is
dropped, and unresolved commitments are always preserved.

| Page | Ceiling |
| --- | --- |
| `people/*.md` Recent Interactions | 30 bullets, then Relationship Arc |
| `projects/*/` Current State subsections | 8 workstreams, 5 blockers, 5 pending decisions, 12 user actions, 7 milestones |
| `projects/*/log.md` | 1000 entries, then rotate |
| `attention/*.md` | one screen |

Compaction never deletes an unresolved commitment or a provenance footnote on
a claim that survives.

## Log

`log.md` at the memory root records what the jobs did, newest last:

```markdown
## [2026-08-18T09:14:00Z] repair
- created stub people/sam_ruiz.md for a link on projects/billing_migration
- flagged attention/current_priorities.md stale (updated 2026-08-11, decay
daily)
```

One entry per job run, even when nothing changed — a run that found nothing
is itself the useful signal that the memory is healthy.
