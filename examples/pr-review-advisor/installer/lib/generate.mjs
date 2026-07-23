// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  GENERATED_WORKFLOW_PATH,
  INSTALL_DIR,
  PACKAGE_NAME,
  PACKAGE_VERSION,
  PROFILE_SCHEMA_VERSION,
} from "./constants.mjs";
import { sha256, stableJson, yamlString } from "./util.mjs";

export function generateRepositoryFiles(repository, census) {
  const files = new Map();
  const profile = generateProfile(repository, census);
  const discoveryLock = generateDiscoveryLock(repository, census);

  addText(
    files,
    `${INSTALL_DIR}/.gitignore`,
    `# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Local credentials, review outputs, and exports must never be committed.
.env
.tmp/
.snapshots/
output/
memory-export/
.Dockerfile.staged
__pycache__/
*.pyc
`,
  );
  addText(files, `${INSTALL_DIR}/config.yaml`, generateConfig(repository));
  addText(files, `${INSTALL_DIR}/profile.generated.yaml`, profile);
  addText(
    files,
    `${INSTALL_DIR}/memory-policy.yaml`,
    generateMemoryPolicy(repository),
  );
  addText(
    files,
    `${INSTALL_DIR}/discovery.lock.json`,
    stableJson(discoveryLock),
  );
  addText(files, GENERATED_WORKFLOW_PATH, generateWorkflow(repository));

  return files;
}

export function generateOverrideProfile(generatedProfile) {
  return generatedProfile.replace(
    "# Deterministic bootstrap candidate. Edit profile.yaml, not this file.",
    "# Maintainer-owned active profile. The installer never overwrites this file.\n" +
      "# Refresh writes new bootstrap candidates to profile.generated.yaml for review.",
  );
}

function generateConfig(repository) {
  return `# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
schema_version: 1
kind: "nemoclaw-review-advisor-config"
repository: ${yamlString(repository.repository)}
trusted_ref: ${yamlString(repository.trustedRef)}
review:
  mode: "artifact-only"
  enabled: true
  automatic_triggers: false
  publication_enabled: false
  profile_candidate: "profile.generated.yaml"
  profile_active: "profile.yaml"
memory:
  policy: "memory-policy.yaml"
  automatic_extraction: false
  writes_require_trusted_feedback: true
`;
}

function generateMemoryPolicy(repository) {
  return `# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
schema_version: 1
kind: "review-advisor-memory-policy"
namespace: ${yamlString(`repository:${repository.repository}`)}
recall:
  cross_repository: false
  memory_is_evidence: false
  require_current_code_verification: true
writes:
  automatic_extraction: false
  require_trusted_feedback: true
  persist_raw_pull_request_content: false
  persist_raw_review_comments: false
retention:
  allow_inspect: true
  allow_export: true
  allow_remove: true
`;
}

