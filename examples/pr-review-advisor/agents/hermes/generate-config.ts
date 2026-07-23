// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { chmodSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const home = process.env.HERMES_HOME || "/sandbox/.hermes";
const model =
  process.env.NEMOCLAW_MODEL || "nvidia/nemotron-3-ultra-550b-a55b";
const baseUrl = process.env.NEMOCLAW_INFERENCE_BASE_URL || "https://inference.local/v1";

function quoted(value: string): string {
  return JSON.stringify(value);
}

mkdirSync(home, { recursive: true });

// API sessions intentionally omit terminal, file, browser, web, code execution,
// delegation, and cron. Repository access is available only through the
// review-advisor plugin's no-follow, root-confined tools.
const config = `_config_version: 32
model:
  default: ${quoted(model)}
  provider: custom
  base_url: ${quoted(baseUrl)}
  api_key: sk-OPENSHELL-PROXY-REWRITE
custom_providers:
  - name: review-advisor-inference
    base_url: ${quoted(baseUrl)}
    api_key: sk-OPENSHELL-PROXY-REWRITE
    discover_models: true
terminal:
  backend: local
  timeout: 180
agent:
  max_turns: 80
  reasoning_effort: high
  verify_on_stop: false
compression:
  in_place: true
memory:
  memory_enabled: true
  user_profile_enabled: false
skills:
  creation_nudge_interval: 0
display:
  compact: false
  tool_progress: all
  interim_assistant_messages: false
curator:
  enabled: false
plugins:
  enabled:
    - review-advisor
platform_toolsets:
  api_server:
    - review-advisor
platforms:
  api_server:
    enabled: true
    extra:
      port: 18642
      host: 127.0.0.1
`;

const configPath = join(home, "config.yaml");
const envPath = join(home, ".env");
writeFileSync(configPath, config, { encoding: "utf8", mode: 0o600 });
writeFileSync(envPath, "API_SERVER_PORT=18642\nAPI_SERVER_HOST=127.0.0.1\n", {
  encoding: "utf8",
  mode: 0o600,
});
chmodSync(configPath, 0o600);
chmodSync(envPath, 0o600);
