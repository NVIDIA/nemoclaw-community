// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { expect } from 'chai';
import { validateUrl, redactSensitiveData, redactUrlParams } from './server.js';

describe('Security Features', () => {
    describe('validateUrl', () => {
        it('should block localhost and loopback', () => {
            expect(() => validateUrl('http://localhost:8080')).to.throw();
            expect(() => validateUrl('http://127.0.0.1')).to.throw();
            expect(() => validateUrl('http://::1')).to.throw();
            expect(() => validateUrl('http://0.0.0.0')).to.throw();
        });
        it('should block metadata IP', () => {
            expect(() => validateUrl('http://169.254.169.254')).to.throw();
        });
        it('should allow valid http/https URLs', () => {
            expect(validateUrl('https://example.com')).to.be.true;
        });
    });

    describe('redactSensitiveData', () => {
        it('should redact authorization headers', () => {
            const data = { 'authorization': 'Bearer secret123', 'content-type': 'application/json' };
            const redacted = redactSensitiveData(data);
            expect(redacted['authorization']).to.equal('[REDACTED]');
            expect(redacted['content-type']).to.equal('application/json');
        });
    });

    describe('redactUrlParams', () => {
        it('should strip query parameters', () => {
            expect(redactUrlParams('https://example.com/path?token=secret')).to.equal('https://example.com/path?redacted');
            expect(redactUrlParams('https://example.com/path')).to.equal('https://example.com/path');
        });
    });
});