function generateProfile(repository, census) {
  const lines = [
    "# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.",
    "# SPDX-License-Identifier: Apache-2.0",
    "#",
    "# Deterministic bootstrap candidate. Edit profile.yaml, not this file.",
    "# source_commit records calibration provenance and must remain an ancestor",
    "# of the target base; the committed base-tree profile is the review authority.",
    `schema_version: ${PROFILE_SCHEMA_VERSION}`,
    'kind: "review-advisor-profile"',
    "metadata:",
    `  name: ${yamlString(repository.repository)}`,
    `  source_commit: ${yamlString(repository.trustedHead)}`,
    `  source_ref: ${yamlString(repository.trustedRef)}`,
    "repository:",
    `  identity: ${yamlString(repository.repository)}`,
    `  default_branch: ${yamlString(repository.defaultBranch || "unknown")}`,
    "required_stages:",
    '  - "scope"',
    '  - "correctness"',
    '  - "security"',
    '  - "tests"',
    '  - "operations"',
    '  - "reconcile"',
    '  - "synthesize"',
    "components:",
  ];

  if (census.layoutConcentrations.length === 0) {
    lines.push(
      '  - id: "repository-root"',
      '    paths: ["**"]',
      '    evidence: [{source: "discovery.lock.json#/layoutConcentrations"}]',
    );
  } else {
    for (const [
      index,
      concentration,
    ] of census.layoutConcentrations.entries()) {
      const id = slug(
        concentration.path === "(repository root)"
          ? "root"
          : concentration.path,
      );
      const glob =
        concentration.path === "(repository root)"
          ? "*"
          : `${concentration.path}/**`;
      lines.push(
        `  - id: ${yamlString(id || `component-${index + 1}`)}`,
        `    paths: [${yamlString(glob)}]`,
        `    evidence: [{source: ${yamlString(
          `discovery.lock.json#/layoutConcentrations/${index}`,
        )}}]`,
      );
    }
  }

  lines.push("priorities:");
  const priorities = buildPriorities(census);
  if (priorities.length === 0) {
    lines.push(
      '  - id: "baseline-correctness"',
      '    title: "Correctness and regression safety"',
      '    rationale: "No repository-specific evidence was discovered; this is a low-confidence, evidence-free checklist that maintainers must customize and reviewers must verify against current code."',
      "    evidence: []",
    );
  } else {
    for (const priority of priorities) {
      lines.push(
        `  - id: ${yamlString(priority.id)}`,
        `    title: ${yamlString(priority.title)}`,
        `    rationale: ${yamlString(priority.rationale)}`,
        "    evidence:",
      );
      for (const evidence of priority.evidence) {
        lines.push(
          `      - path: ${yamlString(evidence.path)}`,
          `        oid: ${yamlString(evidence.oid)}`,
        );
      }
    }
  }

  lines.push("test_surfaces:");
  const testFiles = evidenceForCategory(census, "tests").slice(0, 40);
  if (testFiles.length === 0) {
    lines.push("  []");
  } else {
    for (const test of testFiles) {
      lines.push(
        `  - path: ${yamlString(test.path)}`,
        `    oid: ${yamlString(test.oid)}`,
      );
    }
  }

  lines.push(
    "evidence_policy:",
    "  memory_is_hint_only: true",
    "  require_current_code_evidence: true",
    "unresolved_questions:",
  );
  for (const question of unresolvedQuestions(census)) {
    lines.push(`  - ${yamlString(question)}`);
  }
  return `${lines.join("\n")}\n`;
}

function buildPriorities(census) {
  const definitions = [
    {
      category: "security",
      id: "security-boundaries",
      title: "Security and trust boundaries",
      rationale:
        "Security documentation exists in the trusted tree; verify affected boundaries against current code.",
    },
    {
      category: "architecture",
      id: "architecture-contracts",
      title: "Architecture contracts",
      rationale:
        "Architecture or design documentation exists; check compatibility and boundary changes.",
    },
    {
      category: "codeowners",
      id: "ownership-boundaries",
      title: "Ownership boundaries",
      rationale:
        "CODEOWNERS identifies review boundaries; treat it as routing evidence, not an authorization grant.",
    },
    {
      category: "manifests",
      id: "dependency-and-build-contracts",
      title: "Dependency and build contracts",
      rationale:
        "Tracked manifests define dependency or build surfaces that can amplify change risk.",
    },
    {
      category: "workflows",
      id: "automation-and-release-safety",
      title: "Automation and release safety",
      rationale:
        "Tracked workflow files can affect credentials, releases, and repository-wide automation.",
    },
    {
      category: "guidance",
      id: "repository-guidance",
      title: "Repository review guidance",
      rationale:
        "Repository guidance is available as untrusted evidence and cannot override the advisor policy.",
    },
  ];
  return definitions
    .map((definition) => ({
      ...definition,
      evidence: evidenceForCategory(census, definition.category).slice(0, 8),
    }))
    .filter((definition) => definition.evidence.length > 0);
}

function evidenceForCategory(census, category) {
  return census.evidence
    .filter((entry) => entry.categories.includes(category))
    .map(({ path, oid }) => ({ path, oid }));
}

function unresolvedQuestions(census) {
  const questions = [];
  if (census.categories.codeowners.length === 0) {
    questions.push("Which paths require specialist or security-owner review?");
  }
  if (census.categories.security.length === 0) {
    questions.push(
      "Where are the repository trust boundaries and sensitive data paths?",
    );
  }
  if (census.categories.tests.length === 0) {
    questions.push(
      "Which validation commands and test suites cover each component?",
    );
  }
  questions.push(
    "Which generated, vendored, migration, deployment, and compatibility paths need special handling?",
  );
  return questions;
}

function generateDiscoveryLock(repository, census) {
  const evidence = census.evidence.map(
    ({
      path,
      oid,
      sha256: digest,
      size,
      categories,
      lineStart,
      lineEnd,
      truncated,
    }) => ({
      path,
      oid,
      sha256: digest,
      size,
      categories,
      lineStart,
      lineEnd,
      truncated,
    }),
  );
  const lockedCensus = {
    counts: census.counts,
    categories: census.categories,
    layoutConcentrations: census.layoutConcentrations,
    excluded: census.excluded,
    evidence,
  };
  return {
    schemaVersion: 1,
    repository: repository.repository,
    trustedRef: repository.trustedRef,
    trustedCommit: repository.trustedHead,
    worktreeCommitAtInstall: repository.worktreeHead,
    censusSha256: sha256(stableJson(lockedCensus)),
    census: lockedCensus,
  };
}

function generateWorkflow(repository) {
  const runnerGroup = reviewRunnerGroup(repository.repository);
  const defaultBranch = repository.defaultBranch || "<default-branch>";
  return `# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Safe default: manual, artifact-only, and read-only. No automatic trigger or
