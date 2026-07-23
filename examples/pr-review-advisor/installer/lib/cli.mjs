// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import path from "node:path";
import readline from "node:readline/promises";
import { collectRuntimeAssets } from "./assets.mjs";
import { buildCensus } from "./census.mjs";
import {
  OVERRIDE_PROFILE_PATH,
  PACKAGE_NAME,
  PACKAGE_VERSION,
  STATE_PATH,
} from "./constants.mjs";
import {
  generateOverrideProfile,
  generateRepositoryFiles,
} from "./generate.mjs";
import {
  isAncestor,
  listCommittedTree,
  readCommittedPathBlob,
  resolveGitRoot,
  resolveRepository,
} from "./git.mjs";
import {
  bindReviewScopeToTree,
  normalizeReviewScope,
  repositoryReviewScope,
  reviewScopeDigest,
  reviewScopeForJson,
  reviewScopesEqual,
} from "./scope.mjs";
import { buildState, loadState, stateFile } from "./state.mjs";
import {
  acquireInstallerLock,
  applyTransaction,
  inspectFile,
  planInstall,
  planRemoval,
  renderPlan,
} from "./transaction.mjs";
import { CliError, compareStrings, sha256 } from "./util.mjs";

const COMMANDS = new Set([
  "activate-profile",
  "init",
  "dry-run",
  "check",
  "refresh",
  "remove",
]);
const SCOPE_COMMANDS = new Set(["init", "dry-run", "check", "refresh"]);

export async function runCli(argv, io) {
  try {
    enforceNodeVersion();
    const options = parseArguments(argv, io.cwd);
    if (options.help) {
      io.stdout.write(usage());
      return 0;
    }
    if (!COMMANDS.has(options.command)) {
      throw new CliError(
        `unknown command: ${options.command}\n\n${usage()}`,
        2,
      );
    }
    if (options.command === "check") {
      return runCheck(options, io);
    }
    if (options.command === "activate-profile") {
      return await runActivateProfile(options, io);
    }
    if (options.command === "remove") {
      return await runRemove(options, io);
    }
    return await runInstall(options, io);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "unexpected installer error";
    io.stderr.write(`error: ${message}\n`);
    return error instanceof CliError ? error.exitCode : 1;
  }
}

