<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Development and verification

This page is for contributors who are changing the extension, Hermes plugin,
image preparation, or shared-deployment path.

## Installation approach

The supported recipe installs the Hermes plugin and local NeMo Relay settings
while building the sandbox image. This keeps plugin enablement, the Brev
loopback marker, Python dependencies, and trace configuration consistent after
a restart or rebuild.

`scripts/prepare-hermes-image.py` finds the source checkout used by the
installed `nemohermes`, copies the plugin into Hermes’s shared root-owned plugin
directory, adds the Relay configuration, and updates NemoClaw’s managed Hermes
policy. It also mirrors the top-level plugin configuration into the isolated
dashboard process.

The image installs the checksum-pinned NeMo Relay 0.7.2 x86-64 wheel and runs
`uv pip check`. That version satisfies the Hermes dependency range tested by
this example. The standard `nemoclaw` plugin and the rest of the managed Hermes
image stay in place.

The onboarding wrapper passes `--from` with the prepared Hermes Dockerfile.
Omitting it selects the stock Hermes image, which doesn’t contain the Ask
NemoClaw plugin or loopback marker.

A shorter `hermes plugins install` path may be useful later, but it isn’t a
supported procedure yet. Before adding it, verify immutable-source installation,
explicit enablement, dashboard discovery, restart and rebuild persistence,
minimum OpenShell policy, and both loopback and authenticated HTTPS behavior.

## Local verification

Build the versioned portable extension archive after changing extension source
or its manifest version:

```bash
python3 scripts/build-extension-release.py
```

The generated ZIP contains no deployment URL or credential. Commit it with the
source change. The verification suite compares the archive byte-for-byte with a
fresh deterministic build.

From the example directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh
```

The suite checks:

- JavaScript syntax and response normalization;
- Chrome origin permissions and session handling;
- authentication and browser-origin enforcement;
- input and output size limits;
- conversation ownership, isolation, and idempotency;
- viewport-only and multimodal requests;
- same-session image attachment;
- tab and document changes during page capture;
- cancellation during initialization, image attachment, and inference;
- cancellation, timeout, and non-PTY behavior;
- dashboard session visibility;
- extension builds for portable, HTTPS, loopback, and Brev paths;
- idempotent Hermes image preparation; and
- local-only NeMo Relay ATIF configuration.

## Live verification

Use synthetic or public page content unless your environment is approved for
sensitive data.

1. Start the Brev port forward and configure the extension with its loopback
   URL.
2. Confirm the extension creates a conversation without a Hermes login prompt.
3. Confirm ordinary dashboard chat still works.
4. Ask about a page containing readable text and a distinctive visible image.
5. Send a follow-up and confirm the conversation is retained.
6. Start a new conversation and confirm it doesn’t inherit the earlier one.
7. Confirm both browser conversations appear in Hermes **Sessions**.
8. Change tabs, select the toolbar icon, and confirm **Refresh** starts with the
   new page context.
9. Confirm the recipe added no external host to OpenShell policy.
10. Confirm a new JSON file appears in
    `/sandbox/.hermes-data/nemo-relay/atif`. Inspect only field names if the
    context is sensitive.

## Shared HTTPS deployment

The Brev loopback flow is intended for one developer. A shared deployment
needs normal Hermes authentication and an HTTPS ingress that supports browser
extension API requests. `deploy/nginx/ask-nemoclaw-server.conf` is a reference
reverse-proxy template for that integration.

An operator can check a shared route without sending credentials:

```bash
bash scripts/check-connection.sh https://hermes.example.com
```

HTTP 302, 401, or 403 can be the expected authentication boundary. The side
panel performs the final check after the user signs in normally.

An administrator can build an extension with one initial HTTPS origin:

```bash
bash scripts/build-extension.sh https://hermes.example.com
```

The extension still contains no credential. Users can change the deployment
later through Settings.

## Third-party software

This example builds on NemoClaw, Hermes, OpenShell, NeMo Relay, and FastAPI.
Their own licenses still apply. Check the repository license and
third-party notices before redistributing the example or a built image.

## File map

| Path | Purpose |
| --- | --- |
| `extension/` | Manifest V3 Chrome side-panel source. |
| `release/ask-nemoclaw-extension-0.10.11.zip` | Prebuilt portable extension for local installation. |
| `hermes-plugin/` | Authenticated Hermes REST adapter backed by non-PTY JSON-RPC sessions. |
| `relay/plugins.toml` | Local-only NeMo Relay ATIF configuration with provider-placeholder redaction. |
| `scripts/prepare-hermes-image.py` | Adds the plugin, Relay settings, and managed enablement to the Hermes image source. |
| `scripts/prepare-brev-gateway.sh` | Verifies and hands off the empty legacy Brev gateway. |
| `scripts/check-brev-host.sh` | Runs read-only launchable compatibility checks. |
| `scripts/onboard.sh` | Builds and onboards the custom Hermes sandbox. |
| `scripts/build-extension.sh` | Builds the portable extension or one with an initial HTTPS origin. |
| `scripts/build-extension-release.py` | Builds the versioned portable extension ZIP committed with the example. |
| `scripts/check-connection.sh` | Checks dashboard and plugin routes without printing credentials. |
| `deploy/nginx/ask-nemoclaw-server.conf` | Reference proxy for a shared HTTPS ingress. |
| `scripts/verify.sh` | Runs static and local tests. |
| `tests/` | Python API and JavaScript tests using synthetic data. |
