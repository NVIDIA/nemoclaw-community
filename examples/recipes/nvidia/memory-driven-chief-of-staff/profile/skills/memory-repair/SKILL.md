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

Read `$HERMES_HOME/schema.md` first. It is the contract; everything below
is how to enforce it.

## Start with the mechanical pass

Run the deterministic checker first and work from its output:

```bash
python3 "$HERMES_HOME/scripts/memory_check.py"
```

It returns JSON: every finding with a kind, a path, and a detail, plus a
`clean` flag. It never writes. Deciding what to do about each finding is your
job; detecting them is not, and a check you perform by reading is a check that
drifts.

## What the findings mean, in this order

Cheap and mechanical first, so a run that is going to find nothing finds it
quickly.

1. **Index against filesystem.** Every page has an index entry and every entry
   points at a page that exists. Resolve a mismatch in the direction that
   loses nothing: add the missing entry rather than delete the page, and
   remove an entry only when its target is genuinely gone.
2. **Index sections.** `index-section-missing` means a validated page type
   has no `## Section` to be filed under, so the first page of that type
   would be reported unindexed with no entry that could clear it. Add the
   heading in the order `schema.md` fixes, and add nothing else — an empty
   section is the correct state until a page of that type exists. This is
   what reaches a memory installed before the type was added: the seed only
   supplies a fresh install, and bootstrap never overwrites an index the
   user owns.
3. **Links resolve.** Every relative link between pages lands somewhere. A
   broken link to a person becomes a stub page with `importance: low`; a
   broken link to anything else is removed and noted. Record which you chose.
4. **Frontmatter completeness.** Every page carries the keys its type
   requires. A missing `updated` is filled from the newest dated content on
   the page, never from today — today would assert a freshness the page has
   not earned.
5. **Person identity.** Every people page carries a `source_key`, and no two
   carry the same one. **Never derive one from the page.** For
   `missing-identity`, take the value from the memory job's `source_key` for
   that person and write it in; if the selector does not name them, leave the
   field absent and note it — a page found by the wrong identity is worse than
   one found only by its filename. For `duplicate-identity`, do not merge and
   do not pick. Two pages claiming one identity means either that one of them
   is about somebody else, or that a merge copied the content across and left
   the emptied page behind — and nothing on disk tells those apart, because
   the page that looks redundant is the correct one in the second case and
   the victim in the first. The memory job knows: it reports the pages a
   confirmed link has joined, under `merge_into_slug`. Leave this to that
   job.
6. **Decay windows.** Any page past its `decay` window is flagged as stale in
   the log. **Do not delete it and do not silently refresh the date.** A page
   marked stale is still useful; a page whose date was quietly bumped is a
   lie.
7. **Provenance.** Claims on `patterns/` pages carry a footnote or an
   `(inferred)` marker. A page with neither is flagged. Never invent a
   footnote to satisfy the check — an unsupported claim should be visible, not
   dressed up.
8. **Section ceilings.** Pages past the limits in the schema's growth-control
   table are reported for the consolidation job. Repair does not compact;
   those are different jobs on purpose, because compaction needs judgment and
   repair should be safe enough to run unattended.

## What repair must never do

- Promote an inference to a sourced fact.
- Delete an unresolved commitment.
- Merge two pages on a name match alone. Identity needs evidence; a shared
  first name is not evidence, and neither is a shared full name.
- Invent a `source_key`, or copy one from another page to clear a finding.
- Rewrite a page wholesale when a bounded fix would do.

## Log

Append one entry to `$HERMES_HOME/workspace/memory/log.md` every run, including runs that
changed nothing:

```markdown
## [2026-08-18T09:14:00Z] repair
- created stub people/sam_ruiz.md for a link on projects/billing_migration
- flagged attention/current_priorities.md stale (updated 2026-08-11, decay daily)
- 2 pages over their section ceiling, reported for consolidation
```

A clean run is worth logging. It is the difference between "the memory is
healthy" and "nothing checked it".
