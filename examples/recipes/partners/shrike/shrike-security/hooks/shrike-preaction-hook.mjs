#!/usr/bin/env node
// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Shrike Security — OpenClaw PreToolUse hook.
//
// Runs INSIDE the sandbox before every matched tool call. Classifies the action,
// sends it to Shrike's enforce plane, and returns an OpenClaw permission decision.
// The agent never holds the Shrike key: auth uses the placeholder
// `openshell:resolve:env:SHRIKE_API_KEY`; the OpenShell L7 proxy substitutes the
// real key on egress to api.shrikesecurity.com. The HTTP call shells out to curl
// so it rides the sandbox's OpenShell proxy + CA (node's https bypasses them).
//
// stdin : { hook_event_name, tool_name, tool_input, ... }
// stdout: { hookSpecificOutput: { hookEventName:"PreToolUse",
//           permissionDecision:"allow"|"deny", permissionDecisionReason } }
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

// Fail mode when a verdict can't be obtained. Shrike is fail-closed by brand,
// so default to deny; operators can set SHRIKE_FAIL_MODE=open for availability
// (the OpenShell network policy still contains egress either way).
const FAIL_MODE = (process.env.SHRIKE_FAIL_MODE || 'closed').toLowerCase();
const BASE = 'https://api.shrikesecurity.com/agent';

function emit(decision, reason) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: decision,          // "allow" | "deny"
      permissionDecisionReason: reason,
    },
  }) + '\n');
  process.exit(0);
}

let ev = {};
try { ev = JSON.parse(fs.readFileSync(0, 'utf8') || '{}'); }
catch { emit('allow', 'Shrike: unparseable hook payload — passing through'); }

const tool = (ev.tool_name || ev.toolName || '').toLowerCase();
const input = ev.tool_input || ev.toolInput || {};

// Route the action to the right Shrike scanner by tool/content shape.
// Specialized endpoint applies proper context (SQL vs command vs file), which
// the general /enforce (prompt-shaped) does not.
function route() {
  if (input.sql || /sql|query|database|\bdb\b/.test(tool)) {
    return { path: '/api/scan/enforce/specialized', body: { content: String(input.sql || input.query || input.command || ''), content_type: 'sql' } };
  }
  if (input.command || input.cmd || /exec|bash|shell|command|terminal|run/.test(tool)) {
    return { path: '/api/scan/enforce/specialized', body: { content: String(input.command || input.cmd || ''), content_type: 'command' } };
  }
  if ((input.file_text || input.content) && (input.path || input.file_path || /write|edit|create.?file|save/.test(tool))) {
    return { path: '/api/scan/enforce/specialized', body: { content: String(input.file_text || input.content || ''), content_type: 'file_write' } };
  }
  if (input.url || /web.?search|fetch|browse|http/.test(tool)) {
    return { path: '/api/scan/enforce/specialized', body: { content: String(input.url || input.query || ''), content_type: 'web_search' } };
  }
  // Fallback: general enforce over whatever content we can see.
  const content = input.content || input.text || input.prompt ||
    (Object.keys(input).length ? JSON.stringify(input) : String(ev.prompt || ''));
  return { path: '/api/scan/enforce', body: { prompt: String(content), scan_type: 'full' } };
}

const r = route();
if (r.body.content === '' && r.body.content_type !== 'sql' && !r.body.prompt) {
  emit('allow', 'Shrike: no action content to evaluate');
}
r.body.context = { source: 'nemoclaw-preaction-hook', tool };

let out;
try {
  out = execFileSync('curl', [
    '-s', '--max-time', '12', '--connect-timeout', '6',
    '-X', 'POST', BASE + r.path,
    '-H', 'Content-Type: application/json',
    '-H', 'Authorization: Bearer openshell:resolve:env:SHRIKE_API_KEY',
    '-d', JSON.stringify(r.body),
  ], { encoding: 'utf8', timeout: 15000 });
} catch (e) {
  emit(FAIL_MODE === 'open' ? 'allow' : 'deny',
    `Shrike enforce unreachable (${(e && e.message) || 'error'}) — fail-${FAIL_MODE}`);
}

let resp = {};
try { resp = JSON.parse(out); } catch {}
const action = (resp.action || '').toLowerCase();
if (action === 'allow' || action === 'warn') {
  emit('allow', `Shrike: ${action} (${resp.threat_level || 'none'})`);
} else if (action === 'block' || action === 'require_approval') {
  const why = (resp.recovery && resp.recovery.instruction) ||
    `Blocked by Shrike action governance (${resp.threat_level || 'policy'}).`;
  emit('deny', why);
} else {
  emit(FAIL_MODE === 'open' ? 'allow' : 'deny',
    `Shrike: no decision — fail-${FAIL_MODE}`);
}
