// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Generate Hermes config.yaml and .env from NemoClaw build-arg env vars.
//
// Called at Docker image build time. Reads NEMOCLAW_* env vars and writes:
//   ~/.hermes/config.yaml  — Hermes configuration (immutable at runtime)
//   ~/.hermes/.env         — Messaging token placeholders (immutable at runtime)
//
// Per-user identity/allowlist values (OUTLOOK_TARGET_MAILBOX/REPLY_TO/
// ALLOWED_SENDERS, SLACK_ALLOWED_USERS/ALLOW_ALL_USERS) are NOT written here —
// they are injected at sandbox-create time via `-- env` (scripts/03-sandbox.sh)
// so the built image stays generic. The gateway/bridge read them from os.environ.
//
// Sets what's required for Hermes to run inside OpenShell:
//   - Model and inference endpoint (Hermes calls OpenShell's `inference.local`
//     route, bound to the `compatible-endpoint` provider by `openshell inference set`)
//   - API server on internal port (socat forwards to public port)
//   - Messaging platform tokens (if configured during onboard)
//   - Agent defaults (terminal, memory, skills, display)
//   - Slack-facing UX tweaks (less mid-turn chatter, no browser tool exposure)
//   - Optional search-only Tavily backend with an OpenShell placeholder

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

const SOURCE_ETL_ENV = [
  "SOURCE_ETL_GITHUB_REPO",
  "SOURCE_ETL_FORUM_TAG",
  "SOURCE_ETL_API_URL",
  "SOURCE_ETL_API_HOST",
  "SOURCE_ETL_API_PORT",
] as const;

function booleanEnv(name: string, defaultValue: boolean): boolean {
  const raw = process.env[name];
  if (raw === undefined || raw === "") {
    return defaultValue;
  }

  if (raw === "true") {
    return true;
  }
  if (raw === "false") {
    return false;
  }

  throw new Error(`${name} must be either true or false`);
}

