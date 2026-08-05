// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const fs = require('fs');
const crypto = require('crypto');
const p = '/root/.nemoclaw/sandboxes.json';
if (!fs.existsSync(p)) {
  console.log('[Telegram] sandboxes.json not found, skipping');
  process.exit(0);
}
const d = JSON.parse(fs.readFileSync(p, 'utf8'));
const name = process.env.NEMOCLAW_SANDBOX_NAME || 'retail-assistant';
const s = d.sandboxes[name];
if (!s) {
  console.log('[Telegram] sandbox entry not found, skipping');
  process.exit(0);
}
const h = crypto.createHash('sha256').update(process.env.TELEGRAM_BOT_TOKEN).digest('hex');
s.messagingChannels = ['telegram'];
s.policies = [...new Set([...(s.policies || []), 'telegram'])];
s.providerCredentialHashes = s.providerCredentialHashes || {};
s.providerCredentialHashes.TELEGRAM_BOT_TOKEN = h;
fs.writeFileSync(p, JSON.stringify(d, null, 2));
console.log('[Telegram] sandboxes.json patched');
