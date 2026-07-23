<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Memory and privacy

The review advisor separates committed repository knowledge from experiential
memory.

- `profile.yaml` says what maintainers currently consider important. It is
  versioned, inspectable, and changed through normal repository review. Review
  sessions load it from the exact target-base tree, never the PR head or dirty
  working tree.
- Hermes memory records a small number of lessons written by maintainers while
  adjudicating prior reviews.
- `review.json` retains complete candidate provenance outside memory.

Review sessions receive a frozen read-only snapshot of Hermes memory, but no
memory tool. Repository and PR content therefore cannot write durable memory.
Only `scripts/feedback.sh`, invoked by a trusted operator with an explicit
disposition and a bounded maintainer-authored `--lesson`, can call Hermes'
native memory store.

The feedback path validates the verified artifact, repository binding,
candidate linkage, evidence shape, and candidate source. It persists only the
curated lesson plus compact provenance: disposition, repository, affected
paths, candidate ID, a digest of the candidate evidence, target-base,
merge-base, and head SHAs, profile digest, profile calibration-source commit,
acceptance-context digest, and overall context digest. It does not copy the
model-authored candidate statement, rationale, or evidence text into memory,
and it does not persist patches, source excerpts, PR or linked-issue
descriptions, or review comments there. The trusted-host acceptance fetcher
never requests review comments, issue comments, timelines, or prior advisor
output. Hermes applies its normal prompt-injection scan before accepting the
curated entry.

Memory is never evidence. The review skill requires current patch or checkout
evidence before a remembered pattern can become a finding.

By default the lifecycle derives a repository-install-specific sandbox name.
Do not configure two repositories with the same `NEMOCLAW_SANDBOX_NAME`, and do
not restore a snapshot from one repository into another. Snapshot manifest
schema v2 binds every archive to the exact sandbox name, installation ID, and
configured repository as well as its archive name and SHA-256 digest. Restore
validates all of those fields and rejects snapshots copied from another
repository, sandbox, install path, or installation.

Hermes' built-in store is deliberately bounded. When it fills, consolidate or
remove old lessons instead of copying raw review history into it. Full review
artifacts belong in the repository's normal artifact retention system. The
generated GitHub Actions workflow keeps uploaded review artifacts for seven
days.

## Inference endpoint boundary

`NEMOCLAW_ENDPOINT_URL` is a privacy and retention boundary, not only a routing
setting. The endpoint can receive all model-visible request data: system and
review prompts, repository profile, current patch and requested file content,
the bounded PR and linked-issue snapshot, review tool results, and recalled
curated lessons. The credential is injected by OpenShell at
`inference.local`; it is not exposed to Hermes tools or the publisher.

This example does not control or make a zero-retention promise for the
configured endpoint. A hosted NVIDIA endpoint is governed by the terms and
configuration of that service; another OpenAI-compatible endpoint is governed
by its operator; a genuinely local endpoint keeps this boundary local only
when it is configured and operated that way. Before reviewing sensitive code,
operators must confirm that the selected endpoint's transport, access,
logging, training-use, and retention controls meet their policy.

The snapshot helper exports only `/sandbox/.hermes/memories`. It excludes
provider credentials, `.env`, sessions, repository contents, and review input.
Restore requires the adjacent manifest, verifies every member plus the archive
name and digest, stages the replacement before changing live memory, and rolls
back the prior memory directory if replacement fails. Version 0.1 intentionally
does not provide a cross-install memory-migration or manifest-rebinding path.
Validation also caps the compressed archive at 64 MiB, 10,000 members, each
regular member at 16 MiB, cumulative member content at 128 MiB, and the entire
expanded tar stream at 192 MiB. It rejects deep, overlong, odd, link-like,
special, duplicate, and portable-filesystem-colliding paths before upload.

The manifest digest and identity binding detect corruption and accidental
snapshot mixups; they are not an authenticity signature. An attacker who can
replace both the archive and manifest can recompute the digest. Keep snapshots
in the private install-scoped state directory. Any external snapshot store must
add a trusted signature or MAC (with its key outside that store), or equivalent
KMS-backed integrity and access control, before its contents are authoritative.
