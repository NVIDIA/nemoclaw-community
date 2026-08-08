// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { CliError, compareStrings, isWithin } from "./util.mjs";

const MAX_GIT_OUTPUT = 64 * 1024 * 1024;

export function git(args, cwd, options = {}) {
  const result = spawnSync("git", args, {
    cwd,
    encoding: options.encoding ?? "utf8",
    maxBuffer: options.maxBuffer ?? MAX_GIT_OUTPUT,
    env: {
      PATH: process.env.PATH,
      HOME: process.env.HOME,
      GIT_CONFIG_GLOBAL: "/dev/null",
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_NO_REPLACE_OBJECTS: "1",
      GIT_TERMINAL_PROMPT: "0",
      LC_ALL: "C",
    },
  });

  if (result.error) {
    throw new CliError(`unable to run git: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const detail = String(result.stderr ?? "").trim();
    throw new CliError(`git ${args[0]} failed${detail ? `: ${detail}` : ""}`);
  }
  return result.stdout;
}

export function isAncestor(root, ancestor, descendant) {
  const result = spawnSync(
    "git",
    ["merge-base", "--is-ancestor", ancestor, descendant],
    {
      cwd: root,
      encoding: "utf8",
      env: {
        PATH: process.env.PATH,
        HOME: process.env.HOME,
        GIT_CONFIG_GLOBAL: "/dev/null",
        GIT_CONFIG_NOSYSTEM: "1",
        GIT_NO_REPLACE_OBJECTS: "1",
        GIT_TERMINAL_PROMPT: "0",
        LC_ALL: "C",
      },
    },
  );
  if (result.error) {
    throw new CliError(
      `unable to validate Git ancestry: ${result.error.message}`,
    );
  }
  if (result.status === 0) {
    return true;
  }
  if (result.status === 1) {
    return false;
  }
  const detail = String(result.stderr ?? "").trim();
  throw new CliError(
    `git merge-base --is-ancestor failed${detail ? `: ${detail}` : ""}`,
  );
}

export function readCommittedPathBlob(root, commit, relativePath) {
  if (
    !relativePath ||
    path.posix.isAbsolute(relativePath) ||
    relativePath.split("/").includes("..") ||
    relativePath.includes("\0")
  ) {
    throw new CliError("committed blob path must be repository-relative");
  }
  const listing = git(
    ["ls-tree", "-z", "--full-tree", commit, "--", relativePath],
    root,
    { encoding: "buffer" },
  );
  const records = listing.toString("utf8").split("\0").filter(Boolean);
  if (records.length === 0) {
    return null;
  }
  if (records.length !== 1) {
    throw new CliError(
      `trusted tree returned multiple entries for ${relativePath}`,
    );
  }
  const tab = records[0].indexOf("\t");
  if (tab < 0 || records[0].slice(tab + 1) !== relativePath) {
    throw new CliError(
      `trusted tree returned malformed metadata for ${relativePath}`,
    );
  }
  const [mode, type, oid] = records[0].slice(0, tab).split(/\s+/);
  if (!mode || !type || !oid) {
    throw new CliError(
      `trusted tree returned malformed metadata for ${relativePath}`,
    );
  }
  if (mode !== "100644" || type !== "blob") {
    return { mode, type, oid, content: null };
  }
  const content = git(["cat-file", "blob", oid], root, { encoding: "buffer" });
  return { mode, type, oid, content };
}

export function resolveRepository(targetPath, options = {}) {
  const { requested, root: resolvedRoot } = resolveGitRoot(targetPath);

  const worktreeHead = String(
    git(["rev-parse", "--verify", "HEAD^{commit}"], resolvedRoot),
  ).trim();
  const branchResult = spawnSync(
    "git",
    ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
    {
      cwd: resolvedRoot,
      encoding: "utf8",
      env: {
        PATH: process.env.PATH,
        HOME: process.env.HOME,
        GIT_CONFIG_GLOBAL: "/dev/null",
        GIT_CONFIG_NOSYSTEM: "1",
        GIT_TERMINAL_PROMPT: "0",
        LC_ALL: "C",
      },
    },
  );
  let defaultBranch =
    branchResult.status === 0
      ? branchResult.stdout.trim().replace(/^origin\//, "")
      : "";
  if (!defaultBranch && options.trustedRef) {
    defaultBranch = defaultBranchFromTrustedRef(options.trustedRef);
  }

  const trustedRef =
    options.trustedRef ?? (defaultBranch ? "refs/remotes/origin/HEAD" : "");
  if (!trustedRef) {
    throw new CliError(
      "unable to establish a trusted default branch; fetch origin so " +
        "refs/remotes/origin/HEAD exists or pass --trusted-ref REF explicitly",
      2,
    );
  }
  validateTrustedRef(trustedRef);
  const trustedHead = String(
    git(
      ["rev-parse", "--verify", "--end-of-options", `${trustedRef}^{commit}`],
      resolvedRoot,
    ),
  ).trim();

  let remote = "";
  const remoteResult = spawnSync("git", ["remote", "get-url", "origin"], {
    cwd: resolvedRoot,
    encoding: "utf8",
    env: {
      PATH: process.env.PATH,
      HOME: process.env.HOME,
      GIT_CONFIG_GLOBAL: "/dev/null",
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_TERMINAL_PROMPT: "0",
      LC_ALL: "C",
    },
  });
  if (remoteResult.status === 0) {
    remote = remoteResult.stdout.trim();
  }

  return {
    root: resolvedRoot,
    head: trustedHead,
    trustedHead,
    trustedRef,
    worktreeHead,
    defaultBranch,
    repository: sanitizeRepositoryIdentity(remote, resolvedRoot),
  };
}

function defaultBranchFromTrustedRef(trustedRef) {
  const localMatch = /^refs\/heads\/(.+)$/.exec(trustedRef);
  if (localMatch) {
    return localMatch[1];
  }
  const originMatch = /^refs\/remotes\/origin\/(.+)$/.exec(trustedRef);
  if (originMatch && originMatch[1] !== "HEAD") {
    return originMatch[1];
  }
  return "";
}

function validateTrustedRef(trustedRef) {
  if (trustedRef.length > 512) {
    throw new CliError("--trusted-ref exceeds 512 characters", 2);
  }
  if (trustedRef === "HEAD" || /^[0-9a-f]{40,64}$/.test(trustedRef)) {
    return;
  }
  if (
    /^refs\/[A-Za-z0-9._/-]+$/.test(trustedRef) &&
    !trustedRef.includes("..") &&
    !trustedRef.includes("//") &&
    !trustedRef.endsWith("/") &&
    !trustedRef.endsWith(".") &&
    !trustedRef.includes("@{")
  ) {
    return;
  }
  throw new CliError(
    "--trusted-ref must be HEAD, a full commit SHA, or a canonical refs/... name",
    2,
  );
}

export function resolveGitRoot(targetPath) {
  const requested = fs.realpathSync(path.resolve(targetPath));
  const root = String(
    git(["-C", requested, "rev-parse", "--show-toplevel"], requested),
  ).trim();
  const resolvedRoot = fs.realpathSync(path.resolve(root));
  if (!isWithin(resolvedRoot, requested)) {
    throw new CliError(
      `target ${requested} did not resolve inside Git root ${resolvedRoot}`,
    );
  }
  return { requested, root: resolvedRoot };
}

export function listCommittedTree(repository) {
  const output = git(
    ["ls-tree", "-r", "-z", "-l", "--full-tree", repository.head],
    repository.root,
    { encoding: "buffer" },
  );
  const records = [];
  for (const raw of output.toString("utf8").split("\0")) {
    if (!raw) {
      continue;
    }
    const tab = raw.indexOf("\t");
    if (tab < 0) {
      throw new CliError("unexpected git ls-tree output");
    }
    const metadata = raw.slice(0, tab).split(/\s+/);
    if (metadata.length !== 4) {
      throw new CliError("unexpected git ls-tree metadata");
    }
    const [mode, type, oid, sizeText] = metadata;
    const treePath = raw.slice(tab + 1);
    records.push({
      mode,
      type,
      oid,
      size: sizeText === "-" ? 0 : Number.parseInt(sizeText, 10),
      path: treePath,
    });
  }
  return records.sort((left, right) => compareStrings(left.path, right.path));
}

export function readCommittedBlob(repository, oid) {
  return git(["cat-file", "blob", oid], repository.root, {
    encoding: "buffer",
    maxBuffer: MAX_GIT_OUTPUT,
  });
}

function sanitizeRepositoryIdentity(remote, root) {
  const localName =
    path
      .basename(root)
      .replace(/[^A-Za-z0-9_.-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 128) || "repository";
  const fallback = `local/${localName}`;
  if (!remote) {
    return fallback;
  }

  const scpMatch = remote.match(
    /^(?:[^@/]+@)?(?:github\.com|gitlab\.com):([^/\s]+)\/([^/\s]+?)(?:\.git)?$/,
  );
  if (scpMatch) {
    return `${scpMatch[1]}/${scpMatch[2]}`;
  }

  try {
    const parsed = new URL(remote);
    if (!["https:", "http:", "ssh:"].includes(parsed.protocol)) {
      return fallback;
    }
    const parts = parsed.pathname
      .replace(/^\/+/, "")
      .replace(/\.git$/, "")
      .split("/")
      .filter(Boolean);
    if (parts.length >= 2) {
      return `${parts.at(-2)}/${parts.at(-1)}`;
    }
  } catch {
    // Local paths and malformed remotes intentionally fall back to the folder name.
  }
  return fallback;
}
