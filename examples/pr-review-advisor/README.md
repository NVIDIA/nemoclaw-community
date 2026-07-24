<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# NemoClaw Review Advisor

This first-party NemoClaw turns Hermes and Nemotron 3 Ultra into a reusable,
repository-aware pull-request review advisor. Its first-party design combines
exact-head binding, staged analysis, a canonical finding ledger, artifact
validation, and a separate publisher without embedding NemoClaw-specific
assumptions in the engine.

The example is Hermes-only. Its review protocol is an auditable Hermes skill
source plus a stateful, read-only Hermes plugin. The plugin returns that trusted
protocol from `review_begin`; the review API does not expose Hermes' mutable
skill-management toolset.

This is an educational blueprint, not a hosted review service.

## What it does

- Installs into a repository with one command.
- Deterministically bootstraps a repository profile from a trusted committed
  tree without executing repository code.
- Reviews the complete bounded `merge-base..head` change using Nemotron Ultra,
  while separately binding the live target-base tip.
- Snapshots the current PR title/body and only same-repository issues referenced
  by explicit closing keywords, then removes the GitHub token before model work.
- Runs six enforced ledger stages: scope, correctness, security, tests,
  operations, and reconciliation, followed by synthesis.
- Recalls compact lessons written and explicitly approved by maintainers through
  the trusted feedback command.
- Produces normalized JSON and Markdown artifacts by default.
- Publishes only through a separate, explicit host command that rechecks the
  live GitHub base and head.

Repository files, patches, documentation, commit messages, PR text, and linked
issue text are always untrusted data. A remembered lesson is a hint; every
claim must be re-established against the current patch and checkout.

## Architecture

```text
trusted Git tree + exact SHAs + bounded current-PR acceptance snapshot
          │
          ▼
host preparer ── complete bounded context + detached head-only checkout
          │
          ▼
OpenShell sandbox
  Hermes + Nemotron Ultra
  auditable /pr-review skill source
  read-only review plugin + trusted protocol
  ordered finding ledger
          │
          ▼
attested review.json + host verification receipt + review.md
          │
          ├── maintainer-authored lesson ───► Hermes memory
          └── explicit host publisher ──────► GitHub comment
```

The review session has no terminal, browser, web, generic filesystem,
delegation, cron, memory-write, session-search, or GitHub-write tool. Only the
review plugin can inspect the prepared checkout. OpenShell stores the inference
credential and injects it at the `inference.local` boundary; the publisher never
loads that credential. For each run, the trusted host gives the plugin a fresh
32-byte attestation key outside the model-visible tool results. The host accepts
and persists an artifact only after its HMAC and exact request identity verify
and the ephemeral Hermes session has been deleted.

The configured inference endpoint is a data boundary. Model requests can
contain the system prompt, repository profile, current patch and file content,
PR and linked-issue snapshot, tool results, and recalled curated lessons.
`NEMOCLAW_ENDPOINT_URL` selects who receives that data. This project does not
control or promise the endpoint's logging or retention behavior: operators must
choose a hosted, compatible, or local endpoint whose data policy and
configuration meet their requirements.

## Requirements

- Linux host with Docker
- OpenShell `0.0.85` and a reachable local gateway
- Git, Node.js 22.19.0 or newer, Python 3, and curl
- GitHub.com when using the generated workflow, acceptance-context fetcher, or
  optional publisher; these v0.1 integrations do not support GitHub Enterprise
  Server
- A self-hosted GitHub Actions runner `2.327.1` or newer for the pinned
  Node.js 24 `actions/checkout@v6` and `actions/upload-artifact@v7` actions;
  `upload-artifact@v7` is GitHub.com-only
- An organization runner group with the generated repo-specific name,
  restricted to this repository and the exact advisor workflow at
  `refs/heads/<default-branch>`
- One explicit provider contract: an NVIDIA API key with Nemotron Ultra access,
  an OpenAI-compatible endpoint/key/model tuple, or an existing pre-registered
  OpenShell provider and model
- A step-scoped GitHub token when fetching current-PR acceptance context
- `gh` only when using the optional publisher

## Install in one command

From the repository to review:

```console
$ npx --yes @nvidia/nemoclaw-review-advisor@0.1.0 init .
```