async function runInstall(options, io) {
  const { root } = resolveGitRoot(options.target);
  const releaseLock = options.dryRun ? null : acquireInstallerLock(root);
  try {
    const previousState = loadState(root);
    if (options.command === "refresh" && !previousState) {
      throw new CliError("review advisor is not installed; run init first", 2);
    }
    const repository = resolveRepository(root, {
      trustedRef: options.trustedRef ?? previousState?.repository.trustedRef,
    });
    verifyStateRepository(previousState, repository);

    const reviewScope = resolveReviewScope(options, previousState);
    const previousUnpopulated =
      previousState && reviewScopesEqual(reviewScope, previousState.reviewScope)
        ? previousState.reviewScope.unpopulatedRoots
        : [];
    const allowedUnpopulatedRoots = options.allowUnpopulatedScope
      ? reviewScope.roots
      : previousUnpopulated;
    const census = buildCensus(repository, reviewScope, {
      allowedUnpopulatedRoots,
    });
    const resolvedReviewScope = {
      ...reviewScope,
      unpopulatedRoots: census.reviewScope.unpopulatedRoots,
    };
    const generated = generateRepositoryFiles(
      repository,
      census,
      resolvedReviewScope,
    );
    const { assets } = collectRuntimeAssets(io.assetRoot);
    const desired = new Map([...generated, ...assets]);
    const nextState = buildState(repository, desired, resolvedReviewScope);
    desired.set(STATE_PATH, stateFile(nextState));

    const planningState = previousState
      ? {
          ...previousState,
          ownedFiles: {
            ...previousState.ownedFiles,
            [STATE_PATH]: {
              sha256: inspectFile(repository.root, STATE_PATH).sha256,
              mode: 0o644,
              source: "installer-state",
            },
          },
        }
      : null;
    const overrideContent = Buffer.from(
      generateOverrideProfile(
        generated
          .get(".nemoclaw/review-advisor/profile.generated.yaml")
          .content.toString("utf8"),
      ),
      "utf8",
    );
    const plan = planInstall(repository.root, desired, planningState, {
      relativePath: OVERRIDE_PROFILE_PATH,
      content: overrideContent,
      mode: 0o644,
      source: "maintainer-owned",
      sha256: sha256(overrideContent),
    });

    if (plan.conflicts.length > 0) {
      reportConflicts(plan.conflicts, io);
      return 1;
    }

    const diff = renderPlan(plan.operations);
    if (options.json) {
      writeJson(io.stdout, {
        command: options.command,
        dryRun: options.dryRun,
        repository: repository.repository,
        trustedRef: repository.trustedRef,
        trustedCommit: repository.trustedHead,
        worktreeCommit: repository.worktreeHead,
        reviewScope: reviewScopeForJson(resolvedReviewScope),
        scopeDigest: reviewScopeDigest(resolvedReviewScope),
        census: census.counts,
        changes: plan.operations.map(summarizeOperation),
        diff,
      });
    } else {
      io.stdout.write(
        `${PACKAGE_NAME} ${PACKAGE_VERSION}\n` +
          `Repository: ${repository.repository}\n` +
          `Trusted tree: ${repository.trustedRef} -> ${repository.trustedHead}\n` +
          `Working-tree commit: ${repository.worktreeHead}\n` +
          `Discovery: ${census.counts.regularFiles} regular files, ` +
          `${census.counts.evidenceFiles} bounded evidence files, ` +
          `${census.counts.excludedEntries} exclusions\n\n` +
          diff,
      );
      reportReviewScope(
        resolvedReviewScope,
        previousState?.reviewScope ?? null,
        io,
      );
    }

    if (options.dryRun) {
      if (!options.json) {
        io.stdout.write("Dry run complete; no files were written.\n");
      }
      return 0;
    }
    if (plan.operations.length === 0) {
      if (!options.json) {
        io.stdout.write("Installation is already up to date.\n");
      }
      return 0;
    }

    const approved = await requireApproval(options, io, plan.operations.length);
    if (!approved) {
      io.stderr.write("Cancelled; no files were written.\n");
      return 2;
    }
    applyTransaction(repository.root, plan.operations);
    if (!options.json) {
      io.stdout.write(
        `Applied ${plan.operations.length} file change(s). ` +
          "Review publication remains disabled.\n",
      );
      if (options.command === "refresh") {
        const active = inspectFile(repository.root, OVERRIDE_PROFILE_PATH);
        if (profileSourceCommit(active.content) !== repository.trustedHead) {
          io.stdout.write(
            "The generated candidate reflects the current trusted tree. The active " +
              "profile keeps its older ancestor calibration provenance and remains " +
              "usable once committed. Review the diff, then run " +
              "`nemoclaw-review-advisor activate-profile` if you want to adopt the " +
              "new calibration.\n",
          );
        }
      }
    }
    return 0;
  } finally {
    releaseLock?.();
  }
}

