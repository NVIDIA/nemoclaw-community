<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Recoverable memory writes

Foundation coordinates the recipe's Markdown pages, shared index, memory log,
and SQLite page registry. It adds no entity extractor, page-generation job,
project-status command, or feedback-learning pipeline. Future writers can use
its generated-field API; the existing scheduled writer still covers people
and attention only.

After enablement, new generated content needs no page-by-page approval.
Existing handwritten content remains outside automatic ownership. A user can
explicitly adopt selected fields and review their observed contents. A file
collision or unexplained edit defers the proposed change without rewriting
the live file or treating it as user feedback.

## Install and enable

Stop the profile gateway before updating its runtime and resynchronizing jobs.
Run the recipe installer and `scripts/register-jobs.sh` through the existing
Linux installation procedure. Registration updates jobs by name. It adds one
deterministic memory-maintenance job and adds a recovery pre-step to existing
repair, consolidation, and preference jobs. It adds no generator job.

Make an export with the new runtime before enabling managed generation:

```bash
python3 "$HERMES_HOME/scripts/export_store.py" --to /path/to/backup
python3 "$HERMES_HOME/scripts/memory_operations.py" enable
```

Enablement verifies protocol 1 in all four effective memory-writing skills
and checks their Phase B override state. An incompatible customization is
reported and preserved. Review and rebase that customization through the
existing override workflow before retrying. Jobs check compatibility again
before writes; adding an incompatible override later blocks publication.

Schema 7 adds nine tables and a stable store-instance UUID to the recipe's
`workspace/ledger/state.db`. It does not modify Hermes's own `state.db` at the
profile root. Migration preserves existing rows and leaves Markdown untouched.
It does not register existing pages. Repeated initialization preserves the
UUID, and runtimes refuse stores with a newer schema version.

## Read before proposing a change

```bash
python3 "$HERMES_HOME/scripts/memory_operations.py" check
python3 "$HERMES_HOME/scripts/memory_operations.py" read \
  index.md concepts/example.md
```

`check` is observational; it does not initialize, migrate, recover, or expire
the store. `memory_check.py` also reports journal status without replaying it.
`read` holds a short shared lock and returns `store_instance_id`, file text,
exact `expected_hash` values, and page IDs/states/revisions. An absent file has
both `text` and `expected_hash` set to `null`. A pending operation blocks
current-memory reads until recovery or explicit resolution.

Use one `read` invocation for all files needed in a snapshot. Release the lock
before inference. A later proposal must still pass its expected hashes.
Retired pages remain readable as history but are excluded from active work.
Aliases continue to reserve old names after rename.

## Agent proposal format

Write a UTF-8 JSON file, then submit it:

```bash
python3 "$HERMES_HOME/scripts/apply_memory.py" < proposal.json
```

Every proposal has `version: 1`, the current `store_instance_id`, a unique
`request_id` of at most 128 characters, and an `action`. The same request ID
and digest return the existing result; a different digest is rejected.
Optional `evidence_refs` contains at most 128 `item:<source_id>` or
`event:<id>` references verified against this store. Receipts keep reference
digests without copying source message text. Neither model JSON nor the CLI
accepts an actor, ownership origin, review receipt, completion handler, or SQL
statement.

### Generate a page

```json
{
  "version": 1,
  "store_instance_id": "UUID returned by read",
  "request_id": "generate-example-1",
  "action": "create",
  "changes": [{
    "path": "concepts/example.md",
    "text": "---\nname: Example\n---\n\n## Definition\nAn evidence-backed definition.\n",
    "fields": ["frontmatter:name", "section:Definition"]
  }]
}
```

Only projects, patterns, and concepts enter the registry. Projects use
`projects/<slug>/<slug>.md`; patterns and concepts use `<type>/<slug>.md`.
Generated names use lowercase snake_case. The destination must be absent and
unreserved, including case-folded collisions. The planner creates a stable
page ID, generated ownership receipts, an index entry, and an operation log
entry. Ownership becomes usable only after the entire operation completes.

The current memory-writing skill does not acquire a new admission rule from
this API. Project and other generators remain separate future work.

### Refresh fields

```json
{
  "version": 1,
  "store_instance_id": "UUID returned by read",
  "request_id": "refresh-example-2",
  "action": "update",
  "changes": [{
    "page_id": "registered page UUID",
    "expected_hash": "SHA-256 returned by read",
    "fields": {
      "section:Definition": "## Definition\nThe revised definition.\n"
    }
  }]
}
```

Field identifiers are `frontmatter:<key>`, `section:<exact-heading>`, and
`entry:<opaque-id>`. Replacement text includes the complete field span,
including its key or heading and terminating newline. Bytes outside selected
spans are preserved. Missing fields on registered pages can receive generated
ownership automatically; an existing unmanaged field cannot.

