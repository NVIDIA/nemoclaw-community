// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { test, describe } from 'node:test';
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
        test('should block metadata IP and internal Docker networks', async () => {
            await assert.rejects(async () => validateUrl('http://169.254.169.254'));
            await assert.rejects(async () => validateUrl('http://host.docker.internal:9010'));
            await assert.rejects(async () => validateUrl('http://something.local'));
        });
        test('should block RFC1918 private IPs', async () => {
            await assert.rejects(async () => validateUrl('http://10.0.0.1'));
            await assert.rejects(async () => validateUrl('http://192.168.1.1'));
            await assert.rejects(async () => validateUrl('http://172.16.0.1'));
            await assert.rejects(async () => validateUrl('http://172.31.255.255'));
        });
        test('should allow valid public http/https URLs', async () => {
            assert.strictEqual(await validateUrl('https://example.com'), true);
            // 172.32 is outside the RFC 1918 block
            assert.strictEqual(await validateUrl('http://172.32.0.1'), true);
        });
    });

    describe('redactSensitiveData', () => {
        test('should redact authorization headers', () => {
            const data = { 'authorization': 'Bearer secret123', 'content-type': 'application/json' };
            const redacted = redactSensitiveData(data);
            assert.strictEqual(redacted['authorization'], '[REDACTED]');
            assert.strictEqual(redacted['content-type'], 'application/json');
        });
    });

    describe('redactUrlParams', () => {
        test('should strip query parameters', () => {
            assert.strictEqual(redactUrlParams('https://example.com/path?token=secret'), 'https://example.com/path?redacted');
            assert.strictEqual(redactUrlParams('https://example.com/path'), 'https://example.com/path');
        });
    });
});
