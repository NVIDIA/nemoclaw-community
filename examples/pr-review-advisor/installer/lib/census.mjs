// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import path from "node:path";
import {
  MAX_EVIDENCE_FILE_BYTES,
  MAX_EVIDENCE_LINES,
  MAX_EVIDENCE_TOTAL_BYTES,
} from "./constants.mjs";
import { listCommittedTree, readCommittedBlob } from "./git.mjs";
import { bindReviewScopeToTree, reviewScopeRole } from "./scope.mjs";
import { compareStrings, sha256 } from "./util.mjs";

const SECRET_PATH_PARTS = [
  ".env",
  ".npmrc",
  ".pypirc",
  ".netrc",
  "credential",
  "credentials",
  "id_rsa",
  "id_ed25519",
  "private-key",
  "private_key",
  "secret",
  "secrets",
  "token",
  "tokens",
];

const SECRET_EXTENSIONS = new Set([
  ".der",
  ".jks",
  ".key",
  ".p12",
  ".pfx",
  ".pem",
]);

const BINARY_EXTENSIONS = new Set([
  ".7z",
  ".a",
  ".avi",
  ".bin",
  ".bmp",
  ".class",
  ".dylib",
  ".eot",
  ".exe",
  ".gif",
  ".gz",
  ".ico",
  ".jar",
  ".jpeg",
  ".jpg",
  ".mov",
  ".mp3",
  ".mp4",
  ".o",
  ".otf",
  ".pdf",
  ".png",
  ".pyc",
  ".so",
  ".tar",
  ".tgz",
  ".ttf",
  ".wav",
  ".webm",
  ".webp",
  ".woff",
  ".woff2",
  ".xz",
  ".zip",
]);

const EXCLUDED_DIRECTORY_PARTS = new Set([
  ".cache",
  ".next",
  ".terraform",
  ".venv",
  "build",
  "coverage",
  "dist",
  "generated",
  "node_modules",
  "target",
  "vendor",
]);

const DOC_BASENAMES = new Set([
  "architecture.md",
  "contributing.md",
  "governance.md",
  "maintainers.md",
  "readme",
  "readme.md",
  "security.md",
  "support.md",
]);

const MANIFEST_BASENAMES = new Set([
  "build.gradle",
  "build.gradle.kts",
  "cargo.toml",
  "cmakelists.txt",
  "composer.json",
  "deno.json",
  "deno.jsonc",
  "flake.nix",
  "gemfile",
  "go.mod",
  "gradle.properties",
  "makefile",
  "package.json",
  "pom.xml",
  "project.toml",
  "pyproject.toml",
  "requirements.txt",
  "setup.cfg",
  "setup.py",
]);

const TEXT_EXTENSIONS = new Set([
  ".c",
  ".cc",
  ".conf",
  ".cpp",
  ".css",
  ".go",
  ".h",
  ".hpp",
  ".html",
  ".ini",
  ".java",
  ".js",
  ".json",
  ".jsx",
  ".kt",
  ".md",
  ".mjs",
  ".py",
  ".rb",
  ".rs",
  ".sh",
  ".sql",
  ".toml",
  ".ts",
  ".tsx",
  ".txt",
  ".xml",
  ".yaml",
  ".yml",
]);

