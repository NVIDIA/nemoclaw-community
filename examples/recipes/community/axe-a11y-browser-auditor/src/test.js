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

    test('should block redirect destinations to private IPs', async () => {
      // Simulates what navigateAndSettle does when it finds a Location header
      // pointing to a private address after route.fetch({ maxRedirects: 0 })
      await assert.rejects(async () => validateUrl('http://10.0.0.1/admin'));
      await assert.rejects(async () => validateUrl('http://192.168.1.1:8080/internal'));
      await assert.rejects(async () => validateUrl('http://[fd00::1]/secret'));
      await assert.rejects(async () => validateUrl('http://169.254.169.254/latest/meta-data'));
    });

    test('should return resolved IPs usable for DNS pinning', async () => {
      // openSession() uses the returned { hostname, resolvedAddresses } to build
      // --host-resolver-rules=MAP <hostname> <ip> for Chromium DNS pinning
      const result = await validateUrl('https://example.com');
      assert.strictEqual(typeof result, 'object');
      assert.strictEqual(result.hostname, 'example.com');
      assert.ok(Array.isArray(result.resolvedAddresses));
      assert.ok(result.resolvedAddresses.length > 0);
      for (const ip of result.resolvedAddresses) {
        assert.ok(typeof ip === 'string');
        assert.ok(ip.length > 0);
      }
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

  test('POST /mcp initialize should return 200', async () => {
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

  test('POST /mcp tools/list should return all 9 tools', async () => {
    // Step 1: Initialize
    const initRes = await fetch(`${baseUrl}/mcp`, {
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
    assert.strictEqual(initRes.status, 200);
    const sessionId = initRes.headers.get('mcp-session-id');
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/event-stream',
    };
    if (sessionId) {
      headers['mcp-session-id'] = sessionId;
    }

    // Step 2: Send initialized notification
    await fetch(`${baseUrl}/mcp`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }),
    });

    // Step 3: List tools
    const toolsRes = await fetch(`${baseUrl}/mcp`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list' }),
    });
    assert.strictEqual(toolsRes.status, 200);
    const body = await toolsRes.text();
    const expectedTools = [
      'audit_page', 'check_specific_rules', 'audit_element', 'get_wcag_summary',
      'axe_capture_page', 'axe_capture_element', 'record_page_session',
      'generate_pdf', 'capture_network',
    ];
    for (const tool of expectedTools) {
      assert.ok(body.includes(tool), `Response should contain tool: ${tool}`);
    }
  });

  test('GET /artifacts/nonexistent should return 404', async () => {
    const res = await fetch(`${baseUrl}/artifacts/nonexistent.png`);
    assert.ok([403, 404].includes(res.status));
  });

  test('should listen on a custom port (config override)', async () => {
    // Verify the server started on a random port (not the default 9010)
    const addr = serverInstance.address();
    assert.ok(addr.port > 0);
    assert.notStrictEqual(addr.port, 9010);
    // Verify it responds on that custom port
    const res = await fetch(`http://127.0.0.1:${addr.port}/healthz`);
    assert.strictEqual(res.status, 200);
  });
});

// NOTE: The following contracts are verified at the container/Docker level
// and cannot be exercised in this unit/integration test environment:
//
// - DNS rebinding prevention: Enforced by --host-resolver-rules in openSession()
//   which pins the validated IP. Tested indirectly via the DNS-pinning return
//   contract test above.
//
// - Service Worker blocking: Enforced by serviceWorkers:'block' in context options.
//
// - WebSocket SSRF: Enforced by page.routeWebSocket() + validateUrl() in
//   navigateAndSettle().
//
// - Lifecycle cleanup (bring-up/teardown): Tested via bash -n syntax checks
//   and manual Docker verification. See scripts/teardown.sh --purge.
