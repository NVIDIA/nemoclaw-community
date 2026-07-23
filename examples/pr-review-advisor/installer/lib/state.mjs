// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs";
import path from "node:path";
import {
  GENERATED_WORKFLOW_PATH,
  INSTALL_DIR,
  OVERRIDE_PROFILE_PATH,
  PACKAGE_NAME,
  PACKAGE_VERSION,
  STATE_PATH,
  STATE_SCHEMA_VERSION,
} from "./constants.mjs";
import {
  CliError,
  compareStrings,
  normalizeRepoRelative,
  sha256,
  stableJson,
} from "./util.mjs";
import {
  normalizeStoredReviewScope,
  reviewScopeDigest,
  reviewScopeForJson,
} from "./scope.mjs";

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const GIT_SHA_PATTERN = /^[0-9a-f]{40,64}$/;
const REPOSITORY_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const VERSION_PATTERN = /^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$/;

export function loadState(root) {
  const statePath = path.join(root, STATE_PATH);
  if (!fs.existsSync(statePath)) {
    return null;
  }
  const stat = fs.lstatSync(statePath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new CliError(`${STATE_PATH} is not a regular file`);
  }
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(statePath, "utf8"));
  } catch (error) {
    throw new CliError(`cannot parse ${STATE_PATH}: ${error.message}`);
  }
  validateState(parsed);
  return parsed;
}

export function buildState(
  repository,
  desiredFiles,
  reviewScope,
  preserved = [],
) {
  const ownedFiles = {};
  for (const [relativePath, file] of [...desiredFiles.entries()].sort(
    ([left], [right]) => compareStrings(left, right),
  )) {
    ownedFiles[relativePath] = {
      sha256: file.sha256 ?? sha256(file.content),
      mode: file.mode,
      source: file.source,
    };
  }
  return {
    schemaVersion: STATE_SCHEMA_VERSION,
    package: {
      name: PACKAGE_NAME,
      version: PACKAGE_VERSION,
    },
    repository: {
      identity: repository.repository,
      trustedRef: repository.trustedRef,
      trustedCommit: repository.trustedHead,
      worktreeCommitAtInstall: repository.worktreeHead,
    },
    reviewScope: reviewScopeForJson(reviewScope),
    scopeDigest: reviewScopeDigest(reviewScope),
    configRoot: INSTALL_DIR,
    publicationEnabled: false,
    ownedFiles,
    preservedModifiedFiles: [...preserved].sort(),
  };
}

export function stateFile(state) {
  const content = Buffer.from(stableJson(state), "utf8");
  return {
    content,
    mode: 0o644,
    source: "installer-state",
    sha256: sha256(content),
  };
}

function validateState(state) {
  exactObject(state, "install state", [
    "configRoot",
    "ownedFiles",
    "package",
    "preservedModifiedFiles",
    "publicationEnabled",
    "repository",
    "reviewScope",
    "scopeDigest",
    "schemaVersion",
  ]);
  if (state.schemaVersion !== STATE_SCHEMA_VERSION) {
    throw new CliError(`${STATE_PATH} has an unsupported schema version`);
  }
  if (state.configRoot !== INSTALL_DIR || state.publicationEnabled !== false) {
    throw new CliError(`${STATE_PATH} has unsafe installation metadata`);
  }
  const normalizedReviewScope = normalizeStoredReviewScope(state.reviewScope);
  if (
    typeof state.scopeDigest !== "string" ||
    !SHA256_PATTERN.test(state.scopeDigest) ||
    state.scopeDigest !== reviewScopeDigest(normalizedReviewScope)
  ) {
    throw new CliError(`${STATE_PATH} has an invalid scope digest`);
  }

  exactObject(state.package, "install state package", ["name", "version"]);
  if (
    state.package.name !== PACKAGE_NAME ||
    typeof state.package.version !== "string" ||
    !VERSION_PATTERN.test(state.package.version)
  ) {
    throw new CliError(`${STATE_PATH} has invalid package metadata`);
  }

  exactObject(state.repository, "install state repository", [
    "identity",
    "trustedCommit",
    "trustedRef",
    "worktreeCommitAtInstall",
  ]);
  if (
    typeof state.repository.identity !== "string" ||
    !REPOSITORY_PATTERN.test(state.repository.identity) ||
    typeof state.repository.trustedRef !== "string" ||
    state.repository.trustedRef.length === 0 ||
    state.repository.trustedRef.length > 512 ||
    !GIT_SHA_PATTERN.test(state.repository.trustedCommit) ||
    !GIT_SHA_PATTERN.test(state.repository.worktreeCommitAtInstall)
  ) {
    throw new CliError(`${STATE_PATH} has invalid repository metadata`);
  }

  if (!isPlainObject(state.ownedFiles)) {
    throw new CliError(`${STATE_PATH} ownedFiles must be an object`);
  }
  const ownedEntries = Object.entries(state.ownedFiles);
  if (ownedEntries.length > 10_000) {
    throw new CliError(`${STATE_PATH} owns too many files`);
  }
  for (const [relativePath, owned] of ownedEntries) {
    validateOwnedPath(relativePath);
    exactObject(owned, `owned file ${relativePath}`, [
      "mode",
      "sha256",
      "source",
    ]);
    if (
      typeof owned.sha256 !== "string" ||
      !SHA256_PATTERN.test(owned.sha256) ||
      ![0o644, 0o755].includes(owned.mode) ||
      typeof owned.source !== "string" ||
      owned.source.length === 0 ||
      owned.source.length > 4_096 ||
      /[\u0000-\u001f\u007f]/u.test(owned.source)
    ) {
      throw new CliError(
        `${STATE_PATH} has invalid metadata for ${relativePath}`,
      );
    }
  }

  if (
    !Array.isArray(state.preservedModifiedFiles) ||
    state.preservedModifiedFiles.length > 10_000
  ) {
    throw new CliError(`${STATE_PATH} preservedModifiedFiles must be an array`);
  }
  const seenPreserved = new Set();
  for (const relativePath of state.preservedModifiedFiles) {
    validateOwnedPath(relativePath);
    if (seenPreserved.has(relativePath)) {
      throw new CliError(
        `${STATE_PATH} repeats preserved path ${relativePath}`,
      );
    }
    seenPreserved.add(relativePath);
  }
}

function validateOwnedPath(relativePath) {
  const normalized = normalizeRepoRelative(relativePath);
  if (
    normalized === STATE_PATH ||
    normalized === OVERRIDE_PROFILE_PATH ||
    (normalized !== GENERATED_WORKFLOW_PATH &&
      !normalized.startsWith(`${INSTALL_DIR}/`))
  ) {
    throw new CliError(
      `${STATE_PATH} contains an out-of-scope owned path: ${relativePath}`,
    );
  }
}

function exactObject(value, name, expectedKeys) {
  if (!isPlainObject(value)) {
    throw new CliError(`${name} must be an object`);
  }
  const actual = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    throw new CliError(`${name} has unexpected or missing fields`);
  }
}

function isPlainObject(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}