The first `--yes` answers `npx`'s package-install prompt. The advisor installer
still shows its full proposed diff and asks before writing. For an already
reviewed non-interactive invocation, append a second `--yes` after the target:

```console
$ npx --yes @nvidia/nemoclaw-review-advisor@0.1.0 init . --yes
```

Until the package is published, use the checked-out source tree:

```console
$ node /path/to/nemoclaw-community/examples/pr-review-advisor/installer/bin/cli.mjs init .
```

The initializer resolves the real Git root and trusted ref, inventories tracked
regular files, and writes:

```text
.nemoclaw/review-advisor/
  config.yaml
  profile.yaml                 # active, maintainer-owned; never overwritten
  profile.generated.yaml       # deterministic refresh candidate
  discovery.lock.json
  memory-policy.yaml
  install-state.json
  runtime/
.github/workflows/nemoclaw-review-advisor.yml
```

The generated workflow is manual, read-only, and artifact-only. It retains its
uploaded review artifacts for seven days. There is no `pull_request_target`
trigger and no publisher job. Its trusted fetch step uses the step-scoped
Actions token to bind the current PR title/body and explicit closing issues to
the requested repository, PR number, base, and head. It fetches the base and PR
head into an exact repository-ID/run-ID/attempt-scoped private directory under
`RUNNER_TEMP`; the persistent
trusted workflow checkout is never the target of the PR fetch and receives no
PR ref or PR-only objects from this workflow. The review step receives that
temporary repository and the bounded snapshot file, but no GitHub token. After
an exact four-file artifact preflight, upload runs only when the review and
preflight both succeed. An `if: always()` step then removes the whole per-job
temporary directory and advisor output from the self-hosted runner. A
repository-scoped concurrency group queues overlapping runs without canceling
evidence-producing runs, avoiding same-install sandbox and gateway-route
races.

The workflow derives a repo-specific sensitive runner-group name and expects a
prepared runner in that group carrying the `self-hosted`, `linux`, and
`nemoclaw` labels. Before registering the runner, restrict the group to this
repository and the exact workflow:

```text
OWNER/REPOSITORY/.github/workflows/nemoclaw-review-advisor.yml@refs/heads/DEFAULT_BRANCH
```

That GitHub-side restriction prevents a branch-owned copy of the workflow from
claiming the persistent runner. The workflow's own default-branch condition is
defense in depth, not the authorization boundary. The runner also needs the
host requirements above, a reachable OpenShell gateway, and this repository's
advisor sandbox brought up before dispatch. The one-command installer adds
repository configuration and runtime assets; it does not create the
organization runner group, provision a host, or register a GitHub Actions
runner. Version 0.1 of the generated workflow targets GitHub.com only.
Its pinned `actions/checkout@v6` and `actions/upload-artifact@v7` releases use
the Node.js 24 action runtime and require Actions runner `2.327.1` or newer.
`upload-artifact@v7`, the generated workflow and context fetcher, and the
optional publisher do not support GitHub Enterprise Server in v0.1.

Once the dedicated runner, provider, and sandbox are ready, a pipeline or
trusted operator dispatches exact inputs on the default branch:

```console
$ gh workflow run nemoclaw-review-advisor.yml \
    --ref main \
    -f base_sha="$BASE_SHA" \
    -f head_sha="$HEAD_SHA" \
    -f pr_number=123
```

See [Deployment topology](docs/deployment.md) for the recommended persistent
private-runner appliance, public-fork safety boundary, ephemeral-runner
tradeoffs, and later ARC/App scale-out path.

### What “learns the repository” means

Bootstrap is deterministic. It examines the trusted committed tree for
architecture and security guidance, CODEOWNERS, manifests, workflows, tests,
and layout concentrations. Every generated priority points back to a blob OID
or discovery record. It never runs a build, hook, filter, package manager, test,
or repository script.

Version 0.1 does **not** invoke a model during installation or claim that the
deterministic profile is model-calibrated. Maintainers review and edit the
active `profile.yaml`. If discovery finds no repository-specific signals, the
generated priority is an explicitly evidence-free, low-confidence portable
checklist. It is not evidence about what the repository considers important
and must be customized by maintainers; any finding still requires current code
or patch evidence.

Refresh the trusted-tree census later with:

```console
$ bash .nemoclaw/review-advisor/runtime/scripts/refresh.sh . \
    --trusted-ref refs/remotes/origin/main
```

Refresh updates the generated candidate and shows drift. It does not overwrite
the active profile or memory.

The active profile must be committed at
`.nemoclaw/review-advisor/profile.yaml`. Every review loads its exact bytes
from the requested base commit, never from the PR head or working tree.
`metadata.source_commit` records the trusted commit used to calibrate the
profile. The host requires that provenance commit to be an ancestor of the
requested base. It is normally the parent of the commit that first adds or
refreshes the profile, so it does not create an impossible self-reference.

Repository evolution can carry a committed profile forward. Run `check` to see
non-blocking calibration/candidate lag notices, and refresh when maintainers
want to recalibrate against a newer trusted tree:

```console
$ node .nemoclaw/review-advisor/runtime/installer/bin/cli.mjs \
    activate-profile . --trusted-ref refs/remotes/origin/main
```

`activate-profile` requires confirmation and updates only the maintainer-owned
active profile. Commit the reviewed profile change before using it: uncommitted
profile bytes are deliberately ignored by the reviewer.

## Configure and bring up

```console
$ install -m 600 .nemoclaw/review-advisor/runtime/.env.example \
    .nemoclaw/review-advisor/.env
$ # Select a provider mode and fill its required values in the private .env
$ openshell settings set --global --key providers_v2_enabled --value true --yes
$ bash .nemoclaw/review-advisor/runtime/scripts/bring-up.sh
```

When no sandbox/provider names are configured, the scripts derive names from
the real installation path, configured repository, and exact review-scope
digest. That default is intentional: two repositories or two scopes must not
share a Hermes home or memory. A `refresh` that deliberately replaces the
complete scope therefore starts a new runtime and memory identity; the old
scope's lessons are not recalled. Snapshot or export the old scope first if it
must be retained. If names are overridden, they must remain unique per
repository and scope. Reusing an old name fails the runtime-fingerprint check;
snapshot and explicitly destroy the old sandbox before replacing it.

The scripts bind every OpenShell operation explicitly to `OPENSHELL_GATEWAY`
and configure the managed-inference route on that gateway without changing the
user's global gateway selection. That route is gateway-scoped, not private to
one sandbox, so every advisor installation requires its own dedicated gateway
name and endpoint.

The loopback API key, lifecycle lock, logs, and memory snapshots live outside
the checkout under
`${XDG_STATE_HOME:-$HOME/.local/state}/nemoclaw-review-advisor/<install-id>/`.
`REVIEW_ADVISOR_STATE_ROOT` can relocate that private state root. The generated
workflow preserves explicitly ignored local advisor configuration and exports
while cleaning its self-hosted workspace; the API key remains outside that
workspace, so checkout cleanup cannot rotate it.

For a host-served Ultra model reached through OpenShell, use
`http://host.openshell.internal:<port>/v1` and, for example,
`NEMOCLAW_MODEL=nvidia/nemotron-3-ultra-550b-a55b`. Do not use `127.0.0.1` for
a gateway-to-host model: it refers to the gateway side, not the model service
on the host. Plain HTTP is accepted only for a literal loopback address or the
exact `host.openshell.internal` bridge; arbitrary plaintext LAN and DNS
endpoints are rejected.

### Provider contract

`REVIEW_ADVISOR_PROVIDER_MODE` is a fail-closed, non-interactive provider
contract:

| Mode | Required configuration | Managed behavior |
| --- | --- | --- |
| `nvidia` (default) | Exactly `NVIDIA_INFERENCE_API_KEY`; optional `NEMOCLAW_ENDPOINT_URL` (defaults to NVIDIA), `NEMOCLAW_MODEL` (defaults to Nemotron Ultra), and install-derived `INFERENCE_PROVIDER_NAME` | Creates or updates an OpenShell `nvidia` provider with fixed `NVIDIA_API_KEY` and `NVIDIA_BASE_URL` mappings. |
| `openai-compatible` | Exactly `COMPATIBLE_API_KEY`, plus explicit `NEMOCLAW_ENDPOINT_URL` and `NEMOCLAW_MODEL`; optional install-derived `INFERENCE_PROVIDER_NAME` | Creates or updates an OpenShell `openai` provider with fixed `OPENAI_API_KEY` and `OPENAI_BASE_URL` mappings. |
| `existing` | Explicit `INFERENCE_PROVIDER_NAME`, `REVIEW_ADVISOR_EXISTING_PROVIDER_TYPE`, and `NEMOCLAW_MODEL` | Requires a pre-registered provider with that exact name and reviewed inference-capable type: `nvidia`, `openai`, or `deepinfra`. Credentials and `NEMOCLAW_ENDPOINT_URL` are forbidden; the advisor never creates, updates, or rotates the provider. |

