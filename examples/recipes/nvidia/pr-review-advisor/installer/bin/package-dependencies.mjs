// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const repositoryRoot = path.resolve(packageRoot, "../../../..");
const destinationRoot = path.join(packageRoot, "installer", "shared");
const names = ["example_dependencies.py", "example_dependencies.sh"];

const action = process.argv[2];
if (action === "prepare") {
  fs.rmSync(destinationRoot, { force: true, recursive: true });
  fs.mkdirSync(destinationRoot, { recursive: true });
  for (const name of names) {
    const source = path.join(repositoryRoot, "scripts", name);
    const stat = fs.lstatSync(source);
    if (!stat.isFile() || stat.isSymbolicLink()) {
      throw new Error(`shared dependency resolver must be a regular file: ${source}`);
    }
    const destination = path.join(destinationRoot, name);
    fs.copyFileSync(source, destination);
    fs.chmodSync(destination, stat.mode & 0o777);
  }
} else if (action === "clean") {
  fs.rmSync(destinationRoot, { force: true, recursive: true });
} else {
  throw new Error("usage: package-dependencies.mjs prepare|clean");
}
