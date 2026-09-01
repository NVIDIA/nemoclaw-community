// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  MAX_RUNTIME_FILE_BYTES,
  REQUIRED_RUNTIME_FILES,
  RUNTIME_ASSET_FILES,
  RUNTIME_ASSET_ROOTS,
} from "./constants.mjs";
import {
  CliError,
  compareStrings,
  normalizeRepoRelative,
  sha256,
  toPosix,
} from "./util.mjs";

const DEFAULT_ASSET_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const SHARED_DEPENDENCY_FILES = [
  "example_dependencies.py",
  "example_dependencies.sh",
];

export function collectRuntimeAssets(assetRoot = DEFAULT_ASSET_ROOT) {
  const sourceRoot = path.resolve(assetRoot);
  const sourceFiles = [];

  for (const relative of RUNTIME_ASSET_FILES) {
    const source = path.join(sourceRoot, relative);
    if (fs.existsSync(source)) {
      sourceFiles.push({ relative, source });
    }
  }
  for (const relativeRoot of RUNTIME_ASSET_ROOTS) {
    const source = path.join(sourceRoot, relativeRoot);
    if (fs.existsSync(source)) {
      walkAssetDirectory(sourceRoot, source, sourceFiles);
    }
  }
  for (const name of SHARED_DEPENDENCY_FILES) {
    const relative = `scripts/${name}`;
    if (sourceFiles.some((entry) => entry.relative === relative)) {
      throw new CliError(`package runtime cannot override shared ${relative}`);
    }
    sourceFiles.push({ relative, source: resolveSharedDependency(name) });
  }

  const relativeFiles = new Set(
    sourceFiles.map(({ relative }) => toPosix(relative)),
  );
  const missing = REQUIRED_RUNTIME_FILES.filter(
    (required) => !relativeFiles.has(required),
  );
  if (missing.length > 0) {
    throw new CliError(
      `package runtime is incomplete; missing ${missing.join(", ")} under ${sourceRoot}`,
    );
  }

  const assets = new Map();
  for (const { relative, source } of sourceFiles.sort((left, right) =>
    compareStrings(left.relative, right.relative),
  )) {
    const safeRelative = normalizeRepoRelative(relative);
    const stat = fs.lstatSync(source);
    if (!stat.isFile() || stat.isSymbolicLink()) {
      throw new CliError(
        `runtime asset must be a regular file: ${safeRelative}`,
      );
    }
    if (stat.size > MAX_RUNTIME_FILE_BYTES) {
      throw new CliError(
        `runtime asset exceeds ${MAX_RUNTIME_FILE_BYTES} bytes: ${safeRelative}`,
      );
    }
    const content = fs.readFileSync(source);
    if (content.includes(0)) {
      throw new CliError(
        `runtime asset must be text, not binary: ${safeRelative}`,
      );
    }
    assets.set(`.nemoclaw/review-advisor/runtime/${safeRelative}`, {
      content,
      mode: stat.mode & 0o111 ? 0o755 : 0o644,
      source: safeRelative,
      sha256: sha256(content),
    });
  }
  return { sourceRoot, assets };
}

function resolveSharedDependency(name) {
  const candidates = [
    path.join(DEFAULT_ASSET_ROOT, "installer", "shared", name),
    path.resolve(DEFAULT_ASSET_ROOT, "../../../..", "scripts", name),
  ];
  const source = candidates.find((candidate) => fs.existsSync(candidate));
  if (!source) {
    throw new CliError(
      `package runtime is missing shared dependency resolver ${name}`,
    );
  }
  return source;
}

function walkAssetDirectory(sourceRoot, directory, files) {
  const entries = fs
    .readdirSync(directory, { withFileTypes: true })
    .sort((left, right) => compareStrings(left.name, right.name));
  for (const entry of entries) {
    if (
      [".git", ".DS_Store", "__pycache__", "node_modules"].includes(
        entry.name,
      ) ||
      entry.name.endsWith(".pyc") ||
      (entry.name.startsWith(".env") && entry.name !== ".env.example")
    ) {
      continue;
    }
    const source = path.join(directory, entry.name);
    const relative = toPosix(path.relative(sourceRoot, source));
    if (entry.isSymbolicLink()) {
      throw new CliError(`runtime asset symlinks are not allowed: ${relative}`);
    }
    if (entry.isDirectory()) {
      walkAssetDirectory(sourceRoot, source, files);
    } else if (entry.isFile()) {
      files.push({ relative, source });
    }
  }
}