Generated descriptive fields use compare-and-swap protection: their live hash
must match the recorded baseline. Immutable `frontmatter:id` and
`frontmatter:page_id` fields use `write_once`. Stable entries use `additive`:
an existing entry ID can repeat the same bytes but cannot change contents.

```markdown
<!-- mdcos:entry:example_1 -->
A dated, sourced observation.
<!-- /mdcos:entry:example_1 -->
```

Do not overlap ownership scopes, such as owning both a section and an entry
inside it. Duplicate headings or keys, nested YAML mappings, setext headings,
ambiguous boundaries, and malformed/nested entry markers are rejected.
The managed parser supports flat frontmatter and indented scalar/list
continuations; it does not reserialize arbitrary YAML. Existing people pages
use the full-file adapter and retain their existing schema.

### Existing writers and shared files

`legacy_write` accepts `changes` with `path`, `expected_hash`, and complete
`text`. A null `text` removes a source page in an explicitly authorized people
merge. Creation and deletion receive corresponding index patches. Optional
`index` entries accept `path`, `mode` (`add` or `remove`), and an optional
label. The action must agree with that page's final presence.

People and attention retain their current admission, identity, priority, and
Phase C evidence rules. Evidence text and its acknowledgment marker must be
in the same complete page proposal. No receipt advances a batch independently
of the page. The adapter does not register these pages as managed fields.

Repair and consolidation may use the adapter on existing unmanaged projects,
patterns, and concepts, with `skill` set to the corresponding shipped skill.
They cannot create those pages or bypass a registered page or its sidecars.
Managed repair uses `update` and all normal ownership/review checks.

`repair_index` accepts verified `add`/`remove` index changes for present/absent
targets. Ambiguous entries and wrapped descriptions require an explicit
reviewed repair rather than guessed span edits. `log_only` accepts no page
changes. All operations receive one content-free log entry with their ID;
recovery cannot append a duplicate entry. Preference policy remains in its
existing store and uses this action for its shared memory-log effect.

### Project logs

A project create/update can include `sidecars.log.md` with `expected_hash`
and an `entries` object mapping stable IDs to entry text. The handler renders
the markers and only appends new entries. Existing unowned logs are refused.

A separate update can include `sidecars.rotate` with `log_hash`,
`archive_hash`, and an integer `entries` count. Rotation moves that exact
prefix of marked entries to `log.archive.md` and preserves its remaining
bytes. Archive publication and active-log removal have separate journal
steps. Rotation refuses unowned prefixes or duplicate archive IDs.
Only these declared project sidecars are supported in v1.

## Explicit user actions

The conversational entry point invokes these commands only for a scoped user
instruction. Factual feedback or a model proposal does not authorize takeover,
rename, merge, retirement, deletion, or conflict resolution.

```bash
python3 "$HERMES_HOME/scripts/correct.py" adopt-page --proposal action.json
python3 "$HERMES_HOME/scripts/correct.py" review-adoption --proposal action.json
python3 "$HERMES_HOME/scripts/correct.py" rename-page --proposal action.json
python3 "$HERMES_HOME/scripts/correct.py" merge-pages --proposal action.json
python3 "$HERMES_HOME/scripts/correct.py" retire-page --proposal action.json
python3 "$HERMES_HOME/scripts/correct.py" forget-page --proposal action.json
python3 "$HERMES_HOME/scripts/correct.py" resolve-memory-conflict --proposal action.json
```

Every action file includes `request_id` and `store_instance_id`.

| Command | Additional fields and effect |
| --- | --- |
| `adopt-page` | `path`, `expected_hash`, and `fields` mapping field identifiers to ownership policies. Capture existing spans without rewriting them. Optional project `sidecars` maps declared names to observed hashes. |
| `review-adoption` | `page_id`, whole-page `expected_hash`, and `fields` mapping selected identifiers to their original field hashes. Only those unchanged fields become eligible for automatic updates. |
| `rename-page` | `page_id`, `expected_hash`, `to`, and every declared sidecar path/hash. Keep the ID, update references, and reserve the old path. Case-only changes use recorded temporary-file stages. |
| `merge-pages` | Survivor `page_id`, `expected_hash`, `source_id`, `source_hash`, and reviewed survivor `fields`. Retire the source while keeping its full body and provenance. |
| `retire-page` | `page_id` and `expected_hash`. Freeze automatic changes and mark its index entry retired. |
| `forget-page` | `page_id`, `expected_hash`, and every declared sidecar path/hash. Remove files and references, scrub recovery prose, and retain opaque audit/tombstone records. |

Rename and forget inspect incoming links. Supply `backlinks` covering every
referring page, with `path`, `expected_hash`, and either managed `fields` or
explicitly reviewed unmanaged full `text`. The patch must remove the old
reference. Unmanaged links without a reviewed plan, ambiguous references,
unknown sidecars, and path collisions block preparation. A retired source
keeps its links during merge; name similarity alone grants no merge authority.

