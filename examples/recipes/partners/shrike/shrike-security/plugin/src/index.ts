// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Shrike Action Governance — OpenClaw plugin.
//
// Registers a `before_tool_call` hook on the OpenClaw runtime. Every tool call
// is classified and sent to Shrike's enforce plane BEFORE it executes; a block
// verdict is returned to OpenClaw as `{ block: true, blockReason }`, which stops
// the call. This is the supported OpenClaw plugin interception path (the same
// contract NemoClaw's own secret-scanner uses) — NOT a Claude-style `PreToolUse`
// settings.json hook, which the OpenClaw runtime does not load.
//
// SCOPE: this is IN-SANDBOX defense-in-depth, not an independent security
// boundary. The plugin runs inside the sandbox alongside the agent; a fully
// compromised sandbox could tamper with it. The independent controls remain the
// OpenShell egress policy + credential provider (see providers/shrike.yaml).
//
// The plugin never holds the Shrike key. Auth uses the placeholder
// `openshell:resolve:env:SHRIKE_API_KEY`; the OpenShell L7 proxy substitutes the
// real key on egress to the scoped Shrike host. The HTTP call shells out to
// `curl` (a synchronous, blocking round-trip) so it rides the sandbox's
// OpenShell proxy + CA — Node's global fetch/https bypass them.
//
// Types are declared structurally here (mirroring the OpenClaw plugin contract)
// so this module compiles without importing the `openclaw` package, exactly as
// NemoClaw's in-tree plugin does.

import { execFileSync } from "node:child_process";

// --- OpenClaw plugin contract (structural; see openclaw plugin types) --------

type ToolParams = Record<string, unknown>;

interface BeforeToolCallEvent {
  toolName?: string;
  params?: ToolParams;
  runId?: string;
  toolCallId?: string;
}

interface BeforeToolCallResult {
  params?: ToolParams;
  block?: boolean;
  blockReason?: string;
}

interface PluginLogger {
  info: (message: string) => void;
  warn: (message: string) => void;
  debug: (message: string) => void;
  error: (message: string) => void;
}

interface OpenClawPluginApi {
  logger: PluginLogger;
  on: (
    hookName: string,
    handler: (
      ...args: readonly unknown[]
    ) => BeforeToolCallResult | undefined | Promise<BeforeToolCallResult | undefined>,
  ) => void;
}

// --- Config ------------------------------------------------------------------

const BASE = process.env.SHRIKE_BASE_URL ?? "https://api.shrikesecurity.com/agent";
// Fail mode when a verdict cannot be obtained. Shrike is fail-closed by posture,
// so the default is `closed` (deny). Operators may set SHRIKE_FAIL_MODE=open to
// prioritize availability; either way the OpenShell egress policy still contains
// the sandbox. This is applied to EVERY unresolved state — malformed event,
// unreachable enforce plane, unparseable/undecided response — so a failure never
// silently allows an action.
const FAIL_MODE = (process.env.SHRIKE_FAIL_MODE ?? "closed").toLowerCase();
const AUTH_HEADER = "Authorization: Bearer openshell:resolve:env:SHRIKE_API_KEY";
const TIMEOUT_MS = Number.parseInt(process.env.SHRIKE_TIMEOUT_MS ?? "12000", 10);

// --- Helpers -----------------------------------------------------------------

function asString(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return String(value);
}

/** Apply the CONFIGURED fail mode. Returns a block result unless fail-open. */
function failResult(reason: string): BeforeToolCallResult | undefined {
  if (FAIL_MODE === "open") return undefined; // allow
  return { block: true, blockReason: `Shrike: ${reason} — fail-closed` };
}

function readEvent(value: unknown): BeforeToolCallEvent | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const object = value as Record<string, unknown>;
  const params =
    typeof object.params === "object" && object.params !== null
      ? (object.params as ToolParams)
      : undefined;
  return {
    toolName: typeof object.toolName === "string" ? object.toolName : undefined,
    params,
  };
}

interface EnforceRequest {
  path: string;
  body: Record<string, unknown>;
}

/**
 * Route a tool call to the right Shrike enforce endpoint by tool name + params.
 * The specialized endpoint applies the correct context (SQL vs command vs file
 * vs web), which the general prompt-shaped endpoint does not.
 */
