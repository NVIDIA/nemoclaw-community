// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Generate Hermes config.yaml and .env from NemoClaw build-arg env vars.
//
// Called at Docker image build time. Reads NEMOCLAW_* env vars and writes:
//   ~/.hermes/config.yaml  — Hermes configuration (immutable at runtime)
//   ~/.hermes/.env         — Messaging token placeholders (immutable at runtime)
//
// Sets what's required for Hermes to run inside OpenShell:
//   - Model and inference endpoint (custom provider pointing at inference.local)
//   - API server on internal port (socat forwards to public port)
//   - Messaging platform tokens (if configured during onboard)
//   - Agent defaults (terminal, memory, skills, display)
//   - Slack-facing UX tweaks (less mid-turn chatter, no browser tool exposure)

import { writeFileSync, chmodSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const TOKEN_ENV: Record<string, string> = {
  telegram: "TELEGRAM_BOT_TOKEN",
  discord: "DISCORD_BOT_TOKEN",
  slack: "SLACK_BOT_TOKEN",
};

// Secondary per-channel tokens written as additional OpenShell placeholders.
const EXTRA_TOKEN_ENV: Record<string, string> = {
  slack: "SLACK_APP_TOKEN",
};

// Gateway reads these env vars in _is_user_authorized — NOT config.yaml allowed_users.
const ALLOWED_USERS_ENV: Record<string, string> = {
  telegram: "TELEGRAM_ALLOWED_USERS",
  discord: "DISCORD_ALLOWED_USERS",
  slack: "SLACK_ALLOWED_USERS",
};

const SOURCE_ETL_ENV = [
  "SOURCE_ETL_GITHUB_REPO",
  "SOURCE_ETL_FORUM_TAG",
  "SOURCE_ETL_API_URL",
  "SOURCE_ETL_API_HOST",
  "SOURCE_ETL_API_PORT",
] as const;

function main(): void {
  const model = process.env.NEMOCLAW_MODEL!;
  const baseUrl = process.env.NEMOCLAW_INFERENCE_BASE_URL!;

  const channelsB64 = process.env.NEMOCLAW_MESSAGING_CHANNELS_B64 || "W10=";
  const allowedIdsB64 = process.env.NEMOCLAW_MESSAGING_ALLOWED_IDS_B64 || "e30=";

  const msgChannels: string[] = JSON.parse(
    Buffer.from(channelsB64, "base64").toString("utf-8"),
  );
  const allowedIds: Record<string, (string | number)[]> = JSON.parse(
    Buffer.from(allowedIdsB64, "base64").toString("utf-8"),
  );

  const config: Record<string, unknown> = {
    _config_version: 12,
    model: {
      default: model,
      provider: "custom",
      base_url: baseUrl,
    },
    terminal: {
      backend: "local",
      timeout: 180,
    },
    agent: {
      max_turns: 30,
      reasoning_effort: "medium",
    },
    memory: {
      memory_enabled: true,
      user_profile_enabled: true,
    },
    skills: {
      creation_nudge_interval: 15,
    },
    // Explicit Slack toolset list so the session does not advertise browser
    // automation tools that are not intended for this sandbox workflow.
    platform_toolsets: {
      slack: [
        "web",
        "terminal",
        "file",
        "code_execution",
        "vision",
        "skills",
        "todo",
        "memory",
        "session_search",
        "clarify",
        "delegation",
        "cronjob",
        "tts",
      ],
    },
    display: {
      compact: false,
      tool_progress: "all",
      interim_assistant_messages: false,
      platforms: {
        slack: {
          tool_progress: "all",
        },
      },
    },
    approvals: {
      mode: "smart",
      timeout: 60,
    },
  };

  // Messaging platforms (if configured during onboard)
  const platformsConfig: Record<string, Record<string, unknown>> = {};
  for (const ch of msgChannels) {
    if (ch in TOKEN_ENV) {
      const pCfg: Record<string, unknown> = {
        enabled: true,
        token: `openshell:resolve:env:${TOKEN_ENV[ch]}`,
      };
      // allowed_users in config.yaml is not read by the gateway — see ALLOWED_USERS_ENV below
      platformsConfig[ch] = pCfg;
    }
  }

  if (Object.keys(platformsConfig).length > 0) {
    config.platforms = platformsConfig;
  }

  // API server — internal port only.
  // Hermes binds to 127.0.0.1 regardless of config (upstream bug).
  // socat in start.sh forwards 0.0.0.0:8642 -> 127.0.0.1:18642.
  const platforms = (config.platforms ?? {}) as Record<string, unknown>;
  platforms.api_server = {
    enabled: true,
    extra: {
      port: 18642,
      host: "127.0.0.1",
    },
  };
  config.platforms = platforms;

  // Write config.yaml — use inline YAML serialization (no external dep)
  const configPath = join(homedir(), ".hermes", "config.yaml");
  writeFileSync(configPath, toYaml(config));
  chmodSync(configPath, 0o600);

  // Write .env — API server config and messaging token placeholders
  const envLines: string[] = [
    "API_SERVER_PORT=18642",
    "API_SERVER_HOST=127.0.0.1",
    // Internal API key for session continuation (X-Hermes-Session-Id support).
    // The Outlook bridge uses this key to trigger on_session_finalize for ATIF/Phoenix.
    "API_SERVER_KEY=nemoclaw-internal",
  ];
  for (const ch of msgChannels) {
    if (ch in TOKEN_ENV) {
      envLines.push(`${TOKEN_ENV[ch]}=openshell:resolve:env:${TOKEN_ENV[ch]}`);
    }
    if (ch in EXTRA_TOKEN_ENV) {
      envLines.push(`${EXTRA_TOKEN_ENV[ch]}=openshell:resolve:env:${EXTRA_TOKEN_ENV[ch]}`);
    }
  }
  // Write allowed-user IDs so gateway _is_user_authorized reads them from env.
  for (const [ch, ids] of Object.entries(allowedIds)) {
    if (ch in ALLOWED_USERS_ENV && ids.length > 0) {
      envLines.push(`${ALLOWED_USERS_ENV[ch]}=${ids.map(String).join(",")}`);
    }
  }
  // Suppress the "no home channel" first-message prompt without setting a real channel.
  if (msgChannels.includes("slack")) {
    envLines.push("SLACK_HOME_CHANNEL=none");
  }
  if (msgChannels.includes("outlook")) {
    const sidecarPort = process.env.SIDECAR_LISTEN_PORT ?? "8766";
    envLines.push(`MS_GRAPH_SIDECAR_URL=http://127.0.0.1:${sidecarPort}`);
    envLines.push(`MS_GRAPH_SERVICES=${process.env.MS_GRAPH_SERVICES ?? "outlook"}`);
    for (const key of ["OUTLOOK_TARGET_MAILBOX", "OUTLOOK_REPLY_TO", "OUTLOOK_ALLOWED_SENDERS"]) {
      const value = process.env[key]?.trim();
      if (value) {
        envLines.push(`${key}=${value}`);
      }
    }
  }  
  for (const key of SOURCE_ETL_ENV) {
    const value = process.env[key]?.trim();
    if (value) {
      envLines.push(`${key}=${value}`);
    }
  }

  const envPath = join(homedir(), ".hermes", ".env");
  writeFileSync(envPath, envLines.length > 0 ? envLines.join("\n") + "\n" : "");
  chmodSync(envPath, 0o600);

  console.log(`[config] Wrote ${configPath} (model=${model}, provider=custom)`);
  console.log(`[config] Wrote ${envPath} (${envLines.length} entries)`);
}

/** Minimal YAML serializer for flat/nested objects — no external dependency. */
function toYaml(obj: Record<string, unknown>, indent: number = 0): string {
  const pad = "  ".repeat(indent);
  let out = "";
  for (const [key, value] of Object.entries(obj)) {
    if (value === null || value === undefined) {
      out += `${pad}${key}: null\n`;
    } else if (Array.isArray(value)) {
      if (value.length === 0) {
        out += `${pad}${key}: []\n`;
      } else {
        out += `${pad}${key}:\n`;
        for (const item of value) {
          if (item === null || item === undefined) {
            out += `${pad}  - null\n`;
          } else if (Array.isArray(item)) {
            out += `${pad}  - ${JSON.stringify(item)}\n`;
          } else if (typeof item === "object") {
            out += `${pad}  -\n`;
            out += toYaml(item as Record<string, unknown>, indent + 2);
          } else if (typeof item === "string") {
            out += `${pad}  - ${yamlString(item)}\n`;
          } else {
            out += `${pad}  - ${item}\n`;
          }
        }
      }
    } else if (typeof value === "object" && !Array.isArray(value)) {
      out += `${pad}${key}:\n`;
      out += toYaml(value as Record<string, unknown>, indent + 1);
    } else if (typeof value === "string") {
      out += `${pad}${key}: ${yamlString(value)}\n`;
    } else if (typeof value === "number" || typeof value === "boolean") {
      out += `${pad}${key}: ${value}\n`;
    }
  }
  return out;
}

/** Quote a YAML string if it contains special characters. */
function yamlString(s: string): string {
  if (/[:{}\[\],&*?|>!%@`#'"]/.test(s) || s.includes("\n") || s.trim() !== s) {
    return JSON.stringify(s);
  }
  return s;
}

main();