function runCheck(options, io) {
  const { root } = resolveGitRoot(options.target);
  const state = loadState(root);
  if (!state) {
    throw new CliError("review advisor is not installed", 2);
  }
  const repository = resolveRepository(root, {
    trustedRef: options.trustedRef ?? state.repository.trustedRef,
  });
  verifyStateRepository(state, repository);
  const reviewScope = resolveReviewScope(options, state);
  if (!reviewScopesEqual(reviewScope, state.reviewScope)) {
    throw new CliError(
      "requested review scope does not match the installed scope; " +
        "run refresh with the complete desired scope",
      2,
    );
  }
  const boundScope = bindReviewScopeToTree(
    reviewScope,
    listCommittedTree(repository),
    repository.trustedRef,
    state.reviewScope.unpopulatedRoots,
  );

  const findings = [];
  const notices = [];
  for (const root of boundScope.rootDescriptors) {
    if (root.kind === "unpopulated") {
      notices.push({
        path: root.path,
        status: "scope-root-unpopulated",
      });
    } else if (state.reviewScope.unpopulatedRoots.includes(root.path)) {
      notices.push({
        path: root.path,
        status: "scope-root-now-populated-run-refresh",
      });
    }
  }
  for (const [relativePath, owned] of Object.entries(state.ownedFiles).sort(
    ([left], [right]) => compareStrings(left, right),
  )) {
    const current = inspectFile(root, relativePath);
    if (!current.exists) {
      findings.push({ path: relativePath, status: "missing" });
    } else if (current.sha256 !== owned.sha256) {
      findings.push({ path: relativePath, status: "modified" });
    } else if (current.mode !== owned.mode) {
      findings.push({
        path: relativePath,
        status: "mode-drift",
        installed: owned.mode,
        current: current.mode,
      });
    }
  }
  const override = inspectFile(root, OVERRIDE_PROFILE_PATH);
  const committedProfile = readCommittedPathBlob(
    root,
    repository.trustedHead,
    OVERRIDE_PROFILE_PATH,
  );
  if (!committedProfile) {
    findings.push({
      path: OVERRIDE_PROFILE_PATH,
      status: "active-profile-not-committed-at-trusted-base",
    });
  } else if (!committedProfile.content) {
    findings.push({
      path: OVERRIDE_PROFILE_PATH,
      status: "active-profile-not-regular-blob",
    });
  }
  if (!override.exists) {
    findings.push({ path: OVERRIDE_PROFILE_PATH, status: "missing-override" });
  } else if (
    committedProfile?.content &&
    !override.content.equals(committedProfile.content)
  ) {
    findings.push({
      path: OVERRIDE_PROFILE_PATH,
      status: "active-profile-working-tree-differs-from-trusted-base",
    });
  }
  if (committedProfile?.content) {
    const activeCommit = profileSourceCommit(committedProfile.content);
    if (!activeCommit) {
      findings.push({
        path: OVERRIDE_PROFILE_PATH,
        status: "active-profile-invalid-metadata",
      });
    } else if (!isAncestor(root, activeCommit, repository.trustedHead)) {
      findings.push({
        path: OVERRIDE_PROFILE_PATH,
        status: "active-profile-unrelated-to-trusted-base",
        installed: activeCommit,
        current: repository.trustedHead,
      });
    } else if (activeCommit !== repository.trustedHead) {
      notices.push({
        path: OVERRIDE_PROFILE_PATH,
        status: "active-profile-calibrated-through",
        installed: activeCommit,
        current: repository.trustedHead,
      });
    }
  }
  if (repository.trustedHead !== state.repository.trustedCommit) {
    const discovery = {
      path: state.repository.trustedRef,
      installed: state.repository.trustedCommit,
      current: repository.trustedHead,
    };
    if (
      isAncestor(root, state.repository.trustedCommit, repository.trustedHead)
    ) {
      notices.push({
        ...discovery,
        status: "discovery-candidate-behind-trusted-tip",
      });
    } else {
      findings.push({
        ...discovery,
        status: "discovery-history-mismatch",
      });
    }
  }

  if (options.json) {
    writeJson(io.stdout, {
      command: "check",
      ok: findings.length === 0,
      repository: repository.repository,
      reviewScope: reviewScopeForJson(state.reviewScope),
      scopeDigest: state.scopeDigest,
      findings,
      notices,
    });
  } else {
    if (findings.length === 0) {
      io.stdout.write(
        `OK: ${Object.keys(state.ownedFiles).length} installer-owned files match; ` +
          `trusted base is ${repository.trustedHead}.\n`,
      );
    } else {
      io.stderr.write("Review Advisor installation needs attention:\n");
      for (const finding of findings) {
        io.stderr.write(`  ${finding.status}: ${finding.path}\n`);
      }
    }
    if (notices.length > 0) {
      io.stdout.write("Installation notices:\n");
      for (const notice of notices) {
        const transition =
          notice.installed && notice.current
            ? ` (${notice.installed} -> ${notice.current})`
            : "";
        io.stdout.write(`  ${notice.status}: ${notice.path}${transition}\n`);
      }
    }
  }
  return findings.length === 0 ? 0 : 1;
}

