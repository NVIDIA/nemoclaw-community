<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Security and data

Ask NemoClaw sends browser context to an agent, so its trust boundary needs to
be clear before you use it with sensitive pages.

## Data flow

Every message can include:

- the active page URL and title;
- selected and readable page text;
- a JPEG of the visible viewport; and
- the user’s prompt.

That data goes to the configured Hermes deployment and its inference provider.
NeMo Relay also records local ATIF traces under
`/sandbox/.hermes-data/nemo-relay/atif`. A trace can contain the prompt, page
context, model output, and tool events. The base recipe doesn’t export traces
to an external collector and doesn’t automatically delete them.

## Browser permissions

The extension uses Chrome’s `activeTab` permission. Selecting the toolbar icon
grants temporary access to the current tab; it doesn’t grant persistent access
to every page. Chrome internal pages are rejected.

The extension starts without a deployment hostname. When the user saves a
Hermes URL, Chrome asks for access to that exact origin. Changing deployments
removes the previous optional origin permission.

The `cookies` permission is combined with that exact host permission. This lets
the extension read Hermes session cookies only for the configured deployment.
It converts the access token to Hermes’s supported bearer authentication and
uses `/auth/native/refresh` when needed. Rotated tokens stay in Chrome’s
memory-backed `storage.session`; they aren’t written to local or synchronized
extension storage.

## Loopback development mode

The Brev quick start keeps Hermes bound to loopback and uses the authenticated
Brev CLI tunnel as its access boundary. The prepared image contains a
root-owned, read-only marker that permits one local development identity only
when Hermes sees a loopback hostname.

Hermes embeds a random, short-lived session token in the local dashboard page.
The extension returns it to the same origin in the
`X-Hermes-Session-Token` header and keeps it only in memory. External requests
without a valid Hermes session remain unauthorized.

The bundled `configure_dashboard_auth.py` helper is for a shared HTTPS
deployment. Don’t use it for the Brev loopback quick start.

## Server controls

The Hermes plugin:

- requires an authenticated Hermes session for shared HTTPS deployments;
- checks the browser origin;
- strips URL credentials and fragments and removes credential-like query
  parameters;
- limits request and response sizes;
- accepts only a bounded, browser-generated JPEG viewport;
- requires an idempotency key for each message;
- isolates conversations by the authenticated Hermes user;
- creates a separate non-PTY Hermes session for each browser conversation;
- reuses that session only for follow-up messages in the same conversation;
- removes temporary gateway images after the turn; and
- performs no page writes and adds no external egress policy.

The manifest’s public key produces a stable public extension identifier. The
plugin uses that identifier to check the browser origin; it isn’t a credential.
An enterprise deployment can set `HERMES_ASK_NEMOCLAW_EXTENSION_ID` to the ID
of its centrally distributed extension.

## Untrusted page content

Page text and rendered pixels are untrusted input. The plugin separates them
from the signed-in user’s prompt and tells Hermes not to treat page content as
instructions. This reduces prompt-injection risk, but it isn’t a complete
defense. OpenShell remains the enforcement boundary for network access and
external tools.

Text capture uses `document.body.innerText`. The image includes charts, images,
canvas content, layout, and formatting in the visible viewport. It doesn’t
include off-screen content, other tabs, or Chrome’s toolbar.

## Multimodal inference

The configured inference route needs image understanding to analyze the
viewport. The tested NemoClaw workspace enforces one primary model for every
inference request, so selecting a different auxiliary vision model in Hermes
doesn’t override that route.

This example was tested with
`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`. A text-only primary model can
still use readable page text but can’t interpret the viewport image.
