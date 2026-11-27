# SPDX-License-Identifier: Apache-2.0

"""Bounded NVIDIA Blog reads through the same curl binary allowed by OpenShell.

No host proxy, alternate transport, or cross-origin redirect fallback is added.
When invoked by Dylan, this module and curl execute inside his sandbox.
"""
from email.parser import BytesParser
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urljoin, urlsplit

RESEARCH_HOST = 'blogs.nvidia.com'
RESEARCH_APPROVALS = ('host:' + RESEARCH_HOST,)


def validate_url(url):
    value = urlsplit(url)
    if (value.scheme != 'https' or value.hostname != RESEARCH_HOST
            or value.port not in (None, 443) or value.username or value.password
            or any(ord(char) < 33 for char in url)):
        raise ValueError('Use an HTTPS NVIDIA Blog source URL.')
    return url


def fetch(url, *, limit=2_000_000, timeout=12):
    """Follow up to three same-origin redirects; every request stays policy gated."""
    with tempfile.TemporaryDirectory(prefix='bac-research-') as directory:
        body, headers = Path(directory) / 'body', Path(directory) / 'headers'
        for _ in range(4):
            validate_url(url)
            result = subprocess.run([
                '/usr/bin/curl', '--disable', '--silent', '--show-error', '--fail',
                '--proto', '=https', '--max-time', str(timeout), '--max-filesize', str(limit),
                '--user-agent', 'BaC-Agent-Research/1.0', '--dump-header', str(headers),
                '--output', str(body), '--write-out', '%{http_code}', '--url', url,
            ], capture_output=True, text=True, timeout=timeout + 3)
            if result.returncode:
                # Keep enough evidence to distinguish HTTP errors from policy denials.
                raise RuntimeError('Research GET failed (curl %d, HTTP %s): %s' % (
                    result.returncode, result.stdout.strip()[-3:], result.stderr.strip()[:300]))
            status = int(result.stdout.strip())
            if status in (301, 302, 303, 307, 308):
                blocks = headers.read_bytes().replace(b'\r\n', b'\n').strip().split(b'\n\n')
                fields = BytesParser().parsebytes(blocks[-1].split(b'\n', 1)[-1])
                location = fields.get('Location')
                if not location:
                    raise ValueError('Research redirect has no destination.')
                url = validate_url(urljoin(url, location))
                continue
            if status != 200:
                raise ValueError('Research returned HTTP ' + str(status))
            with body.open('rb') as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('Research response exceeds size limit.')
            return raw
    raise ValueError('Too many research redirects.')
