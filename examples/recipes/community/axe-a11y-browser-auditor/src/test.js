// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import { validateUrl, redactSensitiveData, redactUrlParams } from './server.js';

describe('Security Features', () => {
  describe('validateUrl', () => {
    test('should block localhost and loopback', async () => {
      await assert.rejects(async () => validateUrl('http://localhost:8080'));
      await assert.rejects(async () => validateUrl('http://127.0.0.1'));
      await assert.rejects(async () => validateUrl('http://[::1]'));
      await assert.rejects(async () => validateUrl('http://0.0.0.0'));
    });

    test('should block IPv6 loopback and unique-local', async () => {
      await assert.rejects(async () => validateUrl('http://[::1]:8080'));
      await assert.rejects(async () => validateUrl('http://[fc00::1]'));
      await assert.rejects(async () => validateUrl('http://[fd00::1]'));
    });

    test('should block link-local addresses', async () => {
      await assert.rejects(async () => validateUrl('http://169.254.1.1'));
      await assert.rejects(async () => validateUrl('http://[fe80::1]'));
    });

    test('should block metadata IP and internal Docker networks', async () => {
      await assert.rejects(async () => validateUrl('http://169.254.169.254'));
      await assert.rejects(async () => validateUrl('http://host.docker.internal:9010'));
      await assert.rejects(async () => validateUrl('http://something.local'));
      await assert.rejects(async () => validateUrl('http://anything.nip.io'));
    });

    test('should block RFC1918 private IPs', async () => {
      await assert.rejects(async () => validateUrl('http://10.0.0.1'));
      await assert.rejects(async () => validateUrl('http://192.168.1.1'));
      await assert.rejects(async () => validateUrl('http://172.16.0.1'));
      await assert.rejects(async () => validateUrl('http://172.31.255.255'));
    });

    test('should block non-HTTP schemes', async () => {
      await assert.rejects(async () => validateUrl('ftp://example.com'));
      await assert.rejects(async () => validateUrl('file:///etc/passwd'));
      await assert.rejects(async () => validateUrl('javascript:alert(1)'));
    });

    test('should return hostname and resolvedAddresses for valid public URLs', async () => {
      const result = await validateUrl('https://example.com');
      assert.strictEqual(result.hostname, 'example.com');
      assert.ok(Array.isArray(result.resolvedAddresses));
      assert.ok(result.resolvedAddresses.length > 0);
    });

    test('should allow public IPs outside RFC1918', async () => {
      const result = await validateUrl('http://172.32.0.1');
      assert.strictEqual(result.hostname, '172.32.0.1');
    });
  });

  describe('redactSensitiveData', () => {
    test('should redact authorization headers', () => {
      const data = { 'authorization': 'Bearer secret123', 'content-type': 'application/json' };
      const redacted = redactSensitiveData(data);
      assert.strictEqual(redacted['authorization'], '[REDACTED]');
      assert.strictEqual(redacted['content-type'], 'application/json');
    });

    test('should redact cookie and set-cookie headers', () => {
      const data = { 'cookie': 'session=abc', 'set-cookie': 'token=xyz' };
      const redacted = redactSensitiveData(data);
      assert.strictEqual(redacted['cookie'], '[REDACTED]');
      assert.strictEqual(redacted['set-cookie'], '[REDACTED]');
    });

    test('should redact x-api-key headers', () => {
      const data = { 'x-api-key': 'sk-123', 'accept': 'text/html' };
      const redacted = redactSensitiveData(data);
      assert.strictEqual(redacted['x-api-key'], '[REDACTED]');
      assert.strictEqual(redacted['accept'], 'text/html');
    });
  });

  describe('redactUrlParams', () => {
    test('should strip query parameters', () => {
      assert.strictEqual(redactUrlParams('https://example.com/path?token=secret'), 'https://example.com/path?redacted');
      assert.strictEqual(redactUrlParams('https://example.com/path'), 'https://example.com/path');
    });

    test('should handle multiple query parameters', () => {
      assert.strictEqual(redactUrlParams('https://example.com?a=1&b=2'), 'https://example.com/?redacted');
    });
  });
});

describe('Integration - HTTP Server', () => {
  let baseUrl;
  let serverInstance;

  before(async () => {
    // Import and start the Express app on a random port
    const { app } = await import('./server.js');
    await new Promise((resolve) => {
      serverInstance = app.listen(0, '127.0.0.1', () => {
        const addr = serverInstance.address();
        baseUrl = `http://127.0.0.1:${addr.port}`;
        resolve();
      });
    });
  });

  after(async () => {
    if (serverInstance) {
      await new Promise((resolve) => serverInstance.close(resolve));
    }
  });

  test('GET /healthz should return ok', async () => {
    const res = await fetch(`${baseUrl}/healthz`);
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.status, 'ok');
  });

  test('POST /mcp with tools/list should return tools', async () => {
    const res = await fetch(`${baseUrl}/mcp`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
          protocolVersion: '2025-03-26',
          capabilities: {},
          clientInfo: { name: 'test', version: '1.0.0' },
        },
      }),
    });
    assert.strictEqual(res.status, 200);
  });

  test('GET /artifacts/nonexistent should return 404', async () => {
    const res = await fetch(`${baseUrl}/artifacts/nonexistent.png`);
    assert.ok([403, 404].includes(res.status));
  });
});