const SECRET_PATTERNS = [
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/g,
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bgh[pousr]_[A-Za-z0-9_]{20,}\b/g,
  /\bgithub_pat_[A-Za-z0-9_]{20,}\b/g,
  /\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*["']?[^\s"',]{6,}/gi,
];

export function buildCensus(repository, reviewScope, options = {}) {
  const tree = listCommittedTree(repository);
  const boundScope = bindReviewScopeToTree(
    reviewScope,
    tree,
    repository.trustedRef,
    options.allowedUnpopulatedRoots ?? [],
  );
  const included = [];
  const excluded = [];
  let scopedEntries = 0;
  let supportEntries = 0;
  const categoryEntries = {
    architecture: [],
    codeowners: [],
    docs: [],
    guidance: [],
    manifests: [],
    security: [],
    tests: [],
    workflows: [],
  };

  for (const entry of tree) {
    const role = reviewScopeRole(entry.path, reviewScope);
    if (!role) {
      continue;
    }
    if (role === "scope") {
      scopedEntries += 1;
    } else {
      supportEntries += 1;
    }
    const reason = exclusionReason(entry);
    if (reason) {
      excluded.push(compactEntry(entry, reason, role));
      continue;
    }
    const categories = classify(entry.path);
    const normalized = {
      path: entry.path,
      oid: entry.oid,
      size: entry.size,
      categories,
      role,
    };
    included.push(normalized);
    for (const category of categories) {
      categoryEntries[category].push(normalized);
    }
  }

  const evidence = [];
  let evidenceBytes = 0;
  const evidenceCandidates = Object.values(categoryEntries)
    .flat()
    .filter(
      (entry, index, all) =>
        all.findIndex((candidate) => candidate.path === entry.path) === index,
    )
    .sort((left, right) => compareStrings(left.path, right.path));

  for (const entry of evidenceCandidates) {
    if (entry.size > MAX_EVIDENCE_FILE_BYTES) {
      excluded.push(compactEntry(entry, "evidence-size-limit", entry.role));
      continue;
    }
    if (evidenceBytes + entry.size > MAX_EVIDENCE_TOTAL_BYTES) {
      excluded.push(compactEntry(entry, "evidence-total-limit", entry.role));
      continue;
    }
    const blob = readCommittedBlob(repository, entry.oid);
    if (isBinary(blob)) {
      excluded.push(compactEntry(entry, "binary", entry.role));
      continue;
    }
    evidenceBytes += blob.byteLength;
    const fullText = blob.toString("utf8");
    const excerptLines = fullText.split(/\r?\n/).slice(0, MAX_EVIDENCE_LINES);
    const excerpt = redactSecrets(excerptLines.join("\n"));
    evidence.push({
      path: entry.path,
      oid: entry.oid,
      sha256: sha256(blob),
      size: entry.size,
      categories: entry.categories,
      role: entry.role,
      lineStart: 1,
      lineEnd: Math.max(1, excerptLines.length),
      truncated: excerptLines.length < fullText.split(/\r?\n/).length,
      excerpt,
    });
  }

  const layoutConcentrations = computeLayoutConcentrations(
    included.filter((entry) => entry.role === "scope"),
  );
  return {
    source: {
      kind: "git-commit",
      commit: repository.head,
      repository: repository.repository,
    },
    reviewScope: {
      mode: boundScope.mode,
      roots: boundScope.rootDescriptors,
      supportPaths: boundScope.supportDescriptors,
      unpopulatedRoots: boundScope.unpopulatedRoots,
    },
    limits: {
      maxEvidenceFileBytes: MAX_EVIDENCE_FILE_BYTES,
      maxEvidenceTotalBytes: MAX_EVIDENCE_TOTAL_BYTES,
      maxEvidenceLines: MAX_EVIDENCE_LINES,
    },
    counts: {
      trackedEntries: scopedEntries + supportEntries,
      scopedEntries,
      supportEntries,
      unpopulatedRoots: boundScope.unpopulatedRoots.length,
      regularFiles: included.length,
      evidenceFiles: evidence.length,
      excludedEntries: excluded.length,
    },
    categories: Object.fromEntries(
      Object.entries(categoryEntries).map(([category, entries]) => [
        category,
        entries.map(({ path: entryPath, oid, size, role }) => ({
          path: entryPath,
          oid,
          size,
          role,
        })),
      ]),
    ),
    layoutConcentrations,
    evidence,
    excluded: excluded.sort((left, right) =>
      compareStrings(left.path, right.path),
    ),
  };
}

function exclusionReason(entry) {
  if (entry.type !== "blob") {
    return entry.type === "commit" ? "gitlink" : "non-blob";
  }
  if (entry.mode === "120000") {
    return "symlink";
  }
  if (entry.mode !== "100644" && entry.mode !== "100755") {
    return "unsupported-mode";
  }
  if (!Number.isSafeInteger(entry.size) || entry.size < 0) {
    return "invalid-size";
  }

  const lowered = entry.path.toLowerCase();
  const parts = lowered.split("/");
  if (/[\u0000-\u001f\u007f\\]/u.test(entry.path)) {
    return "non-portable-path";
  }
  if (
    lowered.startsWith(".nemoclaw/review-advisor/") ||
    lowered === ".github/workflows/nemoclaw-review-advisor.yml"
  ) {
    return "advisor-generated-path";
  }
  if (parts.some((part) => EXCLUDED_DIRECTORY_PARTS.has(part))) {
    return "generated-or-vendored-path";
  }
  const basename = parts.at(-1);
  const extension = path.posix.extname(lowered);
  if (
    SECRET_EXTENSIONS.has(extension) ||
    SECRET_PATH_PARTS.some(
      (part) =>
        basename === part ||
        basename.startsWith(`${part}.`) ||
        basename.endsWith(`.${part}`) ||
        parts.slice(0, -1).includes(part),
    )
  ) {
    return "secret-like-path";
  }
  if (BINARY_EXTENSIONS.has(extension)) {
    return "binary-like-path";
  }
  return "";
}

function classify(filePath) {
  const lowered = filePath.toLowerCase();
  const basename = path.posix.basename(lowered);
  const extension = path.posix.extname(lowered);
  const parts = lowered.split("/");
  const categories = [];

  if (
    DOC_BASENAMES.has(basename) ||
    (parts.includes("docs") &&
      [".md", ".mdx", ".rst", ".txt"].includes(extension))
  ) {
    categories.push("docs");
  }
  if (
    [".md", ".mdx", ".rst", ".txt"].includes(extension) &&
    /(?:^|[-_.])(architecture|design|adr)(?:[-_.]|$)/.test(basename)
  ) {
    categories.push("architecture");
  }
  if (
    [".md", ".mdx", ".rst", ".txt"].includes(extension) &&
    /(?:^|[-_.])(security|threat-model|trust-boundary|trust-boundaries)(?:[-_.]|$)/.test(
      basename,
    )
  ) {
    categories.push("security");
  }
  if (
    /^(?:agents|claude|copilot|gemini)(?:\.[^.]+)?\.md$/.test(basename) ||
    basename === ".cursorrules"
  ) {
    categories.push("guidance");
  }
  if (
    basename === "codeowners" &&
    (parts.length === 1 ||
      parts.at(-2) === ".github" ||
      parts.at(-2) === "docs")
  ) {
    categories.push("codeowners");
  }
  if (
    MANIFEST_BASENAMES.has(basename) ||
    /^requirements(?:-[^.]+)?\.txt$/.test(basename)
  ) {
    categories.push("manifests");
  }
  if (
    (parts[0] === ".github" &&
      parts[1] === "workflows" &&
      [".yaml", ".yml"].includes(extension)) ||
    basename === ".gitlab-ci.yml" ||
    basename === "jenkinsfile"
  ) {
    categories.push("workflows");
  }
  if (
    parts.some((part) =>
      ["test", "tests", "spec", "specs", "__tests__"].includes(part),
    ) ||
    /\.(?:spec|test)\.[^.]+$/.test(basename) ||
    /^test_[^.]+\./.test(basename)
  ) {
    categories.push("tests");
  }
  return categories.sort();
}

function computeLayoutConcentrations(entries) {
  const buckets = new Map();
  for (const entry of entries) {
    const parts = entry.path.split("/");
    const bucket =
      parts.length === 1
        ? "(repository root)"
        : parts.length === 2
          ? parts[0]
          : parts.slice(0, 2).join("/");
    const current = buckets.get(bucket) ?? { path: bucket, files: 0, bytes: 0 };
    current.files += 1;
    current.bytes += entry.size;
    buckets.set(bucket, current);
  }
  return [...buckets.values()]
    .sort(
      (left, right) =>
        right.files - left.files ||
        right.bytes - left.bytes ||
        compareStrings(left.path, right.path),
    )
    .slice(0, 12);
}

function compactEntry(entry, reason, role) {
  return {
    path: entry.path,
    size: entry.size,
    reason,
    role,
  };
}

function isBinary(buffer) {
  if (buffer.includes(0)) {
    return true;
  }
  const sample = buffer.subarray(0, Math.min(buffer.length, 8192));
  let suspicious = 0;
  for (const byte of sample) {
    if (byte < 7 || (byte > 13 && byte < 32) || byte === 127) {
      suspicious += 1;
    }
  }
  return sample.length > 0 && suspicious / sample.length > 0.1;
}

function redactSecrets(value) {
  let redacted = value;
  for (const pattern of SECRET_PATTERNS) {
    redacted = redacted.replace(pattern, "[REDACTED]");
  }
  return redacted;
}

export function isLikelyTextPath(filePath) {
  const basename = path.posix.basename(filePath).toLowerCase();
  return (
    TEXT_EXTENSIONS.has(path.posix.extname(basename)) ||
    MANIFEST_BASENAMES.has(basename) ||
    basename === "codeowners" ||
    basename === "dockerfile"
  );
}