function route(toolName: string, params: ToolParams): EnforceRequest {
  const tool = toolName.toLowerCase();

  // `query` is overloaded — SQL tools AND web_search both use it. Only treat it
  // as SQL when there's an explicit `sql` param or a genuinely SQL-ish tool
  // name; otherwise it falls through to the web_search branch below. The bare
  // word "query" is deliberately NOT a SQL tool signal: web_search is a "query"
  // too, and misrouting it to the `sql` content_type drops overarching
  // detectors (e.g. secrets_exposure), which would let a secret-exfil search
  // through. Specialized routing must never subtract a universal check.
  const isSqlTool = /sql|database|\bdb\b/.test(tool);
  const sql = params.sql ?? (isSqlTool ? params.query : undefined);
  if (sql || isSqlTool) {
    return {
      path: "/api/scan/enforce/specialized",
      body: { content: asString(sql ?? params.command), content_type: "sql" },
    };
  }

  const command = params.command ?? params.cmd;
  if (command || /exec|bash|shell|command|terminal|run/.test(tool)) {
    return {
      path: "/api/scan/enforce/specialized",
      body: { content: asString(command), content_type: "command" },
    };
  }

  const fileContent = params.file_text ?? params.content;
  const filePath = params.path ?? params.file_path;
  if (fileContent && (filePath || /write|edit|create.?file|save/.test(tool))) {
    return {
      path: "/api/scan/enforce/specialized",
      body: { content: asString(fileContent), content_type: "file_write" },
    };
  }

  if (params.url || /web.?search|fetch|browse|http/.test(tool)) {
    return {
      path: "/api/scan/enforce/specialized",
      body: { content: asString(params.url ?? params.query), content_type: "web_search" },
    };
  }

  const general =
    params.content ?? params.text ?? params.prompt ?? (Object.keys(params).length ? JSON.stringify(params) : "");
  return { path: "/api/scan/enforce", body: { prompt: asString(general), scan_type: "full" } };
}

/** Synchronous, blocking enforce call via curl (rides the OpenShell proxy/CA). */
function enforce(request: EnforceRequest): Record<string, unknown> {
  const seconds = String(Math.max(1, Math.ceil(TIMEOUT_MS / 1000)));
  const out = execFileSync(
    "curl",
    [
      "-s",
      "--max-time",
      seconds,
      "--connect-timeout",
      "6",
      "-X",
      "POST",
      BASE + request.path,
      "-H",
      "Content-Type: application/json",
      "-H",
      AUTH_HEADER,
      "-d",
      JSON.stringify(request.body),
    ],
    { encoding: "utf8", timeout: TIMEOUT_MS + 3000 },
  );
  return JSON.parse(out) as Record<string, unknown>;
}

// --- Plugin entry point ------------------------------------------------------

export default function register(api: OpenClawPluginApi): void {
  api.logger.info("[shrike] action-governance plugin registered (before_tool_call)");

  api.on("before_tool_call", (...args: readonly unknown[]): BeforeToolCallResult | undefined => {
    const event = readEvent(args[0]);
    if (!event?.toolName || !event.params) {
      // #5 fix: a malformed/unparseable event must apply the configured fail
      // mode, never silently allow (the previous PreToolUse hook always allowed).
      return failResult("unparseable tool-call event");
    }

    const request = route(event.toolName, event.params);
    const content = request.body.content ?? request.body.prompt;
    if (typeof content !== "string" || content.length === 0) {
      // No action content to evaluate (e.g. a read/list) — allow.
      return undefined;
    }
    request.body.context = { source: "nemoclaw-shrike-plugin", tool: event.toolName };

    let response: Record<string, unknown>;
    try {
      response = enforce(request);
    } catch (error) {
      api.logger.warn(
        `[shrike] enforce plane unreachable: ${error instanceof Error ? error.message : String(error)}`,
      );
      return failResult("enforce plane unreachable");
    }

    const action = asString(response.action).toLowerCase();
    if (action === "allow" || action === "warn") return undefined;

    if (action === "block" || action === "require_approval") {
      const recovery = response.recovery;
      const instruction =
        typeof recovery === "object" &&
        recovery !== null &&
        typeof (recovery as Record<string, unknown>).instruction === "string"
          ? ((recovery as Record<string, unknown>).instruction as string)
          : `Blocked by Shrike action governance (${asString(response.threat_level) || "policy"}).`;
      // Log tool name + severity only — never action content (Cloud Logging is
      // not covered by at-rest encryption).
      api.logger.warn(`[shrike] blocked ${event.toolName} (${asString(response.threat_level) || "policy"})`);
      return { block: true, blockReason: instruction };
    }

    // Unrecognized / missing decision — apply the configured fail mode.
    return failResult("no decision from enforce plane");
  });
}
