# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json, hashlib, os, time, base64

p   = '/sandbox/.openclaw/openclaw.json'
hp  = '/sandbox/.openclaw/.config-hash'
hp2 = '/sandbox/.openclaw/logs/config-health.json'

uid = os.environ.get('TELEGRAM_USER_ID', '')
uids = [u.strip() for u in uid.split(',') if u.strip()]
bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
streaming_mode  = os.environ.get('OPENCLAW_STREAMING_MODE', 'partial')
tool_progress   = os.environ.get('OPENCLAW_TOOL_PROGRESS', 'false').lower() == 'true'
max_tokens      = int(os.environ.get('OPENCLAW_MAX_TOKENS', '8192'))
cfg = json.loads(open(p).read())

# Ensure the channels key exists
cfg.setdefault('channels', {}).setdefault('defaults', {})
tg = cfg['channels'].setdefault('telegram', {})
tg['enabled'] = True
acct = tg.setdefault('accounts', {}).setdefault('default', {})
acct['botToken'] = bot_token
acct['enabled'] = True
acct['dmPolicy'] = 'allowlist'
acct['allowFrom'] = uids
acct['groupPolicy'] = 'open'
acct['healthMonitor'] = {'enabled': False}
acct.pop('proxy', None)
acct.pop('typingAction', None)  # Removed in OpenClaw v2026.5.18 schema

tg['streaming'] = {
    'mode': streaming_mode,
    'preview': {
        'toolProgress': tool_progress
    }
}

# Debounce rapid inbound messages to prevent session takeover errors
msgs = cfg.setdefault('messages', {})
msgs.setdefault('inbound', {})['debounceMs'] = 3000

# Increase max output tokens (default 4096 can exhaust on long tool outputs).
# Must be set per-model inside models.providers, NOT at root level —
# root-level "inference" key causes "<root>: Invalid input" on gateway startup.
for prov in cfg.get('models', {}).get('providers', {}).values():
    for m in prov.get('models', []):
        m['maxTokens'] = max_tokens

# Ensure the nemoclaw plugin stays enabled (it provides the exec tool).
# The plugin was already force-installed with --dangerously-force-unsafe-install
# at install time. We just need to make sure it's not accidentally disabled.
# NOTE: Do NOT set plugins.allow — it acts as a whitelist and blocks ALL
# built-in plugins (browser, canvas, file-transfer, memory-core, etc.)
# that are needed for tool execution to work.
plugins = cfg.setdefault('plugins', {})
plugins.pop('allow', None)  # Remove any stale allowlist
entries = plugins.setdefault('entries', {})
entries.setdefault('nemoclaw', {})['enabled'] = True

# Deny web_fetch and browser tools so the agent is forced to use bash + curl.
tools = cfg.setdefault('tools', {})
deny = tools.setdefault('deny', [])
for blocked in ['web_fetch', 'browser']:
    if blocked not in deny:
        deny.append(blocked)

# [v0.0.50 Fix #2] Disable tool search proxy — breaks exec tool flow
tools['toolSearch'] = False

# Add ingress host to allowedOrigins so the dashboard is accessible
# from outside the cluster via the nginx ingress.
# Must be under gateway.controlUi.allowedOrigins (NOT at the config root).
dashboard_url = os.environ.get('CHAT_UI_URL', '').rstrip('/')
if dashboard_url:
    gw = cfg.setdefault('gateway', {})
    cui = gw.setdefault('controlUi', {})
    origins = cui.setdefault('allowedOrigins', [])
    if dashboard_url not in origins:
        origins.append(dashboard_url)

# Keep the default inference.local baseUrl — the inference_local network policy
# allows the L7 proxy to reach it, and DNS + iptables route it to the workspace vLLM proxy.

u = json.dumps(cfg, indent=2)
open(p, 'w').write(u)
h = hashlib.sha256(u.encode()).hexdigest()
open(hp, 'w').write(h + '  ' + p + '\n')

# Write config-health.json so that if the sandbox pod ever restarts,
# openshell-sandbox will trust openclaw.json and auto-start openclaw.
s = os.stat(p)
now_iso = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
entry = {'hash': h, 'bytes': s.st_size, 'mtimeMs': s.st_mtime * 1000,
         'ctimeMs': s.st_ctime * 1000, 'dev': str(s.st_dev),
         'ino': str(s.st_ino), 'mode': s.st_mode, 'nlink': s.st_nlink,
         'uid': s.st_uid, 'gid': s.st_gid, 'hasMeta': True,
         'gatewayMode': 'local', 'observedAt': now_iso}
health = {'entries': {p: {'lastKnownGood': entry,
                          'lastObservedSuspiciousSignature': None,
                          'lastPromotedGood': entry}}}
os.makedirs('/sandbox/.openclaw/logs', exist_ok=True)
open(hp2, 'w').write(json.dumps(health, indent=2) + '\n')
os.chown(hp2, s.st_uid, s.st_gid)
print('[Telegram] openclaw.json patched, allowFrom=' + uid + ', proxy removed, config-health updated')

# Write workspace identity files if provided (base64-encoded via env vars).
workspace_dir = '/sandbox/.openclaw/workspace'
os.makedirs(workspace_dir, exist_ok=True)

soul_b64 = os.environ.get('SOUL_B64', '')
if soul_b64:
    soul_content = base64.b64decode(soul_b64).decode('utf-8')
    open(os.path.join(workspace_dir, 'SOUL.md'), 'w').write(soul_content)
    # OpenClaw also looks for SOUL.md in the root .openclaw dir
    open('/sandbox/.openclaw/SOUL.md', 'w').write(soul_content)
    print('[Workspace] SOUL.md written')

user_b64 = os.environ.get('USER_B64', '')
if user_b64:
    open(os.path.join(workspace_dir, 'USER.md'), 'w').write(
        base64.b64decode(user_b64).decode('utf-8'))
    print('[Workspace] USER.md written')

agents_b64 = os.environ.get('AGENTS_B64', '')
if agents_b64:
    open(os.path.join(workspace_dir, 'AGENTS.md'), 'w').write(
        base64.b64decode(agents_b64).decode('utf-8'))
    print('[Workspace] Custom AGENTS.md written')
