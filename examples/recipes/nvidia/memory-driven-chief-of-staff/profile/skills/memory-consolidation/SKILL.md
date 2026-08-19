---
name: memory-consolidation
description: Keep the memory inside its size limits by compacting rather than truncating, so it stays readable as it ages.
version: 0.1.0
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [memory, maintenance]
---

# Consolidating the memory

Memory that only grows stops being read, and a memory nobody reads is worse
than none — it looks like the system knows things it can no longer surface.
This job keeps pages inside the ceilings in `$HERMES_HOME/workspace/memory/schema.md`.

Read the schema's growth-control table first. Work only on pages the repair
job reported as over their ceiling, or that you can see are over.

## Compact, do not truncate

The distinction is the whole job.

- **Dated events move**, they do not vanish. A project's dated bullets belong
  in that project's `log.md`; the main page keeps the current picture.
- **Superseded state is dropped.** "Waiting on the vendor to reply" is dead
  once the vendor replied. That is not information loss, it is the page
  catching up.
- **A person's Recent Interactions past 30 items** become a `Relationship
  Arc`: a few sentences on how the working relationship changed. Write it
  once, revise it later, never append to it.
- **Patterns decay.** A behaviour last observed months ago and never since is
  weakened or dropped, not restated with confidence it no longer has.

## What must survive

- **Unresolved commitments.** Anything the user owes someone, or is owed,
  survives compaction regardless of age. Age is not resolution.
- **Provenance on every claim that survives.** If you keep the claim, keep its
  footnote. A compacted page full of unsourced assertions is worse than the
  long one it replaced.
- **Project history.** Moved to `log.md`, never deleted. Rotate the log at its
  limit rather than trimming it.

## Bounded work

Compact the pages that are over, and stop. Rewriting the whole memory because
two pages were long is how a maintenance job turns into an outage — and every
rewrite is an opportunity to lose a footnote.

If a page needs judgment you cannot make safely — two entries that might be
the same project, a commitment you cannot tell is resolved — leave it and say
so in the log. An honest deferral is a good outcome.

## Log

```markdown
## [2026-08-18T09:31:00Z] consolidation
- projects/billing_migration: moved 14 dated bullets to log.md, page now 4 sections
- people/dana_okoro: Recent Interactions 41 -> 30, wrote Relationship Arc
- deferred: two entries under concepts/ may be the same term, evidence unclear
```
