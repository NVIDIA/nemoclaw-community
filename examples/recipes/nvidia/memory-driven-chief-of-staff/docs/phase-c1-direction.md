<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Phase C1: direction and counterparty contract

Phase C is proposed as one pull request (PR) with three commits: shared data and reader
compatibility (C1), opt-in Graph Sent Items (C2), and opt-in Slack self-authored
collection (C3). It follows [#156](https://github.com/NVIDIA/nemoclaw-community/issues/156)
and the merged Phase B work in #170. The remaining Foundation and dependency
review in #156 still needs maintainer confirmation; this document does not
claim that approval.

## Data contract

Schema v6 preserves the message author and records the counterparty separately.
No sender column is repurposed as a recipient column.

| Field | Meaning |
| --- | --- |
| `sender`, `sender_key`, `sender_handle` | The actual message author, in both directions. |
| `direction` | `inbound`, `outbound`, or NULL when authorship was not recorded. |
| `source_account` | Connected mailbox address, or Slack team/user pair, used to separate reply matching across accounts. |
| `counterparty_key`, `counterparty_name`, `counterparty_handle` | A resolved outbound recipient or responder. NULL when unresolved. |
| `counterparty_basis` | `single_recipient`, `dm`, `mention`, or `reply`; records why attribution was made. |
| `counterparty_candidates` | Outbound mail recipient addresses eligible to resolve a group conversation, stored as JSON. |
| `counterparty_pending_until` | Seven days after the outbound event, for an eligible unresolved group message. |

Historical rows keep NULL direction and identity fields; migration does not
infer authorship. Replaying an existing source ID does not relabel its direction
or restore its cleared body. Fresh collectors in C2/C3 record direction from
the connected identity. C1 alone does not change collector requests.

Mail attribution considers distinct To, Cc, and Bcc recipients, excluding known
addresses of the connected user. Exactly one recipient resolves immediately.
A self-only message has no counterparty. Multiple recipients remain unresolved
until an eligible recipient replies. Slack uses the other member of a 1:1 DM,
then a single non-self mention. Broader messages remain unresolved.

## Reply matching

Only a stored, explicitly inbound reply from the same connected account and
conversation can resolve an outbound row. Email replies may cross folders, but
the responder must be a recorded recipient. Slack also matches the channel and
only resolves a user-authored thread root, not an arbitrary reply within a
thread. The first qualifying reply wins; attribution records `reply` as its basis.

The reply must occur after the outbound event and at or before its deadline.
A reply collected later can qualify if its event time was inside that window,
even after an earlier pass found no reply after the deadline. Unmatched rows
retain that deadline; elapsed wall-clock time does not erase eligibility or
extend the permitted reply event window. Deleted replies do not qualify. A group
exchange is not evidence that the original message targeted only the responder. Resolution changes no author field and parses no message
text as an instruction.

Each resolver pass examines at most 200 pending rows. A persisted keyset cursor
in ledger `meta` rotates by `(counterparty_pending_until, source_id)` and wraps
after reaching the end. Unresolved rows cannot hold every subsequent batch.
Cursor changes and attribution share the caller's transaction, so a failed pass
advances neither. The compound work index is created when the store is opened;
no new ledger version is required. This rotation remains bounded even when old
unmatched records stay eligible for delayed collection.

## Reader and writer boundaries

Intake uses `direction IS NOT 'outbound'`, keeping historical NULL rows usable.
The obligation writer rejects an outbound item even when a stale envelope names
it. Rejection rolls back every decision, audit event, state change, and cursor
in that envelope.

The people selector groups inbound/legacy evidence by author and outbound
evidence by resolved counterparty. It carries direction and attribution basis
into each interaction. Outbound-only evidence cannot admit a person. A candidate
with explicit inbound and outbound evidence has `both_directions=true`; false
means unconfirmed, not that the user never replied. Existing addressing-based
admission remains available when capture is disabled or evidence is incomplete.

Existing people pages also carry an optional `outbound_evidence` marker copied
from the selector. It fingerprints eligible outbound IDs and attribution bases,
independently of event time, and is acknowledged only by saving the updated
page. Backfill and newly resolved counterparties therefore refresh an existing
page without falsely advancing `last_interaction`. Repeated selection before a
successful write retries; after the matching marker is saved, unchanged runs
are quiet. Changes to the outbound set inside the configured window can also
refresh the page. The bounded handoff reserves one snippet for the latest
collected resolved outbound item when this marker changes.

Both directions remain quoted source material. Outbound mail is not an explicit
priority correction. Only the existing user-correction path may change inferred
priorities; the memory-writing skill states this boundary.

## Exclusions and lifecycle

Outbound exclusion checks include the author and known recipient identifiers
and names before insertion. Graph checks all To/Cc/Bcc recipients. A Slack group
whose participant set is unknown is omitted when person/domain exclusions are
configured. A channel exclusion still applies regardless of person resolution.
This conservative rule avoids retaining an unresolved message first and finding
an excluded counterparty later. Unknown member lookup does not bypass it.

The resolver rechecks current exclusions before assigning a counterparty.
Adding an exclusion does not retroactively purge stored messages or derived
pages. Retention clears bodies in either direction, while metadata, including
recipient identities and resolution basis, remains. `store.json` exports every
new item column. Reset removes the ledger containing them; independent exports
and backups require separate removal. Existing derived-page deletion limits
remain as described in [data lifecycle](data-lifecycle.md).

## Migration, rollback, and review

The frozen `schema-v5.sql` is the prior schema fixture. Installation upgrades
columns, replaces the pending-item index, creates conversation and resolution
indexes, and stamps v6 in the migration transaction. Failure rolls back and can
be retried. Index construction scans existing rows and takes the write lock.
Fresh stores create these indexes after initialization; old stores create them
after their columns exist.

Run `migrate.py --check` to check compatibility and `migrate.py` to upgrade.
Migration is forward-only. Before upgrading, stop scheduled jobs and other
writers and retain a private profile backup with a consistent SQLite backup,
plus the matching distribution revision. Rollback restores that profile and
revision together while writers are stopped; post-backup changes are absent.
Never edit the version stamp to let a v5 writer open v6. Portable JSON export and
Phase B's override restore are not a main-ledger downgrade/restore command.

C2 and C3 are independent opt-ins, each defaulting to off. Disabling capture
stops subsequent collection, not retention or deletion of previously stored
content. See [Graph setup](set-up-graph.md#optional-sent-items-collection) and
[Slack setup](set-up-slack.md#optional-self-authored-collection) for cursor
recovery, backfill, source-deletion limits, and scheduled environment settings.

The proposed owner is @rebelle5868. The one-PR organization does not replace the
requested child-issue contracts or resolve the Foundation/C1 dependency gate.
This change adds no entity schema, page adoption, or new page writer. Review must
confirm those boundaries and the seven-day attribution rule before publication.

Validation uses temporary profiles and synthetic API-shaped messages. It covers
supported schema upgrades, historical NULL rows, author/counterparty separation,
reply deadlines and account/channel isolation, exclusions, atomic obligation
rejection, memory evidence, export, retention, and interrupted migration.