async function runActivateProfile(options, io) {
  const { root } = resolveGitRoot(options.target);
  const releaseLock = options.dryRun ? null : acquireInstallerLock(root);
  try {
    const state = loadState(root);
    if (!state) {
      throw new CliError("review advisor is not installed", 2);
    }
    const repository = resolveRepository(root, {
      trustedRef: options.trustedRef ?? state.repository.trustedRef,
    });
    verifyStateRepository(state, repository);

    const candidatePath = ".nemoclaw/review-advisor/profile.generated.yaml";
    const candidate = inspectFile(root, candidatePath);
    const recordedCandidate = state.ownedFiles[candidatePath];
    if (!candidate.exists || !recordedCandidate) {
      throw new CliError("generated profile candidate is missing; run refresh");
    }
    if (candidate.sha256 !== recordedCandidate.sha256) {
      throw new CliError(
        "generated profile candidate was modified outside the installer; run refresh",
      );
    }
    if (profileSourceCommit(candidate.content) !== repository.trustedHead) {
      throw new CliError(
        "generated profile candidate does not match the trusted branch head; run refresh",
      );
    }

    const active = inspectFile(root, OVERRIDE_PROFILE_PATH);
    const promoted = Buffer.from(
      generateOverrideProfile(candidate.content.toString("utf8")),
      "utf8",
    );
    const operations =
      active.exists && active.content.equals(promoted)
        ? []
        : [
            {
              action: "write-unowned",
              relativePath: OVERRIDE_PROFILE_PATH,
              before: active.exists ? active.content : null,
              beforeMode: active.exists ? active.mode : null,
              after: promoted,
              mode: 0o644,
            },
          ];
    const diff = renderPlan(operations);
    if (options.json) {
      writeJson(io.stdout, {
        command: "activate-profile",
        dryRun: options.dryRun,
        trustedCommit: repository.trustedHead,
        changes: operations.map(summarizeOperation),
        diff,
      });
    } else {
      io.stdout.write(
        `Promoting candidate for trusted commit ${repository.trustedHead}.\n\n${diff}`,
      );
    }
    if (options.dryRun || operations.length === 0) {
      return 0;
    }
    const approved = await requireApproval(options, io, operations.length);
    if (!approved) {
      io.stderr.write("Cancelled; the active profile was not changed.\n");
      return 2;
    }
    applyTransaction(root, operations);
    if (!options.json) {
      io.stdout.write(
        "Activated the generated profile. It remains maintainer-owned and is " +
          "not included in installer removal.\n",
      );
    }
    return 0;
  } finally {
    releaseLock?.();
  }
}

async function runRemove(options, io) {
  const { root } = resolveGitRoot(options.target);
  const releaseLock = options.dryRun ? null : acquireInstallerLock(root);
  try {
    const state = loadState(root);
    if (!state) {
      if (!options.json) {
        io.stdout.write(
          "Review Advisor is not installed; nothing to remove.\n",
        );
      }
      return 0;
    }
    const plan = planRemoval(root, state, STATE_PATH);
    const diff = renderPlan(plan.operations);
    if (options.json) {
      writeJson(io.stdout, {
        command: "remove",
        dryRun: options.dryRun,
        changes: plan.operations.map(summarizeOperation),
        preserved: plan.preserved,
        diff,
      });
    } else {
      io.stdout.write(diff);
      if (plan.preserved.length > 0) {
        io.stdout.write(
          "Preserving locally modified installer files:\n" +
            plan.preserved.map((item) => `  ${item}\n`).join(""),
        );
      }
      io.stdout.write(
        `Preserving maintainer-owned ${OVERRIDE_PROFILE_PATH} and Hermes memory.\n`,
      );
    }
    if (options.dryRun || plan.operations.length === 0) {
      return 0;
    }
    const approved = await requireApproval(options, io, plan.operations.length);
    if (!approved) {
      io.stderr.write("Cancelled; no files were removed.\n");
      return 2;
    }
    applyTransaction(root, plan.operations);
    if (!options.json) {
      io.stdout.write(
        `Removed ${plan.operations.length} unmodified file(s).\n`,
      );
    }
    return 0;
  } finally {
    releaseLock?.();
  }
}