function main(): void {
  const model = process.env.NEMOCLAW_MODEL!;
  const baseUrl = process.env.NEMOCLAW_INFERENCE_BASE_URL!;
  const slackRichBlocks = booleanEnv("NEMOCLAW_SLACK_RICH_BLOCKS", true);
  const webSearchProvider = (
    process.env.NEMOCLAW_WEB_SEARCH_PROVIDER || ""
  ).trim();
  if (webSearchProvider !== "" && webSearchProvider !== "tavily") {
    throw new Error('NEMOCLAW_WEB_SEARCH_PROVIDER must be empty or "tavily"');
  }

  const channelsB64 = process.env.NEMOCLAW_MESSAGING_CHANNELS_B64 || "W10=";

  const msgChannels: string[] = JSON.parse(
    Buffer.from(channelsB64, "base64").toString("utf-8"),
  );

  const agentToolsets = [
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
  ];
  if (webSearchProvider === "tavily") {
    // Hermes's `search` toolset exposes web_search without web_extract.
    agentToolsets.unshift("search");
  }

  const config: Record<string, unknown> = {
    _config_version: 34,
    model: {
      default: model,
      provider: "custom",
      base_url: baseUrl,
    },
    terminal: {
      backend: "local",
      cwd: "/sandbox",
      timeout: 180,
    },
    agent: {
      max_turns: 30,
      reasoning_effort: "medium",
      // Config migration v30 -> v32 disables the previous implicit
      // verify-on-stop behavior. Generated configs start at v34, so preserve
      // that migrated value explicitly instead of inheriting "auto".
      verify_on_stop: false,
    },
    memory: {
      memory_enabled: true,
      user_profile_enabled: true,
    },
    skills: {
      creation_nudge_interval: 15,
    },
    // Explicit Slack toolset list so the session does not advertise browser
    // automation tools that are not intended for this sandbox workflow. When
    // search is enabled, apply the same search-only surface to the API server
    // used by the Outlook bridge.
    platform_toolsets: {
      slack: agentToolsets,
      ...(webSearchProvider === "tavily"
        ? { api_server: agentToolsets }
        : {}),
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
      mode: "off",
      timeout: 60,
    },
    // Hermes owns Relay's provider, tool, and session lifecycles in-process.
    // The bundled plugin loads the immutable plugins.toml selected by
    // HERMES_NEMO_RELAY_PLUGINS_TOML; no shell hooks or Relay daemon are used.
    plugins: {
      enabled: ["nemoclaw", "observability/nemo_relay"],
    },
  };

  if (webSearchProvider === "tavily") {
    config.web = { backend: "tavily" };
  }

  // Messaging platforms (if configured during onboard)
  const platformsConfig: Record<string, Record<string, unknown>> = {};
  for (const ch of msgChannels) {
    if (ch in TOKEN_ENV) {
      const tokenPlaceholder =
        ch === "slack" && TOKEN_ENV[ch] === "SLACK_BOT_TOKEN"
          ? "xoxb-OPENSHELL-RESOLVE-ENV-SLACK_BOT_TOKEN"
          : `openshell:resolve:env:${TOKEN_ENV[ch]}`;
      const pCfg: Record<string, unknown> = {
        enabled: true,
        token: tokenPlaceholder,
      };
      if (ch === "slack") {
        pCfg.extra = {
          rich_blocks: slackRichBlocks,
        };
      }
      // allowed_users in config.yaml is not read by the gateway; it reads the
      // *_ALLOWED_USERS env vars (injected at sandbox-create, not written here).
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

  // Write .env — API server config + messaging token placeholders.
  // No OPENAI_API_KEY: inference runs through OpenShell's `inference.local`
  // route, which injects the bearer at the gateway. The key never enters
  // the sandbox env.
  const envLines: string[] = [
    "API_SERVER_PORT=18642",
    "API_SERVER_HOST=127.0.0.1",
    // Internal API key used by the Outlook bridge to authenticate local API
    // requests and support X-Hermes-Session-Id continuation.
    "API_SERVER_KEY=nemoclaw-internal",
  ];
  if (webSearchProvider === "tavily") {
    envLines.push("TAVILY_API_KEY=openshell:resolve:env:TAVILY_API_KEY");
  }
  for (const ch of msgChannels) {
    if (ch in TOKEN_ENV) {
      if (ch === "slack" && TOKEN_ENV[ch] === "SLACK_BOT_TOKEN") {
        envLines.push("SLACK_BOT_TOKEN=xoxb-OPENSHELL-RESOLVE-ENV-SLACK_BOT_TOKEN");
      } else {
        envLines.push(`${TOKEN_ENV[ch]}=openshell:resolve:env:${TOKEN_ENV[ch]}`);
      }
    }
    if (ch in EXTRA_TOKEN_ENV) {
      if (ch === "slack" && EXTRA_TOKEN_ENV[ch] === "SLACK_APP_TOKEN") {
        envLines.push("SLACK_APP_TOKEN=xapp-OPENSHELL-RESOLVE-ENV-SLACK_APP_TOKEN");
      } else {
        envLines.push(`${EXTRA_TOKEN_ENV[ch]}=openshell:resolve:env:${EXTRA_TOKEN_ENV[ch]}`);
      }
    }
  }
  // Slack allowlist (SLACK_ALLOWED_USERS / SLACK_ALLOW_ALL_USERS) and the
  // Outlook per-user vars (OUTLOOK_TARGET_MAILBOX/REPLY_TO/ALLOWED_SENDERS) are
  // NOT written here — they are injected at sandbox-create time via `-- env`
  // (scripts/03-sandbox.sh) to keep the image generic. The gateway and the
  // Outlook bridge read them from os.environ.
  //
  // Suppress the "no home channel" first-message prompt without setting a real channel.
  if (msgChannels.includes("slack")) {
    envLines.push("SLACK_HOME_CHANNEL=none");
  }
  for (const key of SOURCE_ETL_ENV) {
    const value = process.env[key]?.trim();
    if (value) {
      envLines.push(`${key}=${value}`);
    }
  }
  const gitlabProjects = process.env.GITLAB_READONLY_PROJECTS?.trim();
  if (gitlabProjects) {
    const gitlabApiUrl = process.env.GITLAB_API_URL?.trim();
    const gitlabProjectIds = process.env.GITLAB_READONLY_PROJECT_IDS?.trim();
    if (!gitlabApiUrl || !gitlabProjectIds) {
      throw new Error(
        "GITLAB_API_URL and GITLAB_READONLY_PROJECT_IDS are required when GitLab is enabled",
      );
    }
    envLines.push(`GITLAB_READONLY_PROJECTS=${gitlabProjects}`);
    envLines.push(`GITLAB_API_URL=${gitlabApiUrl}`);
    envLines.push(`GITLAB_READONLY_PROJECT_IDS=${gitlabProjectIds}`);
    envLines.push("GITLAB_TOKEN=openshell:resolve:env:GITLAB_TOKEN");
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
