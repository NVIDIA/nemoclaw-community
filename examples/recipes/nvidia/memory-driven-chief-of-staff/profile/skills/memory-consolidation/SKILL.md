---
name: memory-consolidation
description: Keep the memory inside its size limits by compacting rather than truncating, so it stays readable as it ages.
version: 0.2.0
memory-operation-protocol: 1
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [memory, maintenance]
---

## Coordinated memory transport

All reads of `workspace/memory` use
`python3 $HERMES_HOME/scripts/memory_operations.py read <relative-path> ...`.
This returns the store instance, exact file hashes, and a coherent snapshot.
If it reports a pending or blocked operation, stop this pass and surface the
diagnostic. Do not read partial files as current memory.

All memory file changes, including shared index entries and the single log
entry, go through `python3 $HERMES_HOME/scripts/apply_memory.py < proposal.json`.
Never write, append, rename, or delete memory files with shell or file tools.
Prepare complete people/attention pages and their evidence markers together
in a `legacy_write` proposal with the returned `expected_hash` for every file.
Use `null` text for a reviewed people merge source deletion and include its
index removal in the same operation. Preserve the content and admission rules
below. A failed proposal acknowledges no new evidence batch.

Managed projects, patterns, and concepts use `update` with declared field
changes; never send a managed page through the whole-file adapter. Existing
unmanaged pages may be repaired with their exact full-file precondition and
remain unmanaged. Use `repair_index` for verified missing or stale entries,
and `log_only` for a pass that changes only the shared memory log. The writer
constructs index patches and a log entry containing its operation ID.
Before building a proposal, read `$HERMES_HOME/scripts/memory-protocol.md`
for the installed JSON contract and examples.

A conflict preserves the live file. Report it and defer that target. Generate
a fresh independent proposal for unrelated work; do not retry a changed
request under an already used request ID, adopt a page implicitly, clear
review flags, or use a direct write as a fallback. Per-page user approval is
not required for generated content after Foundation enablement. Handwritten
content requires an explicit scoped user action through `correct.py`.

# Consolidating the memory

Memory that only grows stops being read, and a memory nobody reads is worse
than none — it looks like the system knows things it can no longer surface.
This job keeps pages inside the ceilings in `$HERMES_HOME/schema.md`.

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