function parseArguments(argv, cwd) {
  if (argv.length === 0) {
    return { command: "", target: cwd };
  }
  if (argv[0] === "--help" || argv[0] === "-h") {
    return { command: "init", target: cwd, help: true };
  }
  const options = {
    command: argv[0],
    requestedCommand: argv[0],
    target: cwd,
    trustedRef: undefined,
    scopeRoots: [],
    supportPaths: [],
    scopeOptionsProvided: false,
    allowUnpopulatedScope: false,
    yes: false,
    json: false,
    dryRun: argv[0] === "dry-run",
    help: false,
  };
  let targetSeen = false;
  for (let index = 1; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      options.help = true;
    } else if (argument === "--yes" || argument === "-y") {
      options.yes = true;
    } else if (argument === "--json") {
      options.json = true;
    } else if (argument === "--dry-run") {
      options.dryRun = true;
    } else if (argument === "--trusted-ref") {
      index += 1;
      if (!argv[index]) {
        throw new CliError("--trusted-ref requires a value", 2);
      }
      options.trustedRef = argv[index];
    } else if (argument.startsWith("--trusted-ref=")) {
      options.trustedRef = argument.slice("--trusted-ref=".length);
    } else if (argument === "--scope-root") {
      index += 1;
      if (!argv[index]) {
        throw new CliError("--scope-root requires a value", 2);
      }
      options.scopeRoots.push(argv[index]);
      options.scopeOptionsProvided = true;
    } else if (argument.startsWith("--scope-root=")) {
      const value = argument.slice("--scope-root=".length);
      if (!value) {
        throw new CliError("--scope-root requires a value", 2);
      }
      options.scopeRoots.push(value);
      options.scopeOptionsProvided = true;
    } else if (argument === "--support-path") {
      index += 1;
      if (!argv[index]) {
        throw new CliError("--support-path requires a value", 2);
      }
      options.supportPaths.push(argv[index]);
      options.scopeOptionsProvided = true;
    } else if (argument.startsWith("--support-path=")) {
      const value = argument.slice("--support-path=".length);
      if (!value) {
        throw new CliError("--support-path requires a value", 2);
      }
      options.supportPaths.push(value);
      options.scopeOptionsProvided = true;
    } else if (argument === "--allow-unpopulated-scope") {
      options.allowUnpopulatedScope = true;
    } else if (argument === "--repo") {
      index += 1;
      if (!argv[index]) {
        throw new CliError("--repo requires a path", 2);
      }
      if (targetSeen) {
        throw new CliError("repository path was provided more than once", 2);
      }
      options.target = path.resolve(cwd, argv[index]);
      targetSeen = true;
    } else if (argument.startsWith("-")) {
      throw new CliError(`unknown option: ${argument}`, 2);
    } else if (!targetSeen) {
      options.target = path.resolve(cwd, argument);
      targetSeen = true;
    } else {
      throw new CliError(`unexpected argument: ${argument}`, 2);
    }
  }
  if (
    (options.scopeOptionsProvided || options.allowUnpopulatedScope) &&
    !SCOPE_COMMANDS.has(options.requestedCommand)
  ) {
    throw new CliError(
      `scope options are not supported by ${options.requestedCommand}`,
      2,
    );
  }
  if (
    options.allowUnpopulatedScope &&
    !["init", "dry-run"].includes(options.requestedCommand)
  ) {
    throw new CliError(
      "--allow-unpopulated-scope is supported only by init and dry-run",
      2,
    );
  }
  if (options.scopeOptionsProvided) {
    options.reviewScope = normalizeReviewScope(
      options.scopeRoots,
      options.supportPaths,
    );
  }
  if (
    options.allowUnpopulatedScope &&
    (!options.reviewScope || options.reviewScope.mode !== "scoped")
  ) {
    throw new CliError(
      "--allow-unpopulated-scope requires at least one --scope-root",
      2,
    );
  }
  if (options.command === "dry-run") {
    options.command = "init";
  }
  return options;
}

async function requireApproval(options, io, count) {
  if (options.yes) {
    return true;
  }
  if (options.json || !io.stdin.isTTY || !io.stdout.isTTY) {
    throw new CliError(
      "approval required; rerun with --yes after reviewing the proposed diff",
      2,
    );
  }
  const prompt = readline.createInterface({
    input: io.stdin,
    output: io.stdout,
  });
  try {
    const answer = await prompt.question(
      `Apply ${count} repository file change(s)? [y/N] `,
    );
    return /^y(?:es)?$/i.test(answer.trim());
  } finally {
    prompt.close();
  }
}

function verifyStateRepository(state, repository) {
  if (!state) {
    return;
  }
  if (state.repository.identity !== repository.repository) {
    throw new CliError(
      "install state belongs to a different repository identity",
    );
  }
}

