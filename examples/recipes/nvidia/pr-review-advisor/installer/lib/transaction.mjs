// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { randomUUID } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { git } from "./git.mjs";
import {
  CliError,
  compareStrings,
  isWithin,
  lines,
  normalizeRepoRelative,
  sha256,
} from "./util.mjs";

export function acquireInstallerLock(root) {
  const reportedLockPath = String(
    git(
      ["rev-parse", "--git-path", "nemoclaw-review-advisor-install.lock"],
      root,
    ),
  ).trim();
  const rawLockPath = path.resolve(root, reportedLockPath);
  if (path.basename(rawLockPath) !== "nemoclaw-review-advisor-install.lock") {
    throw new CliError("Git returned an unsafe installer lock path");
  }
  const lockParent = path.dirname(rawLockPath);
  const parentInfo = fs.lstatSync(lockParent);
  if (!parentInfo.isDirectory() || parentInfo.isSymbolicLink()) {
    throw new CliError("installer lock parent must be a regular Git directory");
  }

  const flags =
    fs.constants.O_WRONLY |
    fs.constants.O_CREAT |
    fs.constants.O_EXCL |
    (fs.constants.O_NOFOLLOW ?? 0);
  let descriptor;
  try {
    descriptor = fs.openSync(rawLockPath, flags, 0o600);
    fs.writeFileSync(
      descriptor,
      `${JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() })}\n`,
      "utf8",
    );
    fs.fsyncSync(descriptor);
  } catch (error) {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
    if (error?.code === "EEXIST" || error?.code === "ELOOP") {
      throw new CliError(
        `another installer operation is active, or a stale lock remains: ${rawLockPath}`,
        2,
      );
    }
    throw new CliError(`cannot acquire installer lock: ${error.message}`);
  }

  const held = fs.fstatSync(descriptor);
  let released = false;
  return () => {
    if (released) {
      return;
    }
    released = true;
    let releaseError = null;
    try {
      const current = fs.lstatSync(rawLockPath);
      if (
        current.isSymbolicLink() ||
        current.dev !== held.dev ||
        current.ino !== held.ino
      ) {
        releaseError = new CliError(
          `installer lock identity changed while held: ${rawLockPath}`,
        );
      } else {
        fs.unlinkSync(rawLockPath);
      }
    } catch (error) {
      if (error?.code !== "ENOENT") {
        releaseError = new CliError(
          `cannot release installer lock: ${error.message}`,
        );
      }
    } finally {
      fs.closeSync(descriptor);
    }
    if (releaseError) {
      throw releaseError;
    }
  };
}

export function inspectFile(root, relativePath) {
  const safePath = normalizeRepoRelative(relativePath);
  assertNoSymlinkTraversal(root, safePath);
  const absolute = path.join(root, safePath);
  if (!fs.existsSync(absolute)) {
    return { exists: false, relativePath: safePath, absolute };
  }
  const stat = fs.lstatSync(absolute);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new CliError(`${safePath} is not a regular file`);
  }
  const content = fs.readFileSync(absolute);
  return {
    exists: true,
    relativePath: safePath,
    absolute,
    content,
    sha256: sha256(content),
    mode: stat.mode & 0o777,
  };
}

export function planInstall(root, desiredFiles, previousState, overrideFile) {
  const operations = [];
  const conflicts = [];
  const previousOwned = previousState?.ownedFiles ?? {};

  for (const [relativePath, desired] of [...desiredFiles.entries()].sort(
    ([left], [right]) => compareStrings(left, right),
  )) {
    const current = inspectFile(root, relativePath);
    const previous = previousOwned[relativePath];
    if (current.exists && !previous) {
      conflicts.push(
        `${relativePath} already exists and is not installer-owned`,
      );
      continue;
    }
    if (current.exists && previous && current.sha256 !== previous.sha256) {
      conflicts.push(`${relativePath} was modified after installation`);
      continue;
    }
    if (
      !current.exists ||
      current.sha256 !== desired.sha256 ||
      current.mode !== desired.mode
    ) {
      operations.push({
        action: "write",
        relativePath,
        before: current.exists ? current.content : null,
        beforeMode: current.exists ? current.mode : null,
        after: desired.content,
        mode: desired.mode,
      });
    }
  }

  for (const [relativePath, previous] of Object.entries(previousOwned).sort(
    ([left], [right]) => compareStrings(left, right),
  )) {
    if (desiredFiles.has(relativePath)) {
      continue;
    }
    const current = inspectFile(root, relativePath);
    if (!current.exists) {
      continue;
    }
    if (current.sha256 !== previous.sha256) {
      conflicts.push(`${relativePath} was modified and cannot be retired`);
      continue;
    }
    operations.push({
      action: "delete",
      relativePath,
      before: current.content,
      beforeMode: current.mode,
      after: null,
    });
  }

  const override = inspectFile(root, overrideFile.relativePath);
  if (!override.exists) {
    operations.push({
      action: "write-unowned",
      relativePath: overrideFile.relativePath,
      before: null,
      after: overrideFile.content,
      mode: overrideFile.mode,
    });
  }

  return { operations, conflicts };
}

export function planRemoval(root, state, statePath) {
  const operations = [];
  const preserved = [];
  for (const [relativePath, owned] of Object.entries(state.ownedFiles).sort(
    ([left], [right]) => compareStrings(left, right),
  )) {
    const current = inspectFile(root, relativePath);
    if (!current.exists) {
      continue;
    }
    if (current.sha256 !== owned.sha256) {
      preserved.push(relativePath);
      continue;
    }
    operations.push({
      action: "delete",
      relativePath,
      before: current.content,
      beforeMode: current.mode,
      after: null,
    });
  }
  const metadata = inspectFile(root, statePath);
  if (metadata.exists) {
    operations.push({
      action: "delete",
      relativePath: statePath,
      before: metadata.content,
      beforeMode: metadata.mode,
      after: null,
    });
  }
  return { operations, conflicts: [], preserved };
}

