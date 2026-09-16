<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Customizing a shipped skill

Keep custom instructions in
`workspace/skill-overrides/overrides/<skill>/SKILL.md` under the installed
profile. Hermes reads `skills/<skill>/SKILL.md`; the hourly `--apply` job
copies a validated override there. Profile updates preserve the workspace,
but can replace the live skill file.

A customization can replace the entire instruction file. Review it before
applying it, including any permission, connector, and retrieval instructions.
Run these commands from the recipe source directory, with `HERMES_HOME` set
to the intended installed profile. Stop its scheduled jobs and avoid concurrent
Hermes profile updates while installing, rebasing, exporting, or restoring.
The recipe's commands share locks; Hermes updates do not take those locks.

## Register the distribution

`scripts/install.sh` records shipped content from the recipe source it has
just installed, before applying overrides. It stores the complete skill list,
exact content, and hashes. Registration never copies live installed bytes into
this history and never changes live skills.

After a bare `hermes profile update`, use the same reviewed recipe checkout
and revision that supplied the update:

```bash
python3 profile/scripts/skill_overrides.py --record-distribution "$PWD/profile"
python3 profile/scripts/skill_overrides.py --check
```

This command accepts the source you provide as authoritative; it does not
verify a publisher signature. Do not point it at unreviewed content or a copy
of the installed profile. The installed profile and its descendants are
refused as sources. Keep the source checkout unchanged during registration.

An ordinary tick never treats changed bytes as proof of an update. Unknown
live content produces `blocked`, even when its frontmatter is valid. Resolve
it by checking the installed version against the reviewed source. If it is
a legitimate update, register that source. Otherwise restore the installed
file from the accepted source before retrying. Registration refuses while an
apply/remove operation is pending; finish or investigate that operation first.

On an installation upgraded from the earlier override implementation, old
observations remain available for export but are not automatically trusted.
Register its reviewed source before using the override commands.

## Create and apply an override

```bash
python3 profile/scripts/skill_overrides.py --fork inbound-judging
```

Edit the new workspace file. Its `based_on_sha256` identifies the accepted
base; keep that field unchanged while editing instructions. `--fork` never
overwrites an existing customization.

```bash
python3 profile/scripts/skill_overrides.py --check
python3 profile/scripts/skill_overrides.py --apply
```

`--check` writes nothing. It reports `blocked` if an interrupted apply or remove
operation is still pending, including when the file write already landed. Run
the named mutating command to reconcile and finish that operation. The installer
and hourly job run `--apply`; a successful apply makes the customization
effective for subsequent skill loads. Every command prints findings and
`{"wakeAgent": false}`. None uses a model call.

## Rebase after a shipped change

When the accepted base differs from `based_on_sha256`, `--apply` reports
`skipped-stale` and leaves both the live file and the override untouched.
There is no automatic merge. Export a copy before removing the old override:

```bash
python3 profile/scripts/export_store.py --to /path/to/export
python3 profile/scripts/skill_overrides.py --remove inbound-judging
python3 profile/scripts/skill_overrides.py --fork inbound-judging
```

Review the exported customization against the new fork and copy only the
changes you still want. Then run `--check` and `--apply`. Running `--fork`
alone while an override exists reports `skipped-exists`.

## Findings and exit codes

The command returns 1 if any finding requires attention, otherwise 0.
Argument errors return 2. Other skills continue when one skill is blocked.

| Finding | Exit | Meaning |
| --- | --- | --- |
| `distribution-recorded` | 0 | Accepted a base from the selected source. |
| `restored` | 0 | Restored override state without writing live skills. |
| `forked` / `applied` / `removed` | 0 | Completed the requested operation. |
| `preserved-live` | 0 | Reset left content not written by the override feature unchanged and removed its tracked state. |
| `skipped-exists` / `skipped-no-override` | 0 | Nothing to create or remove. |
| `reconciled-complete` / `reconciled-retry` / `reconciled-abandoned` | 0 | Recorded the outcome of an interrupted operation. |
| `blocked` | 1 | Unknown distribution/live content, or an unresolved operation. |
| `skipped-stale` | 1 | Review and rebase the customization. |
| `orphaned-override` | 1 | The live file is missing; absence does not prove upstream removal. |
| `skipped-invalid` | 1 | Invalid override metadata or an unapproved base. |
| `skipped-no-base` / `skipped-missing-base` | 1 | No accepted or intact base is available for restoration. |
| `skipped-unknown-skill` | 1 | No installed skill to fork. |
| `reconciled-diverged` | 1 | Live content differs from both recorded operation states. |
| `error` / `reconciled-error` | 1 | A file, lock, database, or bundle operation failed. |

The accepted distribution list determines whether a skill is still shipped.
A missing live file alone does not update that list. If an accepted new
source removes a skill, its override remains stored and blocked; remove/reset
will not recreate it from historical bytes. Export it before resolving its
retirement manually. A missing installed file for a skill still in the
accepted distribution can be restored from its retained base by `--remove`.

## Export and restore

An export contains readable override copies and
`skill-overrides-recovery.json`, a versioned bundle with every retained base,
accepted distribution entry, approval, observation, applied manifest row, and
apply/remove operation record. It also preserves live skill bytes as recovery
evidence. Override bytes survive even when they are invalid UTF-8.

Only restore an export you trust: it contains instructions and authority
records. Checksums detect corruption, not authorship. Restore requires an
absent `workspace/skill-overrides/` directory and refuses existing state.
For an existing profile, export first and use the documented
[full reset](data-lifecycle.md#be-rid-of-all-of-it) only if you intend to delete
its ledger, memory, policy, collection state, and overrides together.

```bash
python3 profile/scripts/skill_overrides.py --restore /path/to/export/skill-overrides-recovery.json
python3 profile/scripts/skill_overrides.py --check
python3 profile/scripts/skill_overrides.py --apply
```

Restore validates the complete bundle before installing it. It rebuilds a
fresh database from known tables and atomically publishes the feature state.
It does not execute imported SQL, replace live skills, restore the main
recipe ledger or memory, or reinstall credentials. The original base
relationship and operation history survive without another fork.

If the installed version changed after export, restore still preserves the
customization, but apply blocks unknown content. Register the reviewed update
source, then rebase the stale override as above. An interrupted operation
retains its original intent: an apply can retry on the next tick; a remove
requires `--remove` for that skill. Diverged content requires investigation.

A crash before restore publishes its directory leaves only
`workspace/.skill-overrides-restore`. Retrying restore replaces that staging
directory; reset also removes it. A crash after publication leaves the complete
state. Retrying restore then refuses to replace it; use `--check` instead.

## Rollback and reset

`--remove <skill>` restores the latest accepted base and removes that
customization. Unknown live content or a missing base blocks it.
`reset.py --yes` first restores active customizations and then removes all
tracked recipe data. If another writer already replaced an applied override and
no pending operation is diverged, reset leaves that live content unchanged and
removes the tracked override state. A genuinely diverged pending operation or a
missing base for an override that is still live prevents deletion and preserves
the overrides and history for investigation. An earlier skill in that same
reset may already have its live base restored.

## Relationship to skill evolution (#159)

[#159](https://github.com/NVIDIA/nemoclaw-community/issues/159) proposes an
automatic learning module; this feature manages manually edited full-file
overrides. The proposed module is not implemented here. Its future
`LEARNED.md` loader would be part of the shipped skill: a changed base blocks
an older override until review, so an old override cannot automatically erase
that new loader. A user can still remove a loader deliberately while editing
a current override. Integration must define and test any protected loader
contract when #159 is implemented; this feature does not claim that contract
already exists.