function resolveReviewScope(options, previousState) {
  if (options.scopeOptionsProvided) {
    return options.reviewScope;
  }
  return previousState?.reviewScope ?? repositoryReviewScope();
}

function reportReviewScope(reviewScope, previousScope, io) {
  if (reviewScope.mode !== "scoped") {
    return;
  }
  io.stdout.write(
    `Review scope roots: ${reviewScope.roots.join(", ")}\n` +
      `Support paths: ${
        reviewScope.supportPaths.length > 0
          ? reviewScope.supportPaths.join(", ")
          : "(none)"
      }\n`,
  );
  if (reviewScope.unpopulatedRoots.length > 0) {
    io.stdout.write(
      "Unpopulated scope roots at the trusted tree (working-tree bytes were " +
        `not read): ${reviewScope.unpopulatedRoots.join(", ")}\n`,
    );
  }
  const newlyPopulated = (previousScope?.unpopulatedRoots ?? []).filter(
    (root) => !reviewScope.unpopulatedRoots.includes(root),
  );
  if (newlyPopulated.length > 0) {
    io.stdout.write(
      `Trusted scope roots now populated: ${newlyPopulated.join(", ")}\n`,
    );
  }
}

function profileSourceCommit(content) {
  if (!content) {
    return "";
  }
  const matches = [
    ...content
      .toString("utf8")
      .matchAll(
        /^ {2}source_commit:\s*["']?([0-9a-f]{40,64})["']?\s*(?:#.*)?$/gm,
      ),
  ];
  return matches.length === 1 ? matches[0][1] : "";
}

function reportConflicts(conflicts, io) {
  io.stderr.write(
    "Refusing to overwrite files outside the recorded installer hashes:\n",
  );
  for (const conflict of conflicts) {
    io.stderr.write(`  ${conflict}\n`);
  }
}

function summarizeOperation(operation) {
  return {
    action: operation.action,
    path: operation.relativePath,
  };
}

function writeJson(output, value) {
  output.write(`${JSON.stringify(value, null, 2)}\n`);
}

function enforceNodeVersion() {
  if (!isSupportedNodeVersion(process.versions.node)) {
    throw new CliError("Node.js 22.19.0 or newer is required", 2);
  }
}

export function isSupportedNodeVersion(version) {
  const match = /^([0-9]+)\.([0-9]+)\.([0-9]+)$/.exec(String(version));
  if (!match) {
    return false;
  }
  const actual = match.slice(1).map((part) => Number.parseInt(part, 10));
  const minimum = [22, 19, 0];
  for (let index = 0; index < minimum.length; index += 1) {
    if (actual[index] > minimum[index]) {
      return true;
    }
    if (actual[index] < minimum[index]) {
      return false;
    }
  }
  return true;
}

function usage() {
  return `Usage:
  nemoclaw-review-advisor init [path] [--trusted-ref REF] [--scope-root PATH ...]
                                  [--support-path PATH ...]
                                  [--allow-unpopulated-scope] [--yes] [--dry-run]
  nemoclaw-review-advisor dry-run [path] [--trusted-ref REF]
                                     [--scope-root PATH ...]
                                     [--support-path PATH ...]
                                     [--allow-unpopulated-scope]
  nemoclaw-review-advisor check [path] [--trusted-ref REF]
                                   [--scope-root PATH ...]
                                   [--support-path PATH ...] [--json]
  nemoclaw-review-advisor refresh [path] [--trusted-ref REF]
                                     [--scope-root PATH ...]
                                     [--support-path PATH ...]
                                     [--yes] [--dry-run]
  nemoclaw-review-advisor activate-profile [path] [--yes] [--dry-run]
  nemoclaw-review-advisor remove [path] [--yes] [--dry-run]

Discovery reads only regular blobs from the trusted committed tree. If
refs/remotes/origin/HEAD is unavailable, --trusted-ref is required. Mutating
commands print a complete proposed diff and require confirmation. Publication
is disabled in every generated default. Repeated scope options replace the
complete installed scope; omit them to reuse it. --allow-unpopulated-scope is
an explicit init/dry-run bootstrap for scope roots absent from the trusted tree.
`;
}
