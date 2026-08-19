---
name: memory-repair
description: Check the memory against its schema and fix what can be fixed, so the store degrades visibly rather than silently.
version: 0.1.0
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [memory, maintenance]
---

# Repairing the memory

An append-only note store cannot be checked, because there is nothing to check
it against. This memory has a schema, so it can be — and this is the job that
does it.

Read `workspace/memory/schema.md` first. It is the contract; everything below
is how to enforce it.

## What to check, in this order

Cheap and mechanical first, so a run that is going to find nothing finds it
quickly.

1. **Index against filesystem.** Every page has an index entry and every entry
   points at a page that exists. Resolve a mismatch in the direction that
   loses nothing: add the missing entry rather than delete the page, and
   remove an entry only when its target is genuinely gone.
2. **Links resolve.** Every relative link between pages lands somewhere. A
   broken link to a person becomes a stub page with `importance: low`; a
   broken link to anything else is removed and noted. Record which you chose.
3. **Frontmatter completeness.** Every page carries the keys its type
   requires. A missing `updated` is filled from the newest dated content on
   the page, never from today — today would assert a freshness the page has
   not earned.
4. **Decay windows.** Any page past its `decay` window is flagged as stale in
   the log. **Do not delete it and do not silently refresh the date.** A page
   marked stale is still useful; a page whose date was quietly bumped is a
   lie.
5. **Provenance.** Claims on `patterns/` pages carry a footnote or an
   `(inferred)` marker. A page with neither is flagged. Never invent a
   footnote to satisfy the check — an unsupported claim should be visible, not
   dressed up.
6. **Section ceilings.** Pages past the limits in the schema's growth-control
   table are reported for the consolidation job. Repair does not compact;
   those are different jobs on purpose, because compaction needs judgment and
   repair should be safe enough to run unattended.

## What repair must never do

- Promote an inference to a sourced fact.
- Delete an unresolved commitment.
- Merge two pages on a name match alone. Identity needs evidence; a shared
  first name is not evidence.
- Rewrite a page wholesale when a bounded fix would do.

## Log

Append one entry to `workspace/memory/log.md` every run, including runs that
changed nothing:

```markdown
## [2026-08-18T09:14:00Z] repair
- created stub people/sam_ruiz.md for a link on projects/billing_migration
- flagged attention/current_priorities.md stale (updated 2026-08-11, decay daily)
- 2 pages over their section ceiling, reported for consolidation
```

A clean run is worth logging. It is the difference between "the memory is
healthy" and "nothing checked it".
