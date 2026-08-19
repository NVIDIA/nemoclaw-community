// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  CliError,
  compareStrings,
  normalizeRepoRelative,
  sha256,
} from "./util.mjs";

const MAX_SCOPE_PATHS = 256;
const MAX_SCOPE_PATH_BYTES = 4_096;
const REGULAR_BLOB_MODES = new Set(["100644", "100755"]);
const PORTABLE_COLLATOR = new Intl.Collator("und", {
  usage: "search",
  sensitivity: "base",
});

export function repositoryReviewScope() {
  return {
    mode: "repository",
    roots: [],
    supportPaths: [],
    unpopulatedRoots: [],
  };
}

export function normalizeReviewScope(roots = [], supportPaths = []) {
  const normalizedRoots = normalizePathList(roots, "--scope-root");
  const normalizedSupportPaths = normalizePathList(
    supportPaths,
    "--support-path",
  );
  if (normalizedRoots.length === 0) {
    if (normalizedSupportPaths.length > 0) {
      throw new CliError(
        "--support-path requires at least one --scope-root",
        2,
      );
    }
    return repositoryReviewScope();
  }

  rejectOverlaps(normalizedRoots, "--scope-root");
  rejectOverlaps(normalizedSupportPaths, "--support-path");
  for (const supportPath of normalizedSupportPaths) {
    for (const root of normalizedRoots) {
      if (pathsOverlap(supportPath, root)) {
        throw new CliError(
          `--support-path ${JSON.stringify(supportPath)} overlaps ` +
            `--scope-root ${JSON.stringify(root)}`,
          2,
        );
      }
    }
  }

  return {
    mode: "scoped",
    roots: normalizedRoots,
    supportPaths: normalizedSupportPaths,
    unpopulatedRoots: [],
  };
}

export function normalizeStoredReviewScope(value) {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    throw new CliError("install state reviewScope must be an object");
  }
  const keys = Object.keys(value).sort();
  const expected = ["mode", "roots", "supportPaths", "unpopulatedRoots"];
  if (
    keys.length !== expected.length ||
    keys.some((key, index) => key !== expected[index])
  ) {
    throw new CliError(
      "install state reviewScope has unexpected or missing fields",
    );
  }
  if (
    !Array.isArray(value.roots) ||
    !Array.isArray(value.supportPaths) ||
    !Array.isArray(value.unpopulatedRoots)
  ) {
    throw new CliError("install state reviewScope paths must be arrays");
  }
  const normalized = normalizeReviewScope(value.roots, value.supportPaths);
  const unpopulatedRoots = normalizePathList(
    value.unpopulatedRoots,
    "install state unpopulated root",
  );
  if (
    value.mode !== normalized.mode ||
    !sameStrings(value.roots, normalized.roots) ||
    !sameStrings(value.supportPaths, normalized.supportPaths) ||
    !sameStrings(value.unpopulatedRoots, unpopulatedRoots) ||
    unpopulatedRoots.some((root) => !normalized.roots.includes(root))
  ) {
    throw new CliError("install state reviewScope is not canonical");
  }
  return {
    ...normalized,
    unpopulatedRoots,
  };
}

export function bindReviewScopeToTree(
  reviewScope,
  tree,
  trustedRef,
  allowedUnpopulatedRoots = reviewScope.unpopulatedRoots ?? [],
) {
  if (reviewScope.mode === "repository") {
    return {
      ...repositoryReviewScope(),
      rootDescriptors: [],
      supportDescriptors: [],
    };
  }
  const rootDescriptors = reviewScope.roots.map((configuredPath) =>
    describeSelection(
      configuredPath,
      tree,
      "--scope-root",
      trustedRef,
      allowedUnpopulatedRoots.includes(configuredPath),
    ),
  );
  const supportDescriptors = reviewScope.supportPaths.map((configuredPath) =>
    describeSelection(configuredPath, tree, "--support-path", trustedRef),
  );
  return {
    mode: "scoped",
    roots: [...reviewScope.roots],
    supportPaths: [...reviewScope.supportPaths],
    unpopulatedRoots: rootDescriptors
      .filter((descriptor) => descriptor.kind === "unpopulated")
      .map((descriptor) => descriptor.path),
    rootDescriptors,
    supportDescriptors,
  };
}

export function reviewScopeRole(filePath, reviewScope) {
  if (reviewScope.mode === "repository") {
    return "scope";
  }
  if (reviewScope.roots.some((root) => pathIsWithin(filePath, root))) {
    return "scope";
  }
  if (
    reviewScope.supportPaths.some((supportPath) =>
      pathIsWithin(filePath, supportPath),
    )
  ) {
    return "support";
  }
  return "";
}

