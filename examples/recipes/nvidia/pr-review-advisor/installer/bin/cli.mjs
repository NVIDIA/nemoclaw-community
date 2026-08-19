#!/usr/bin/env node
// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import process from "node:process";
import { runCli } from "../lib/cli.mjs";

const exitCode = await runCli(process.argv.slice(2), {
  cwd: process.cwd(),
  stdin: process.stdin,
  stdout: process.stdout,
  stderr: process.stderr,
  env: process.env,
});

process.exitCode = exitCode;
