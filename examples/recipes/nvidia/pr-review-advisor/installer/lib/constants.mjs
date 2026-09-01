// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export const PACKAGE_NAME = "@nvidia/nemoclaw-review-advisor";
export const PACKAGE_VERSION = "0.1.0";
export const STATE_SCHEMA_VERSION = 2;
export const PROFILE_SCHEMA_VERSION = 1;
export const INSTALL_DIR = ".nemoclaw/review-advisor";
export const STATE_PATH = `${INSTALL_DIR}/install-state.json`;
export const OVERRIDE_PROFILE_PATH = `${INSTALL_DIR}/profile.yaml`;
export const GENERATED_WORKFLOW_PATH =
  ".github/workflows/nemoclaw-review-advisor.yml";

export const MAX_EVIDENCE_FILE_BYTES = 256 * 1024;
export const MAX_EVIDENCE_TOTAL_BYTES = 2 * 1024 * 1024;
export const MAX_EVIDENCE_LINES = 80;
export const MAX_RUNTIME_FILE_BYTES = 4 * 1024 * 1024;

export const REQUIRED_RUNTIME_FILES = [
  "dependencies.toml",
  "scripts/example_dependencies.py",
  "scripts/example_dependencies.sh",
  "scripts/review.sh",
];

export const RUNTIME_ASSET_ROOTS = [
  "agents/hermes",
  "docs",
  "installer",
  "review-profiles",
  "schemas",
  "scripts",
  "skills/pr-review",
];

export const RUNTIME_ASSET_FILES = [
  ".env.example",
  "dependencies.toml",
  "LICENSE",
  "README.md",
  "policy.yaml",
];