# publishing job is installed.
# Version 0.1 targets GitHub.com. The pinned Node 24 actions require a
# self-hosted Actions runner at version 2.327.1 or newer.
# The named runner group is a required external security boundary. Restrict it
# to this workflow path at refs/heads/<default-branch>; the job-level ref check
# below is defense in depth, not the runner authorization boundary.
# Required selected-workflow entry:
# ${repository.repository}/.github/workflows/nemoclaw-review-advisor.yml@refs/heads/${defaultBranch}
name: NemoClaw Review Advisor

on:
  workflow_dispatch:
    inputs:
      base_sha:
        description: "Trusted base commit SHA"
        required: true
        type: string
      head_sha:
        description: "Pull request head commit SHA"
        required: true
        type: string
      pr_number:
        description: "Pull request number"
        required: true
        type: number

permissions:
  contents: read
  pull-requests: read
  issues: read

concurrency:
  group: nemoclaw-review-advisor-\${{ github.repository_id }}
  cancel-in-progress: false

jobs:
  review:
    if: \${{ github.ref_name == github.event.repository.default_branch }}
    runs-on:
      group: ${runnerGroup}
      labels: [self-hosted, linux, nemoclaw]
    timeout-minutes: 30
    steps:
      - name: Check out trusted workflow source
        uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6.0.3
        with:
          persist-credentials: false
          fetch-depth: 0
          ref: \${{ github.event.repository.default_branch }}
          clean: false

      - name: Clean workspace without deleting advisor state
        run: |
          set -eu
          git reset --hard HEAD
          git clean -ffdx \\
            -e .nemoclaw/review-advisor/.env \\
            -e .nemoclaw/review-advisor/.tmp/ \\
            -e .nemoclaw/review-advisor/.snapshots/ \\
            -e .nemoclaw/review-advisor/memory-export/

      - name: Fetch and bind exact pull request inputs
        env:
          REVIEW_BASE_SHA: \${{ inputs.base_sha }}
          REVIEW_HEAD_SHA: \${{ inputs.head_sha }}
          REVIEW_PR_NUMBER: \${{ inputs.pr_number }}
          REVIEW_REPOSITORY_ID: \${{ github.repository_id }}
          NEMOCLAW_GITHUB_TOKEN: \${{ github.token }}
        run: |
          set -eu
          for git_variable in "\${!GIT_@}"; do
            unset "$git_variable"
          done
          export GIT_CONFIG_NOSYSTEM=1
          export GIT_CONFIG_GLOBAL=/dev/null
          export GIT_TERMINAL_PROMPT=0
          case "$REVIEW_BASE_SHA" in
            *[!0-9a-f]*|'') echo "base_sha must be a lowercase full SHA" >&2; exit 2 ;;
          esac
          case "$REVIEW_HEAD_SHA" in
            *[!0-9a-f]*|'') echo "head_sha must be a lowercase full SHA" >&2; exit 2 ;;
          esac
          test "\${#REVIEW_BASE_SHA}" -eq 40
          test "\${#REVIEW_HEAD_SHA}" -eq 40
          case "$REVIEW_PR_NUMBER" in
            *[!0-9]*|'0'|'') echo "pr_number must be a positive integer" >&2; exit 2 ;;
          esac
          case "$REVIEW_REPOSITORY_ID" in
            *[!0-9]*|'0'|'') echo "repository_id must be a positive integer" >&2; exit 2 ;;
          esac
          test "$(git rev-parse HEAD)" = "$REVIEW_BASE_SHA"
          git check-ref-format "refs/heads/$GITHUB_REF_NAME"
          job_tmp="$RUNNER_TEMP/nemoclaw-review-\${REVIEW_REPOSITORY_ID}-\${GITHUB_RUN_ID}-\${GITHUB_RUN_ATTEMPT}"
          test ! -e "$job_tmp"
          test ! -L "$job_tmp"
          mkdir -m 700 "$job_tmp"
          analysis_repo="$job_tmp/repo"
          test ! -e "$analysis_repo"
          test ! -L "$analysis_repo"
          mkdir -m 700 "$analysis_repo"
          git -C "$analysis_repo" init --quiet
          askpass="$job_tmp/git-askpass"
          (
            set -C
            umask 077
            printf '%s\\n' \\
              '#!/bin/sh' \\
              'case "$1" in' \\
              '  *Username*) printf "%s\\\\n" "x-access-token" ;;' \\
              '  *Password*) printf "%s\\\\n" "$NEMOCLAW_GITHUB_TOKEN" ;;' \\
              '  *) exit 1 ;;' \\
              'esac' >"$askpass"
          )
          test -f "$askpass"
          test ! -L "$askpass"
          chmod 700 "$askpass"
          trap 'rm -f -- "$askpass"' EXIT
          GIT_ASKPASS="$askpass" \\
          git -C "$analysis_repo" \\
            -c protocol.allow=never -c protocol.https.allow=always \\
            fetch --no-tags --no-recurse-submodules \\
            "https://github.com/\${GITHUB_REPOSITORY}.git" \\
            "+refs/heads/\${GITHUB_REF_NAME}:refs/review-advisor/base" \\
            "+refs/pull/\${REVIEW_PR_NUMBER}/head:refs/review-advisor/head"
          test "$(git -C "$analysis_repo" rev-parse 'refs/review-advisor/base^{commit}')" = "$REVIEW_BASE_SHA"
          test "$(git -C "$analysis_repo" rev-parse 'refs/review-advisor/head^{commit}')" = "$REVIEW_HEAD_SHA"
          acceptance_context="$job_tmp/acceptance.json"
          test ! -e "$acceptance_context"
          test ! -L "$acceptance_context"
          .nemoclaw/review-advisor/runtime/scripts/fetch-pr-context.py \\
            --repository "$GITHUB_REPOSITORY" \\
            --pr-number "$REVIEW_PR_NUMBER" \\
            --base "$REVIEW_BASE_SHA" \\
            --head "$REVIEW_HEAD_SHA" \\
            --output "$acceptance_context"
          unset NEMOCLAW_GITHUB_TOKEN

      - name: Run artifact-only review
        id: review
        env:
          REVIEW_BASE_SHA: \${{ inputs.base_sha }}
          REVIEW_HEAD_SHA: \${{ inputs.head_sha }}
          REVIEW_PR_NUMBER: \${{ inputs.pr_number }}
          REVIEW_JOB_TEMP: \${{ runner.temp }}/nemoclaw-review-\${{ github.repository_id }}-\${{ github.run_id }}-\${{ github.run_attempt }}
          REVIEW_ANALYSIS_REPO: \${{ runner.temp }}/nemoclaw-review-\${{ github.repository_id }}-\${{ github.run_id }}-\${{ github.run_attempt }}/repo
          REVIEW_ACCEPTANCE_CONTEXT: \${{ runner.temp }}/nemoclaw-review-\${{ github.repository_id }}-\${{ github.run_id }}-\${{ github.run_attempt }}/acceptance.json
        run: |
          set -eu
          advisor_output="$GITHUB_WORKSPACE/.nemoclaw/review-advisor/output"
          rm -rf -- "$advisor_output"
          test ! -e "$advisor_output"
          test ! -L "$advisor_output"
          .nemoclaw/review-advisor/runtime/scripts/review.sh \\
            --repo "$REVIEW_ANALYSIS_REPO" \\
            --base "$REVIEW_BASE_SHA" \\
            --head "$REVIEW_HEAD_SHA" \\
            --repository "$GITHUB_REPOSITORY" \\
            --pr-number "$REVIEW_PR_NUMBER" \\
            --acceptance-context "$REVIEW_ACCEPTANCE_CONTEXT" \\
            --output "$advisor_output"

      - name: Validate complete review artifact set
        id: artifacts
        if: \${{ steps.review.outcome == 'success' }}
        run: |
          set -eu
          python3 - "$GITHUB_WORKSPACE/.nemoclaw/review-advisor/output" <<'PY'
          import os
          import stat
          import sys
          from pathlib import Path

          output = Path(sys.argv[1])
          info = output.lstat()
          if output.is_symlink() or not stat.S_ISDIR(info.st_mode):
              raise SystemExit("review output is not a regular directory")
          if info.st_uid != os.geteuid():
              raise SystemExit("review output is not owned by the runner uid")
          expected = {"request.json", "review.json", "review.md", "verification.json"}
          entries = {entry.name: entry for entry in output.iterdir()}
          if set(entries) != expected:
              raise SystemExit("review output does not contain the exact artifact set")
          for name, entry in entries.items():
              entry_info = entry.lstat()
              if entry.is_symlink() or not stat.S_ISREG(entry_info.st_mode):
                  raise SystemExit(f"unsafe review artifact: {name}")
              if entry_info.st_uid != os.geteuid() or entry_info.st_size == 0:
                  raise SystemExit(f"invalid review artifact: {name}")
          PY

      - name: Upload review artifacts
        if: \${{ steps.review.outcome == 'success' && steps.artifacts.outcome == 'success' }}
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: nemoclaw-review-\${{ inputs.head_sha }}
          path: .nemoclaw/review-advisor/output/
          if-no-files-found: error
          retention-days: 7

      - name: Remove review data from self-hosted runner
        if: \${{ always() }}
        env:
          REVIEW_REPOSITORY_ID: \${{ github.repository_id }}
        run: |
          set -eu
          job_tmp="$RUNNER_TEMP/nemoclaw-review-\${REVIEW_REPOSITORY_ID}-\${GITHUB_RUN_ID}-\${GITHUB_RUN_ATTEMPT}"
          advisor_output="$GITHUB_WORKSPACE/.nemoclaw/review-advisor/output"
          rm -rf -- "$job_tmp"
          rm -rf -- "$advisor_output"
  `;
}

function reviewRunnerGroup(repositoryIdentity) {
  const repositoryName = repositoryIdentity.split("/").at(-1) ?? "repository";
  const safeName = slug(repositoryName).slice(0, 32) || "repository";
  return `nemoclaw-review-advisor-${safeName}-${sha256(repositoryIdentity).slice(0, 12)}`;
}

function slug(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);
}

function addText(files, relativePath, content, mode = 0o644) {
  files.set(relativePath, {
    content: Buffer.from(content, "utf8"),
    mode,
    source: "generated",
    sha256: sha256(content),
  });
}
