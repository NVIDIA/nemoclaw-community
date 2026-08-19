<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# NemoClaw Review Advisor installer

This package installs the repository-local configuration and pinned runtime
assets for the first-party Hermes PR Review Advisor.

Registry publication is a separate first-party release action. Until this
package is published, invoke `installer/bin/cli.mjs` from a trusted checkout.
After publication, installation is:

```bash
npx @nvidia/nemoclaw-review-advisor@0.1.0 init .
```

The installer reads only committed Git objects while discovering a repository.
It does not execute repository files, install their dependencies, commit
changes, contact a model, or enable review publication.

The default bootstrap is deterministic: it creates an evidence-linked candidate
from bounded repository metadata and committed blobs. `init` and `refresh`
remain deterministic and model-free.

Installation is repository-wide by default. A maintainer can opt into strict
path scoping with repeatable, canonical repository-relative paths:

```bash
npx @nvidia/nemoclaw-review-advisor@0.1.0 init . \
  --scope-root examples/recipes/nvidia/pr-review-advisor \
  --support-path SECURITY.md \
  --support-path .github/CODEOWNERS
```

Scope roots are the only paths a scoped review may change. Support paths are
readable evidence but are not review roots. The installer sorts and
deduplicates the complete supplied set, rejects overlapping or unsafe paths,
and normally requires every configured path to select a regular blob in the
trusted committed tree. It never uses dirty or untracked working-tree bytes for
discovery.

For a first-party bootstrap whose new scope directory is intentionally absent
from the trusted tree, `init` and `dry-run` alone accept
`--allow-unpopulated-scope`. The missing root is recorded explicitly in the
discovery lock and install state, and its generated component has no evidence:

```bash
npx @nvidia/nemoclaw-review-advisor@0.1.0 init . \
  --scope-root examples/recipes/nvidia/pr-review-advisor \
  --support-path SECURITY.md \
  --allow-unpopulated-scope
```

Later `refresh` calls reuse the recorded scope when no scope flags are supplied.
They continue to surface an unpopulated trusted-tree root and clear that
bootstrap marker only after the trusted ref contains regular files beneath it.
Supplying any scope flag replaces the complete configured set, so include every
desired root and support path. `check` accepts the same repeated flags as an
assertion that the installed scope matches. The generated scope digest is part
of the runtime installation identity. Replacing the scope therefore derives a
new sandbox, state, snapshot, and Hermes-memory identity instead of exposing
lessons learned for the old scope. Export or snapshot the old scope before
refresh when it must be retained.

If that census discovers no repository-specific signals, the generated
evidence-free fallback is only a low-confidence portable checklist. It does not
claim to know the repository's priorities; maintainers must review and
customize the active profile, and review findings still require current code
or patch evidence.

The generated artifact-only workflow targets GitHub.com in version 0.1. Its
pinned Node 24 actions require a self-hosted Actions runner at version
`2.327.1` or newer. It derives a repo-specific organization runner-group name
and requires that group to be restricted to the exact workflow path at
`refs/heads/<default-branch>`; its in-file branch check is defense in depth.
The runner must also carry the `self-hosted`, `linux`, and `nemoclaw` labels.
For a scoped installation, the generated workflow fails before inference when
the merge-base-to-head change contains a path outside the configured roots and
passes the exact repeated scope/support arguments to the trusted runtime.
The PR Git repository, acceptance snapshot, and askpass helper share one
repository-ID/run-ID/attempt-scoped private temporary directory. Artifact
upload runs only after a successful review and exact four-file preflight. An
`if: always()` cleanup step then removes that whole temporary directory and
advisor output. The persistent trusted workflow checkout is never the target
of the PR fetch and receives no PR ref from the generated workflow. A
repository-scoped concurrency group queues overlapping runs and sets
`cancel-in-progress: false`.

See `docs/deployment.md` in the installed runtime for the recommended
persistent private-runner topology and public-fork trust boundary.

Commands:

- `init [path]` proposes and installs the initial configuration.
- `dry-run [path]` prints the complete proposed file diff without writing.
- `check [path]` checks generated-file hashes, requires the active profile to
  match the trusted base-tree blob, rejects unrelated calibration provenance,
  and reports ancestor-only calibration/candidate lag as non-blocking notices.
- `refresh [path]` repeats discovery at the trusted commit and updates the
  generated candidate while preserving the active `profile.yaml`; without an
  explicit `--trusted-ref`, it reuses the recorded installation trust anchor.
- `activate-profile [path]` shows the exact candidate-to-active diff and, only
  after approval, promotes it without making the active profile installer-owned.
- `remove [path]` removes unmodified installer-owned files while preserving
  manual overrides and locally modified files.

Mutating commands require an interactive confirmation or `--yes`.
They hold a Git-scoped installer lock from planning through approval and
revalidate every target immediately before mutation; rollback preserves a
target that changed externally rather than clobbering it.

Commit the installed files before the first review. Reviews always load
`.nemoclaw/review-advisor/profile.yaml` from the exact target base commit.
`metadata.source_commit` is calibration provenance and must be an ancestor of
that base; it is not the hash of the commit containing the profile.