## Recovery and resolution

```bash
python3 "$HERMES_HOME/scripts/memory_operations.py" recover
python3 "$HERMES_HOME/scripts/maintain_memory.py"
```

Before the first file effect, one SQLite transaction records the complete
dependency-ordered plan, before/after presence, hashes, rendered bytes, and
registry effects. The limit is 32 file steps and 8 MiB of combined before/after
payload. Oversized operations fail before preparation.

Each file step compares its own live state. A before-image permits the frozen
write; an after-image acknowledges a write that already landed. Any other
state preserves the live file and blocks the operation. Publication uses
same-directory temporary files, fsync, atomic replacement, and parent-directory
fsync. Creation uses no-clobber publication. Readers remain gated while the
multi-file result is partial. This protocol coordinates cooperating writers;
it cannot make arbitrary external editors honor a lock.

`memory_operations.py inspect` returns the affected live files and their
hashes as an explicitly partial observation (`current_memory: false`). Use
that output to review a conflict; it is not a current-memory read.

`resolve-memory-conflict` adds `operation_id`, `choice`, and `observed`, a map
of every affected path to its current hash or null. Choices are:

- `retry`: current files must match retained before/after images. Record the
  reviewed choice and replay the frozen plan.
- `cancel`: permitted only before a persistent file effect. Clear replay
  payloads and retain an audit of the user decision.
- `replace`: also supply `replacement`, mapping every affected path to full
  reviewed text or null. Compensate the interrupted operation from actual
  files. Previously existing paths must be restored; new files may be retained
  as unmanaged content. Existing reviewed, mutable fields receive
  the explicitly chosen baseline; immutable fields and pending adoption reviews
  retain their restrictions. The planner reconciles affected index entries and
  records its own log marker. It does not apply an obsolete completion effect.
  Keep the old and replacement receipts.

No blocked operation is automatically superseded by newer evidence. Pending
adoption review affects only its selected fields and does not occupy the
global unfinished-operation slot.

## Completion extensions and lock order

Future extensions register versioned code handlers through
`memory_journal.register_completion`. Registration names required migrated
tables, a pure validator, a transactional apply callback, and optionally a
coordinated-reader guard. Unknown handlers or absent migrations block prepare
and recovery. The model-facing JSON format cannot register or invoke one.

After every final file image verifies, one short SQLite transaction applies
Foundation registry/audit effects, invokes completion handlers, marks the
operation complete, and scrubs replay bytes. A handler failure rolls the
entire transaction back. Physical after-images remain available for retry.
Callbacks must not commit, take locks, write files, or open connections.
Foundation introduces no feedback or entity tables. Future capture paths can
remain SQLite-only; the extension owns revision checks and obsolete-result
handling when captures arrive during publication.

The lock order is Phase B global/per-skill locks, then
`workspace/.memory-operations.lock`, then a short SQLite transaction. Memory
readers acquire their shared lock before SQLite transactions. Ranking remains
a pure function; it never acquires a lock inside an existing write transaction.
No lock spans a model call, network request, or user interaction. Export
captures Phase B state before acquiring the memory barrier and never reacquires
the Phase B locks from inside that barrier.

## Export, retention, disable, and reset

Export enumerates all nine Foundation tables. JSON represents active BLOB
payloads as `{"encoding":"base64","data":"..."}`; null remains null.
Database and memory files are captured while memory writers are excluded,
including partial operations and their status. This lets the user inspect or
export a blocked operation before choosing a resolution.

Completed, cancelled, and superseded operations retain hashes and scoped
receipts but clear replay bytes. Unfinished payloads expire after 30 days,
become `payload_expired` resolutions, and cannot be reconstructed from cleared
sources. Forget and reset clear relevant payloads immediately. Existing message
body-retention rules remain unchanged.

`memory_operations.py disable` stops automatic managed generation without
erasing state. The people/attention adapter, reader guards, recovery, and user
resolution remain available. Managed repair continues to honor ownership.
Disabling never restores direct file writes or downgrades the schema.

Before reset or uninstall, stop the profile gateway and other producers using
the existing shutdown procedure. Reset restores Phase B customizations first,
then takes the memory lock and erases the existing reset targets. It never
recovers pending memory operations before erasing them. Both stable lock files
remain empty outside the removed trees. A fresh store gets a new instance ID,
so old proposals are rejected. Uninstall removes the recipe's registered jobs,
including `memory operations`, through the normal cron removal procedure.

There is no automatic downgrade or general restore command. Rollback requires
a verified backup from before enablement and a compatible runtime. Restoring
that earlier snapshot can lose changes made after the backup.
