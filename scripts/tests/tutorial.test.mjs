// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import test from "node:test";

import {
  addCopyButtons,
  initActiveToc,
  initTutorial,
  initTutorialPaging,
} from "../../site/scripts/tutorial.mjs";

test("tutorial enhancements remain available as a local module", () => {
  assert.equal(typeof addCopyButtons, "function");
  assert.equal(typeof initActiveToc, "function");
  assert.equal(typeof initTutorial, "function");
  assert.equal(typeof initTutorialPaging, "function");
});
