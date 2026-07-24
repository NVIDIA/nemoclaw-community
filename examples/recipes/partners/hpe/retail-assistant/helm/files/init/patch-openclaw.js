// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const fs = require('fs');
const crypto = require('crypto');
const p = '/sandbox/.openclaw/openclaw.json';
const hp = '/sandbox/.openclaw/.config-hash';
const cfg = JSON.parse(fs.readFileSync(p, 'utf8'));
const uid = process.env.TELEGRAM_USER_ID;
const acct = cfg.channels &&
             cfg.channels.telegram &&
             cfg.channels.telegram.accounts &&
             cfg.channels.telegram.accounts.default;
if (acct) {
  acct.dmPolicy = 'allowlist';
  acct.allowFrom = [uid];
  delete acct.proxy;
  const u = JSON.stringify(cfg, null, 2);
  fs.writeFileSync(p, u);
  const h = crypto.createHash('sha256').update(u).digest('hex');
  fs.writeFileSync(hp, h + '  ' + p + '\n');
  console.log('[Telegram] openclaw.json patched, allowFrom=' + uid + ', proxy removed');
} else {
  console.log('[Telegram] no telegram account found, skipping');
}
