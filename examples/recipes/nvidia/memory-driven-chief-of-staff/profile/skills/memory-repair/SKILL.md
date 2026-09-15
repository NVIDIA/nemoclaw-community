---
name: memory-repair
description: Check the memory against its schema and fix what can be fixed, so the store degrades visibly rather than silently.
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

1. **Index against filesystem.** Every page has an index entry, every entry
   points at a page that exists, and each entry sits under the `## Section`
   for its own page type. Resolve a mismatch in the direction that loses
   nothing: for `unindexed`, add the missing entry; for `index-dangling`,
   remove an entry only when its target is genuinely gone; for
   `index-misfiled`, **move** the existing line into its own type's section
   rather than adding a second entry — the page already has one, it is just
   filed under the wrong heading. For `index-unparseable`, preserve the index,
   report the ambiguity, and make no index edits: the checker deliberately
   withholds derived findings when it cannot prove which content is top-level.
2. **Index sections.** `index-section-missing` means a validated page type
   has no `## Section` to be filed under, so the first page of that type
   would be reported unindexed with no entry that could clear it. Add the
   heading in the position `schema.md` fixes — immediately before whichever
   required section, already present, comes next in that order. Then reconcile
   every page of that type in the same pass: move each existing entry named by
   `index-misfiled`, and add an entry for each page named by `unindexed`. Do
   not leave the section empty: this finding is emitted only because at least
   one page of the type already exists. This is what reaches a memory installed
   before the type was added: the seed only supplies a fresh install, and
   bootstrap never overwrites an index the user owns.
   `index-out-of-order` means a `## Section` heading exists but not where
   `schema.md` puts it relative to the others. Move the heading — and
   everything filed under it — to its correct position; do not add a second
   heading for the same section.
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
