// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Generate the small, build-time Hermes configuration used by this example.

import { chmodSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const model = process.env.NEMOCLAW_MODEL;
const baseUrl = process.env.NEMOCLAW_INFERENCE_BASE_URL;
if (!model || !baseUrl) {
  throw new Error("NEMOCLAW_MODEL and NEMOCLAW_INFERENCE_BASE_URL are required");
}

const config = `_config_version: 39
model:
  default: ${JSON.stringify(model)}
  provider: custom
  base_url: ${JSON.stringify(baseUrl)}
terminal:
  backend: local
  cwd: /sandbox
  timeout: 180
agent:
  max_turns: 30
  reasoning_effort: medium
  verify_on_stop: false
memory:
  memory_enabled: true
  user_profile_enabled: true
skills:
  creation_nudge_interval: 15
display:
  compact: false
  tool_progress: all
  interim_assistant_messages: false
approvals:
  mode: off
  timeout: 60
platforms:
  api_server:
    enabled: true
    extra:
      port: 8642
      host: 0.0.0.0
`;

const hermesHome = join(homedir(), ".hermes");
const configPath = join(hermesHome, "config.yaml");
const envPath = join(hermesHome, ".env");

writeFileSync(configPath, config);
writeFileSync(
  envPath,
  "API_SERVER_PORT=8642\nAPI_SERVER_HOST=0.0.0.0\nAPI_SERVER_KEY=nemoclaw-internal\n",
);
chmodSync(configPath, 0o600);
chmodSync(envPath, 0o600);

console.log(`[config] Wrote ${configPath} (model=${model}, provider=custom)`);