export function reviewScopesEqual(left, right) {
  return (
    left.mode === right.mode &&
    sameStrings(left.roots, right.roots) &&
    sameStrings(left.supportPaths, right.supportPaths)
  );
}

export function reviewScopeForJson(reviewScope) {
  return {
    mode: reviewScope.mode,
    roots: [...reviewScope.roots],
    supportPaths: [...reviewScope.supportPaths],
    unpopulatedRoots: [...(reviewScope.unpopulatedRoots ?? [])],
  };
}

export function reviewScopeDigest(reviewScope) {
  return sha256(
    JSON.stringify({
      mode: reviewScope.mode,
      roots: reviewScope.roots,
      support_paths: reviewScope.supportPaths,
    }),
  );
}

function normalizePathList(values, optionName) {
  if (!Array.isArray(values)) {
    throw new CliError(`${optionName} values must be an array`, 2);
  }
  if (values.length > MAX_SCOPE_PATHS) {
    throw new CliError(
      `${optionName} may be repeated at most ${MAX_SCOPE_PATHS} times`,
      2,
    );
  }
  const unique = new Set();
  const portable = [];
  for (const value of values) {
    if (
      typeof value !== "string" ||
      Buffer.byteLength(value, "utf8") > MAX_SCOPE_PATH_BYTES
    ) {
      throw new CliError(
        `${optionName} must be a repository-relative path of at most ` +
          `${MAX_SCOPE_PATH_BYTES} UTF-8 bytes`,
        2,
      );
    }
    try {
      const normalized = normalizeRepoRelative(value);
      if (unique.has(normalized)) {
        continue;
      }
      const components = portablePathComponents(normalized, optionName);
      if (
        portable.some(
          (prior) =>
            prior.length === components.length &&
            prior.every(
              (component, index) =>
                PORTABLE_COLLATOR.compare(component, components[index]) === 0,
            ),
        )
      ) {
        throw new CliError(
          `${optionName} contains paths that collide on a portable filesystem`,
          2,
        );
      }
      unique.add(normalized);
      portable.push(components);
    } catch (error) {
      if (error instanceof CliError) {
        throw new CliError(error.message, 2);
      }
      throw error;
    }
  }
  return [...unique].sort(compareStrings);
}

function portablePathComponents(value, optionName) {
  return value.split("/").map((component) => {
    const portable = component.normalize("NFC").replace(/[ .]+$/u, "");
    if (!portable) {
      throw new CliError(
        `${optionName} contains an empty portable path component`,
        2,
      );
    }
    if (PORTABLE_COLLATOR.compare(portable, ".git") === 0) {
      throw new CliError(
        `${optionName} collides with reserved review metadata`,
        2,
      );
    }
    return portable;
  });
}

function rejectOverlaps(values, optionName) {
  for (let index = 0; index < values.length; index += 1) {
    for (let other = index + 1; other < values.length; other += 1) {
      if (pathsOverlap(values[index], values[other])) {
        throw new CliError(
          `${optionName} paths overlap: ${JSON.stringify(values[index])} and ` +
            JSON.stringify(values[other]),
          2,
        );
      }
    }
  }
}

function describeSelection(
  configuredPath,
  tree,
  optionName,
  trustedRef,
  allowUnpopulated = false,
) {
  const selectedEntries = tree.filter((entry) =>
    pathIsWithin(entry.path, configuredPath),
  );
  const unsupported = selectedEntries.find(
    (entry) =>
      entry.type !== "blob" || !REGULAR_BLOB_MODES.has(entry.mode),
  );
  if (unsupported) {
    throw new CliError(
      `${optionName} ${JSON.stringify(configuredPath)} selects unsupported ` +
        `tracked entry ${JSON.stringify(unsupported.path)} at ${trustedRef} ` +
        `(mode=${unsupported.mode}, type=${unsupported.type}); review scope ` +
        "supports only regular tracked files",
      2,
    );
  }
  const regularMatches = selectedEntries;
  if (regularMatches.length === 0) {
    if (allowUnpopulated) {
      return {
        path: configuredPath,
        kind: "unpopulated",
        regularFiles: 0,
      };
    }
    throw new CliError(
      `${optionName} ${JSON.stringify(configuredPath)} does not select any ` +
        `regular tracked files at ${trustedRef}`,
      2,
    );
  }
  return {
    path: configuredPath,
    kind: regularMatches.some((entry) => entry.path === configuredPath)
      ? "file"
      : "directory",
    regularFiles: regularMatches.length,
  };
}

function pathsOverlap(left, right) {
  return pathIsWithin(left, right) || pathIsWithin(right, left);
}

function pathIsWithin(candidate, configuredPath) {
  return (
    candidate === configuredPath || candidate.startsWith(`${configuredPath}/`)
  );
}

function sameStrings(left, right) {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}
