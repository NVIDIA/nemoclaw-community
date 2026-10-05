<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Brev setup and troubleshooting

This page explains the Brev-specific parts of the Ask NemoClaw quick start. If
the commands in the main README work, you don’t need anything here.

## Why the Docker storage driver matters

Some NemoClaw launchable versions enable Docker’s containerd snapshotter. A
container created with that snapshotter sees an overlay root filesystem, which
can’t provide the nested overlay mounts required by the OpenShell sandbox.

On a fresh host, switch Docker to classic `overlay2` before creating a sandbox.
Confirm the result with:

```bash
docker info --format 'Driver={{.Driver}} Status={{json .DriverStatus}}'
```

Don’t change Docker storage on a host that already contains data you need. The
recipe’s quick start assumes a new Brev instance with no sandbox.

## Why the gateway handoff is needed

The tested launchable includes an older OpenShell gateway supervised by a
system service. That gateway can answer health requests, but it doesn’t
implement the complete inference configuration contract expected by the
updated NemoClaw client. A model can validate successfully and onboarding can
still fail with:

```text
Operation is not implemented or not supported
```

`scripts/prepare-brev-gateway.sh` first proves that the legacy gateway contains
no sandbox. It then stops and disables only `openshell-gateway.service`, removes
the stale client registration, and leaves the old gateway data intact.

`scripts/onboard.sh` selects the repository’s `nemoclaw-managed` gateway
declaration. Current NemoClaw uses the version-matched native gateway on the
tested Brev host. It does not implicitly enable the more privileged
compatibility-container mode, which requires an explicit operator opt-in.

Don’t copy individual OpenShell binaries into `/usr/local/bin`. The CLI,
gateway, and sandbox driver need to be from a compatible build.

## Resume or recreate onboarding

Resume an interrupted image build with the same trusted Dockerfile selection:

```bash
bash scripts/onboard.sh --resume
```

To discard the example sandbox and build it again from a clean state:

```bash
bash scripts/onboard.sh --recreate-sandbox
```

Recreation permanently removes that sandbox’s conversations and workspace
state. The script also clears its lifecycle registration and releases only the
verified service forwards owned by that sandbox. A normal onboarding run is
non-destructive.

The default sandbox name is `ask-nemoclaw`. To use another name of 19 or fewer
characters:

```bash
NEMOCLAW_SANDBOX_NAME=my-browser-agent bash scripts/onboard.sh
```

## Dashboard port conflicts

NemoClaw normally assigns dashboard port `18789`. Check the actual port with:

```bash
nemohermes ask-nemoclaw dashboard-url --quiet
```

Use that remote port on the right side of the Brev mapping. If local port
`18789` is occupied, choose a different local port on the left:

```bash
brev port-forward <brev-instance-name> -p 18790:18789
```

Configure the extension with the local URL, such as
`http://127.0.0.1:18790`.

## Why Brev Secure Links aren’t used

Brev Secure Links protect browser pages with a redirect-based authentication
flow. A Chrome extension making a cross-origin API request can’t complete that
redirect flow as an ordinary web page would.

Use the authenticated Brev CLI port forward for this single-user development
example. For a shared deployment, provide a normal authenticated HTTPS ingress
that accepts API requests from the extension.

## Connection checks

After starting the port forward, run:

```bash
bash scripts/check-connection.sh http://127.0.0.1:18789
```

For loopback, the checker requires all of the following:

- Hermes reports that dashboard authentication is disabled;
- the prepared sandbox provides an ephemeral dashboard session token; and
- the Ask NemoClaw API accepts that token.

The checker doesn’t print or store the token. If it reports that authentication
is required, the sandbox was configured for a shared deployment or was built
before the loopback marker was added. Recreate it from the current recipe if
you don’t need its existing state.
