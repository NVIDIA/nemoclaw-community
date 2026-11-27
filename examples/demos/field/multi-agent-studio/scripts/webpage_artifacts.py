# SPDX-License-Identifier: Apache-2.0

"""Attach verified HTML outputs to the chat that produced them."""
import hashlib
import json
import os
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

DEMO_CODING_INSTRUCTIONS = (
    '\nDEMO CODING PACE: implement the requested core in one clear desktop layout. '
    'Use fluid width/max-width, scale a canvas within its container, and give wide tables their own '
    'horizontal scroll area. These handle a narrow desktop preview without a mobile version. '
    'Do not add phone/tablet @media rules or touch UI unless the user asks for those devices. '
    'Omit themes, decorative animation, sound, persistence and extra settings unless requested. '
    'Keep animation essential to the requested behavior, such as a game\'s update loop. '
    'For a static chart, prefer plain HTML/CSS or inline SVG so it renders without a chart library. '
    'Do not design or test additional devices. '
    'Read relevant inputs once and write one complete usable implementation, using shared data/functions '
    'instead of duplicated markup. Check the core flow while composing. After saving, return; use a '
    'targeted edit only for a concrete defect or missing requirement. No save-confirmation rereads, '
    'alternate versions, cosmetic passes or unsolicited review reports. Keep required functionality '
    'over a size target. Put the handoff note (path and limitations, under 80 words) in your chat reply. '
    'Keep the saved HTML intact.\n'
)

PAGE_INSTRUCTIONS = (
    '\nWhen a webpage is requested, save one complete self-contained HTML file in artifacts/ with '
    'inline CSS/JavaScript. The preview has no network access: no CDN, external images or libraries. '
    'Use browser-native APIs; draw charts with CSS, SVG or canvas. No library globals are preloaded. '
    'It uses sandbox="allow-scripts allow-forms" with an opaque origin and form-action none; '
    'local forms must prevent submission. Never require parent access. If persistence was requested, '
    'guard storage with try/catch and an in-memory fallback. '
    'For interactive controls, preserve requested input ranges, reject blank/non-finite numeric values, '
    'and keep state and displayed results in sync. For games, preserve simultaneous keys, release on '
    'blur/page hiding, and a restart that clears input/timers without duplicating animation loops. '
    'Without a backend, confirmations describe only local demo actions, never sent emails or bookings. '
    'A successful native write proves delivery, not browser testing; do not claim unperformed checks. '
    'If writing is unavailable, return the complete document in a fenced html block and say it was not saved. '
    'Do not create a webpage unless requested.\n'
)


def html_files(workspace):
    from studio import safe_file, Problem
    folder = workspace / 'artifacts'
    if folder.is_symlink() or not folder.is_dir():
        return {}
    found = {}
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(root) / d).is_symlink())
        for name in sorted(files):
            if not name.lower().endswith('.html'):
                continue
            relative = str((Path(root) / name).relative_to(workspace))
            try:
                path = safe_file(workspace, relative, True)
                raw = path.read_bytes()
                raw.decode('utf-8')
                found[relative] = (hashlib.sha256(raw).hexdigest(), path.stat().st_mtime_ns)
            except (Problem, OSError, UnicodeError):
                continue
    return found


class _PageScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.kind = None
        self.scripts = []
        self.inert = []

    def handle_starttag(self, tag, attrs):
        if tag in ('template', 'textarea', 'noscript', 'xmp', 'svg', 'math', 'title', 'iframe'):
            self.inert.append(tag)
        elif tag == 'script' and not self.inert:
            attrs = dict(attrs)
            kind = (attrs.get('type') or '').strip().lower()
            if 'src' not in attrs and kind in ('', 'text/javascript', 'application/javascript', 'module'):
                self.kind = kind

    def handle_data(self, data):
        if self.kind is not None:
            self.scripts.append([self.kind, data])

    def handle_endtag(self, tag):
        if self.inert and self.inert[-1] == tag:
            self.inert.pop()
        elif tag == 'script':
            self.kind = None


def script_syntax_error(raw):
    """Check ordinary standalone scripts without running the generated page or resolving imports."""
    if len(raw) > 1024 * 1024 or b'<script' not in raw.lower():
        return ''
    parser = _PageScripts()
    try:
        parser.feed(raw.decode('utf-8'))
        parser.close()
    except (ValueError, AssertionError):
        return ''
    if not parser.scripts:
        return ''
    from agent_runtime import root
    node = root() / 'node/bin/node'
    binary = str(node) if node.is_file() else shutil.which('node')
    if not binary:
        return ''
    try:
        check = subprocess.run([binary, '--no-warnings', '--experimental-vm-modules',
                                str(Path(__file__).with_name('check_page_scripts.mjs'))],
                               input=json.dumps(parser.scripts), text=True, capture_output=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return check.stdout.strip()[:240] if check.returncode == 2 else ''


def collect_pages(studio, owner, job_id, role, before, answer, source_map=None, *, source_workspace=None, validation_errors=None):
    """Export changed pages into job-specific immutable, account-owned paths.

    Never trust paths mentioned in a model reply. Only actual artifact files or
    complete HTML documents returned by the model can become previews.
    """
    from studio import safe_file, Problem
    workspace = source_workspace if source_workspace is not None else studio.workspace(owner, role)
    sources = []
    source_names = {}
    for relative, signature in html_files(workspace).items():
        if before.get(relative) == signature:
            continue
        try:
            raw = safe_file(workspace, relative, True).read_bytes()
            # Do not attach a file that changed during collection.
            content = raw.decode('utf-8')
            if hashlib.sha256(raw).hexdigest() != signature[0]:
                continue
            if not (re.search(r'<html\b', content, re.I) and re.search(r'</html\s*>', content, re.I)):
                if validation_errors is not None:
                    validation_errors.append(relative + ': the file was saved but does not contain a complete HTML document. '
                                             'Write the full page to this file and put the handoff note in your reply.')
                continue
            sources.append(raw)
            source_names[hashlib.sha256(raw.strip()).hexdigest()] = relative
        except (Problem, OSError, UnicodeError):
            continue
    # A model without file tools can still supply a complete HTML deliverable.
    for match in re.finditer(r'^```html\s*\n([\s\S]*?)^```\s*$', str(answer), re.I | re.M):
        content = match.group(1).strip()
        if re.search(r'<html\b', content, re.I) and re.search(r'</html\s*>', content, re.I):
            raw = content.encode('utf-8')
            if len(raw) <= 10 * 1024 * 1024:
                sources.append(raw)
    paths, seen = [], set()
    label = 'personal' if role is None else 'r' + str(role)
    for raw in sources:
        digest = hashlib.sha256(raw.strip()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        if validation_errors is not None:
            error = script_syntax_error(raw)
            if error:
                validation_errors.append(source_names.get(digest, 'HTML page') + ': ' + error)
                continue
        relative = 'artifacts/page-' + job_id + '-' + label + '-' + digest[:12] + '.html'
        safe_file(studio.workspace(owner), relative).write_bytes(raw)
        if source_map is not None and digest in source_names:
            source_map[relative] = source_names[digest]
        paths.append(relative)
    return paths