All modes require a dedicated HTTPS `OPENSHELL_GATEWAY_ENDPOINT` in the private
`.env`; `OPENSHELL_GATEWAY` may be omitted for an install-derived name. The
scripts reject mode-incompatible fields, configure the exact provider/model
route, and verify that route before continuing. They do not guess credential
aliases or prompt for missing values. Version 0.1 deliberately rejects
arbitrary or `generic` existing-provider types; extending that allowlist is a
reviewed runtime change, not configuration-only plugin discovery.

Remote inference endpoints must use HTTPS. The only plaintext exceptions are a
literal loopback origin and exact `host.openshell.internal`, the reviewed
OpenShell host-backed route described above.

Provider credentials stay in the private host configuration, a same-name CI
secret environment variable, and OpenShell's provider store. Hermes and the
model receive only the managed inference interface at `inference.local`; the
credential is not placed in the review payload, tool environment, artifacts,
or publisher.

For example, a runner-provisioning step can keep the secret in the pipeline
environment and write only non-secret route configuration to the ignored
mode-`0600` file before the generated artifact-only workflow runs:

```yaml
- name: Bring up review advisor
  env:
    NVIDIA_INFERENCE_API_KEY: ${{ secrets.NVIDIA_INFERENCE_API_KEY }}
  run: |
    set -eu
    umask 077
    config=.nemoclaw/review-advisor/.env
    test ! -L "$config"
    install -m 600 /dev/null "$config"
    {
      printf '%s\n' 'REVIEW_ADVISOR_PROVIDER_MODE=nvidia'
      printf '%s\n' 'OPENSHELL_GATEWAY_ENDPOINT=https://127.0.0.1:17670'
    } >"$config"
    openshell settings set --global \
      --key providers_v2_enabled --value true --yes
    bash .nemoclaw/review-advisor/runtime/scripts/bring-up.sh
```

Use an environment-scoped pipeline secret and a dedicated runner/gateway.
In CI, never echo the credential, write it into the checkout, or upload it as
an artifact. A mode-`0600` local `.env` remains supported for host-managed
development. The `existing` mode is the corresponding option when runner
provisioning owns provider registration and credential rotation.

## Run a review

Using full locally available commit SHAs, first capture current acceptance
evidence on the trusted host:

```console
$ NEMOCLAW_GITHUB_TOKEN="$(gh auth token)" \
    .nemoclaw/review-advisor/runtime/scripts/fetch-pr-context.py \
      --repository owner/repository \
      --pr-number 123 \
      --base "$BASE_SHA" \
      --head "$HEAD_SHA" \
      --output "$RUNNER_TEMP/pr-acceptance.json"
```

Then run without a GitHub credential:

```console
$ unset NEMOCLAW_GITHUB_TOKEN GH_TOKEN GITHUB_TOKEN
$ bash .nemoclaw/review-advisor/runtime/scripts/review.sh \
    --repo . \
    --base "$BASE_SHA" \
    --head "$HEAD_SHA" \
    --repository owner/repository \
    --pr-number 123 \
    --acceptance-context "$RUNNER_TEMP/pr-acceptance.json" \
    --output ./.nemoclaw/review-advisor/output
```

For a local GitHub event payload, the fetch helper and reviewer both support
the same `--event` identity:

```console
$ NEMOCLAW_GITHUB_TOKEN="$(gh auth token)" \
    .nemoclaw/review-advisor/runtime/scripts/fetch-pr-context.py \
      --event "$GITHUB_EVENT_PATH" \
      --output "$RUNNER_TEMP/pr-acceptance.json"
$ unset NEMOCLAW_GITHUB_TOKEN GH_TOKEN GITHUB_TOKEN
$ bash .nemoclaw/review-advisor/runtime/scripts/review.sh \
    --repo "$GITHUB_WORKSPACE" \
    --event "$GITHUB_EVENT_PATH" \
    --acceptance-context "$RUNNER_TEMP/pr-acceptance.json" \
    --output "$RUNNER_TEMP/nemoclaw-review"
```