export function renderPlan(operations) {
  if (operations.length === 0) {
    return "No file changes.\n";
  }
  const chunks = [];
  for (const operation of operations) {
    chunks.push(renderOperation(operation));
  }
  return `${chunks.join("\n")}\n`;
}

export function applyTransaction(root, operations) {
  if (operations.length === 0) {
    return;
  }
  const stagingRoot = fs.mkdtempSync(
    path.join(os.tmpdir(), "nemoclaw-review-advisor-"),
  );
  const staged = new Map();
  const applied = [];
  const temporaryTargets = new Set();
  try {
    for (const operation of operations) {
      if (!operation.action.startsWith("write")) {
        continue;
      }
      const stagedPath = path.join(stagingRoot, operation.relativePath);
      fs.mkdirSync(path.dirname(stagedPath), { recursive: true });
      fs.writeFileSync(stagedPath, operation.after, { mode: operation.mode });
      staged.set(operation.relativePath, stagedPath);
    }

    for (const operation of operations) {
      const safePath = normalizeRepoRelative(operation.relativePath);
      assertOperationPrecondition(root, operation);
      assertNoSymlinkTraversal(root, safePath);
      const target = path.join(root, safePath);
      if (!isWithin(root, target)) {
        throw new CliError(
          `transaction target escapes repository: ${safePath}`,
        );
      }
      if (operation.action.startsWith("write")) {
        fs.mkdirSync(path.dirname(target), { recursive: true });
        assertNoSymlinkTraversal(root, safePath);
        const temporaryTarget = `${target}.nemoclaw-tmp-${randomUUID()}`;
        temporaryTargets.add(temporaryTarget);
        fs.copyFileSync(
          staged.get(safePath),
          temporaryTarget,
          fs.constants.COPYFILE_EXCL,
        );
        fs.chmodSync(temporaryTarget, operation.mode);
        fs.renameSync(temporaryTarget, target);
        temporaryTargets.delete(temporaryTarget);
      } else {
        fs.unlinkSync(target);
      }
      applied.push(operation);
    }
  } catch (error) {
    const rollbackFailures = rollbackAppliedOperations(root, applied);
    const rollbackStatus =
      rollbackFailures.length === 0
        ? "transaction changes were rolled back"
        : `rollback incomplete; preserved changed targets: ${rollbackFailures.join(", ")}`;
    throw new CliError(
      `transaction failed; ${rollbackStatus}: ${error.message}`,
    );
  } finally {
    for (const temporaryTarget of temporaryTargets) {
      fs.rmSync(temporaryTarget, { force: true });
    }
    fs.rmSync(stagingRoot, { recursive: true, force: true });
  }
}

function assertOperationPrecondition(root, operation) {
  const current = inspectFile(root, operation.relativePath);
  if (operation.before === null) {
    if (current.exists) {
      throw new CliError(
        `transaction target changed after review: ${operation.relativePath}`,
      );
    }
    return;
  }
  if (
    !current.exists ||
    !current.content.equals(operation.before) ||
    current.mode !== operation.beforeMode
  ) {
    throw new CliError(
      `transaction target changed after review: ${operation.relativePath}`,
    );
  }
}

export function rollbackAppliedOperations(root, applied) {
  const failures = [];
  for (const operation of [...applied].reverse()) {
    const target = path.join(root, operation.relativePath);
    try {
      const current = inspectFile(root, operation.relativePath);
      if (operation.action.startsWith("write")) {
        if (!current.exists) {
          if (operation.before !== null) {
            failures.push(operation.relativePath);
          }
          continue;
        }
        if (
          !current.content.equals(operation.after) ||
          current.mode !== operation.mode
        ) {
          failures.push(operation.relativePath);
          continue;
        }
        if (operation.before === null) {
          fs.unlinkSync(target);
        } else {
          fs.writeFileSync(target, operation.before, {
            mode: operation.beforeMode ?? 0o644,
          });
          fs.chmodSync(target, operation.beforeMode ?? 0o644);
        }
      } else if (current.exists) {
        failures.push(operation.relativePath);
      } else if (operation.before !== null) {
        fs.writeFileSync(target, operation.before, {
          flag: "wx",
          mode: operation.beforeMode ?? 0o644,
        });
        fs.chmodSync(target, operation.beforeMode ?? 0o644);
      } else {
        failures.push(operation.relativePath);
      }
    } catch {
      failures.push(operation.relativePath);
    }
  }
  return [...new Set(failures)];
}

function renderOperation(operation) {
  const beforeName =
    operation.before === null ? "/dev/null" : `a/${operation.relativePath}`;
  const afterName =
    operation.after === null ? "/dev/null" : `b/${operation.relativePath}`;
  const output = [
    `diff --nemoclaw ${beforeName} ${afterName}`,
    `--- ${beforeName}`,
    `+++ ${afterName}`,
  ];
  if (operation.before !== null) {
    output.push(
      ...lines(operation.before.toString("utf8")).map((line) => `-${line}`),
    );
  }
  if (operation.after !== null) {
    output.push(
      ...lines(operation.after.toString("utf8")).map((line) => `+${line}`),
    );
  }
  return output.join("\n");
}

function assertNoSymlinkTraversal(root, relativePath) {
  const parts = relativePath.split("/");
  let current = root;
  for (const part of parts) {
    current = path.join(current, part);
    if (!fs.existsSync(current)) {
      return;
    }
    if (fs.lstatSync(current).isSymbolicLink()) {
      throw new CliError(`refusing symlinked install path: ${relativePath}`);
    }
  }
}
