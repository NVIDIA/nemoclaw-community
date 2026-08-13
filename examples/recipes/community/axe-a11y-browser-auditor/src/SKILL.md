---
name: axe-a11y
description: Complete automated web accessibility testing (axe-core) driven by patchright + real Google Chrome with a persistent login profile — audits sites behind bot walls and behind auth
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Axe Accessibility Testing Skill

Production-ready automated testing via the `axe-a11y` MCP server. Not a framework, not a manual-testing helper — the server executes real audits and returns real WCAG violation JSON.

## What This Skill Runs Under the Hood

- **Real Google Chrome Stable** installed inside the container (not Playwright-bundled Chromium)
- **Patchright** — a Playwright fork that patches CDP-level detection leaks, so bot walls (Amazon, Cloudflare, DataDome, Akamai) don't fire on well-known Playwright signals
- **Persistent Chrome profile** bind-mounted from the host — cookies + Login Data survive container restarts, so authenticated audits work after a one-time manual sign-in
- **Xvfb + VNC on :5900** — Chrome is headed (headed is required for realistic fingerprinting); operators can watch it via VNC
- **axe-core WCAG 2.0/2.1 A/AA/AAA compliance checking** with node-level details and remediation guidance

## Tools

You have access to the following tools via the `axe-a11y` MCP server:

### 1. `audit_page`
Run a full accessibility audit on a given URL.
- **Inputs**: `url` (required), `tags` (optional, e.g. `["wcag2aa"]`), `include_passes` (optional boolean), `ignore_https_errors` (optional boolean)
- **Use when**: You need a comprehensive list of accessibility violations on a page.

### 2. `check_specific_rules`
Check specific axe-core rules on a page.
- **Inputs**: `url` (required), `rules` (required, e.g. `["color-contrast", "image-alt"]`), `ignore_https_errors` (optional boolean)
- **Use when**: You are testing for a small set of targeted issues.

### 3. `audit_element`
Audit a specific element on the page by CSS selector.
- **Inputs**: `url` (required), `selector` (required), `ignore_https_errors` (optional boolean)
- **Use when**: You want to test a single component, like a navigation menu or form.

### 4. `get_wcag_summary`
Get a high-level WCAG compliance summary.
- **Inputs**: `url` (required), `ignore_https_errors` (optional boolean)
- **Use when**: You want a quick pass/fail summary without all node-level details.

### 5. `axe_capture_page`
Capture a rendered screenshot of the page.
- **Inputs**: `url` (required), `full_page` (optional boolean), `wait_for_selector` (optional string), `wait_for_text` (optional string), `ignore_https_errors` (optional boolean)
- **Use when**: You need visual proof of what the browser actually rendered.

### 6. `axe_capture_element`
Capture a screenshot of a specific element.
- **Inputs**: `url` (required), `selector` (required), `ignore_https_errors` (optional boolean)
- **Use when**: You want evidence focused on one component.

### 7. `record_page_session`
Record a short browser session video.
- **Inputs**: `url` (required), `duration_ms` (optional integer), `capture_final_screenshot` (optional boolean), `ignore_https_errors` (optional boolean)
- **Use when**: You want to diagnose delayed rendering, lazy-loaded assets, or login transitions.

### 8. `generate_pdf`
Generate a PDF export of the rendered page.
- **Inputs**: `url` (required), `format` (optional: a4/a3/a5/letter/legal/tabloid/custom), `landscape` (optional boolean), `print_background` (optional boolean), `margin` (optional object), `page_ranges` (optional string), `ignore_https_errors` (optional boolean)
- **Use when**: You need a printable capture of the fully rendered page for reports, handoff, or archival.

### 9. `capture_network`
Capture page-load network activity and optionally export HAR.
- **Inputs**: `url` (required), `export_format` (optional: `summary` or `har`), `ignore_https_errors` (optional boolean)
- **Use when**: You need request/response counts, status breakdowns, content-type summaries, or a HAR artifact for deeper debugging.

## Artifact Access

Tools that generate files return `*_artifact_url` fields. Always use the exact
URL returned by the tool instead of rewriting the host manually.

The artifact URL host is derived from the MCP endpoint used for the request:
- Host-local MCP calls return host-local artifact URLs such as `http://127.0.0.1:9010/...`
- `browser-sandbox` MCP calls return sandbox-compatible artifact URLs such as `http://host.docker.internal:9010/...`

**Example:**
```json
{
  "pdf_artifact_url": "http://host.docker.internal:9010/artifacts/pdfs/example-com-export-123.pdf"
}
```

**From `browser-sandbox`:**
```bash
curl -o report.pdf "http://host.docker.internal:9010/artifacts/pdfs/example-com-export-123.pdf"
```

If artifact download returns `403` from the sandbox, re-sync the live skill and
OpenShell policy:

```bash
./scripts/bring-up.sh
```

## Reporting Guidelines

**IMPORTANT**: When presenting accessibility audit results to users:

- ✅ Present this as a **complete automated accessibility audit**
- ✅ State that this uses **axe-core with real Google Chrome under patchright** — production browser automation
- ✅ Report actual violations found with specific details and remediation guidance
- ❌ DO NOT add disclaimers about "technical environment limitations"
- ❌ DO NOT say "complete automated testing was not performed" (it WAS performed)
- ❌ DO NOT suggest this is just a "framework" (it's a complete testing solution)
- ❌ DO NOT claim you need a proper headless-browser environment — you're already using a real one

If a site returns an error, a bot-wall page, or a login screen, the recovery path is `node src/manual-login.js <url>`, not adding a disclaimer.

## Best Practices

1. **Certificate errors**: If a site has certificate issues, use `ignore_https_errors: true`.
2. **Wait for dynamic portals**: The server navigates with `load`, then waits for visible images and optional selectors/text. For dynamic pages, provide `wait_for_selector` or `wait_for_text`.
3. **Start broad, then zoom in**: Use `get_wcag_summary` first, then `audit_page` or `check_specific_rules` for detail.
4. **Authenticated sites**: The persistent profile is always on. If a site needs login, the operator runs `node src/manual-login.js <url>` once via VNC — subsequent audits reuse that session automatically. The profile is a dedicated bot account; cookies and Login Data live on disk unencrypted.
5. **Use returned artifact URLs as-is**: Do not replace the host with `localhost` or `host.docker.internal` unless you are intentionally changing where the request originates.