Both commits must already exist locally. This keeps network fetching and
credential use outside the reviewer. The acceptance helper calls only the
current PR REST endpoint and issue endpoints selected by explicit closing
keywords in the current PR body. It fails closed on identity drift, redirects,
oversized text, more than ten closing issues, linked PRs, and unsafe files. It
never requests review comments, issue comments, timelines, or prior advisor
output.

The preparer:

- resolves the real Git root;
- requires exactly one result from `git merge-base --all BASE HEAD` and uses
  that object, not the moving target-base tip, as the start of the PR patch;
- rejects symlinks and submodules;
- loads the sole non-executable regular profile blob from the exact target base
  and validates that its `source_commit` is an ancestor of that base;
- disables hooks, global/system Git config, submodule recursion, textconv, and
  external diff commands;
- refuses to materialize an exact-head tree above 50,000 files or 512 MiB of
  raw blob content;
- materializes exact raw blobs with `git cat-file`, preserving only the tracked
  executable bit and never running checkout filters, smudge commands, or
  repository code;
- gives the model-facing tree only a detached `.git/HEAD` marker—no Git objects,
  refs, config, remotes, credentials, or filters;
- supplies the full text change or fails when the separate change bound is
  exceeded (512 changed files and 32 MiB of serialized context by default),
  without silent truncation.

The 50,000-file/512-MiB checkout bounds limit exact-head materialization; they
do not claim that a change of that size is reviewable. The host accepts at most
10,000 changed files as an absolute parser ceiling, while the installed default
and plugin both refuse more than 512. The plugin also refuses a patch whose
complete coverage would require more than 128 bounded diff reads (each at most
400 lines and 256 KiB). Raising a host bound does not raise those model-review
limits.

The Hermes appliance allows 256 model turns so a one-tool-per-turn execution
can cover all 128 bounded diff reads plus repository checks and the ordered
review stages. Each model call uses six Hermes-native, `Retry-After`-aware
attempts to absorb transient provider throttling; the host never starts a
second agent turn after an incomplete or failed response. The host's 30-minute
inference deadline remains the hard wall-clock bound. `review_diff` is also a
per-path coverage cursor: overlapping or repeated requests advance to the next
unread chunk, and every result points to the next exact uncovered path and
line. If the final assistant text omits the artifact, the host performs one
bounded read of that exact Hermes session and accepts only a linked, attested
`review_finalize` result. Provider failure metadata is bounded and surfaced
after that recovery check; no raw response or transcript becomes durable.

The documented durable outputs are `review.json`, `review.md`,
`verification.json`, and `request.json`. The verification receipt binds the
persisted artifact bytes to the HMAC, request-identity, and Hermes-session
deletion checks performed by the trusted host, including the target base, merge
base, head, profile digest, calibration-source SHA, and acceptance-context
digest. The target `base_sha` remains distinct so
publication staleness is checked against the live target-branch tip. It cannot
publish.

If Hermes' final assistant turn omits the requested JSON envelope, the host
does not ask the model to repeat the review. It makes one authenticated,
bounded read through Hermes' advertised session-messages API and accepts only
an exact `review_finalize` tool result linked to its assistant tool call. The
same schema, HMAC, and request-identity checks apply. Session history is never
persisted, and the exact session lineage is still deleted before any artifact
is written.

## Teach it from reviewed outcomes

`review.json` contains lesson **candidates**, not durable memory. An authorized
maintainer promotes one explicitly:

```console
$ bash .nemoclaw/review-advisor/runtime/scripts/feedback.sh \
    --artifact ./.nemoclaw/review-advisor/output/review.json \
    --candidate L-0123456789abcdef \
    --disposition accepted \
    --lesson "Require an authorization check at this request boundary."
```

