// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import test from "node:test";

import { decodeSandboxSource } from "../../site/scripts/diagrams.mjs";

test("Mermaid sandbox documents decode Unicode as UTF-8", () => {
  const source = "♿ axe-core · 🌐 browser → 🤖 agent — 1920×1080";
  const payload = Buffer.from(source, "utf8").toString("base64");

  assert.equal(
    decodeSandboxSource(`data:text/html;charset=UTF-8;base64,${payload}`),
    source,
  );
});