Dispositions are `accepted`, `dismissed`, and `corrected`. Every disposition
requires a bounded lesson written by the maintainer; the model's candidate
statement is never copied into memory. The host validates the candidate,
evidence shape, source identity, artifact receipt, and repository binding, then
calls Hermes' native memory implementation outside the model session. Only the
curated lesson and compact provenance—including a digest of the candidate
evidence—become durable memory. Raw patches, PR prose, comments, candidate
statements, rationales, and evidence text are never persisted there. The next
fresh review session sees the compact lesson and must reverify it against
current code.

Inspect, export, or explicitly reset memory:

```console
$ bash .nemoclaw/review-advisor/runtime/scripts/memory.sh inspect
$ bash .nemoclaw/review-advisor/runtime/scripts/memory.sh \
    export ./.nemoclaw/review-advisor/memory-export
$ bash .nemoclaw/review-advisor/runtime/scripts/memory.sh reset --yes
```

See [Memory and privacy](docs/memory-and-privacy.md) for the trust model and
current built-in memory limits.

## Snapshot and restore memory

```console
$ SNAPSHOT=$(bash .nemoclaw/review-advisor/runtime/scripts/snapshot.sh)
$ bash .nemoclaw/review-advisor/runtime/scripts/restore.sh "$SNAPSHOT"
```

The scoped snapshot contains review memory, not model credentials,
configuration, repository contents, or review inputs. Restore validates every
archive member and rolls back the memory directory if replacement fails. Its
schema-v2 manifest binds the archive name and digest to the exact sandbox,
installation ID, and configured repository. A snapshot from another sandbox,
repository, install path, or copied installation is deliberately rejected. The
plain digest detects corruption and mixups; it is not an authenticity
signature, so external custody requires a trusted MAC/signature or
KMS-controlled integrity layer.

## Optional publication

Publication is deliberately absent from `review.sh`. After inspecting the
artifact, run the separate host publisher:

```console
$ bash .nemoclaw/review-advisor/runtime/scripts/publish.sh \
    --artifact ./.nemoclaw/review-advisor/output/review.json \
    --repo owner/repository \
    --pr 123 \
    --head "$HEAD_SHA" \
    --confirm-publish
```

The publisher reconstructs the comment from the normalized artifact and checks
the adjacent `verification.json` receipt, exact artifact digest, and
repository/PR/base/merge-base/head identity. When the reviewed artifact bound
acceptance context, it uses the operator's existing `gh` credential to refetch
the current bounded PR/title/body/closing-issue snapshot immediately before
publication and requires the exact digest to match. The fetch also fails if the
PR is no longer open or its base/head changed. Artifacts without acceptance
context receive an open/base/head recheck instead. Only then can the publisher
write the comment. It never loads `.env` and cannot access the inference key.

## Verify and stop

```console
$ bash .nemoclaw/review-advisor/runtime/scripts/verify.sh
$ bash .nemoclaw/review-advisor/runtime/scripts/tear-down.sh
```

Provider setup verifies the configured credential, endpoint, and model before
persisting the route. The later runtime check sends only the static prompt
`Reply with OK.` with a one-token limit through the sandbox's
`inference.local` policy boundary. It validates a bounded completion response
without creating a Hermes session, transcript, or memory entry. The selected
provider may still log that readiness request under its own data policy.

The normal teardown stops only the loopback forward. Destroying the sandbox is
explicit and should follow a memory snapshot:

```console
$ bash .nemoclaw/review-advisor/runtime/scripts/tear-down.sh --destroy-sandbox
```

## Profiles

[`review-profiles/generic.yaml`](review-profiles/generic.yaml) documents the
portable profile shape. Its evidence-free priorities are checklist prompts,
not claims about an arbitrary real repository and not substitutes for current
code evidence. [`review-profiles/nemoclaw.yaml`](review-profiles/nemoclaw.yaml)
is the public worked example of the real NemoClaw components, evidence, and
priorities used by this advisor design, pinned to the latest published
NemoClaw tag at preparation time: `v0.0.93`
(`ac5579e99838b4c0437669f347488abba0956eef`). Installed repositories use their
generated, maintainer-owned active profile.

### Repository-local dogfood profile

This repository's [`config.yaml`](config.yaml),
[`dogfood/profile.yaml`](dogfood/profile.yaml), and
[`dogfood/memory-policy.yaml`](dogfood/memory-policy.yaml) are source-only
first-party dogfood inputs. They are deliberately excluded from the npm
package: a normal installation generates repository-specific configuration
under `.nemoclaw/review-advisor/`.

The profile does not exist at its trusted base, so the first review of this
directory is a provisional, local trusted-operator bootstrap. Pin the exact PR
head that contains the profile and bind its Git blob object explicitly:

```bash
BASE_SHA=fd1794ad8e4beac3efb7c2d87a1c4cffdee53abc
git fetch --no-tags origin \
  "+refs/pull/58/head:refs/review-advisor/pr-58"
HEAD_SHA="$(git rev-parse 'refs/review-advisor/pr-58^{commit}')"
PROFILE_PATH=examples/pr-review-advisor/dogfood/profile.yaml
PROFILE_OID="$(git rev-parse "${HEAD_SHA}:${PROFILE_PATH}")"

examples/pr-review-advisor/scripts/review.sh \
  --repo . \
  --base "$BASE_SHA" \
  --head "$HEAD_SHA" \
  --repository NVIDIA/nemoclaw-community \
  --pr-number 58 \
  --profile-path "$PROFILE_PATH" \
  --bootstrap-profile-oid "$PROFILE_OID" \
  --scope-root .github/workflows/nemoclaw-review-advisor-dogfood.yml \
  --scope-root README.md \
  --scope-root THIRD-PARTY-NOTICES \
  --scope-root examples/pr-review-advisor \
  --support-path .github/CODEOWNERS \
  --support-path .github/PULL_REQUEST_TEMPLATE.md \
  --support-path CONTRIBUTING.md \
  --support-path LICENSE \
  --support-path SECURITY.md \
  --output .tmp/dogfood-pr-58
```

That exception is not a GitHub-hosted authorization pattern, and its output
must not automatically publish a verdict or promote memory. After the profile
lands on the default branch, the manual repository workflow reads it from the
trusted base with `--profile-path` and never accepts a bootstrap object ID.

## NemoClaw adoption path

This example is the replacement target for NemoClaw's current review advisor,
not a fork of NemoClaw core. Adopt it in controlled phases:

1. Start from the tagged NemoClaw worked profile, update its evidence only from
   the next published tag being evaluated, and commit the reviewed active
   profile to the target branch.
2. Run this advisor artifact-only beside the current advisor against the same
   exact base, merge-base, and head commits. Compare coverage, finding quality,
   false positives, failure behavior, runtime, and cost without publishing its
   output automatically.
3. Configure the production inference path through either the managed NVIDIA
   contract or an existing pipeline-owned OpenShell provider. Promote only
   maintainer-authored lessons from reviewed outcomes into Hermes memory.
4. Cut the normal pipeline over to this installed runtime and its separate
   exact-head publisher only after the shadow results and persistent-runner
   recovery procedure meet the repository's acceptance bar. Retire the prior
   advisor in a later, independent change.

This path requires no NemoClaw core change and does not import prior review
comments or model-authored lessons as memory.

## Current limits

- One review lifecycle operation runs per installed sandbox at a time.
- Built-in Hermes memory is intentionally compact; store durable policy in the
  committed profile and only high-value, maintainer-authored lessons in memory.
- Repository-wide reviews refuse any symlink or submodule. Scoped reviews
  refuse those entries inside the selected roots while ignoring unrelated
  special entries outside the configured scope.
- Exact-head checkout fails closed above 50,000 files or 512 MiB of raw blobs.
- Change preparation fails closed above the configured complete-context bound
  (512 changed files and 32 MiB by default; 10,000 changed files is the absolute
  parser ceiling).
- Model review independently fails above 512 changed files or 128 bounded diff
  reads for complete coverage, so the effective patch-size limit can be lower.
- Binary changes automatically force a blocked, low-confidence artifact with a
  required human-review limitation because the text protocol cannot inspect
  their contents.
- Bootstrap and profile refresh are deterministic and model-free.
- Snapshot restore is bound to one sandbox, installation ID, and repository;
  v0.1 does not provide cross-install memory migration.
- The generated self-hosted workflow targets GitHub.com only, requires Actions
  runner `2.327.1` or newer, and removes its exact acceptance input and advisor
  output plus its temporary PR Git object store after the artifact-upload
  attempt.
- The optional publisher posts a GitHub issue comment. It does not submit an
  approving or changes-requested GitHub review.
