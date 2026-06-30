<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Optional Outlook Channel

The Outlook bridge is intentionally separate from core startup. It reads one
configured mailbox, accepts messages from one configured sender, and replies
only to the matching message thread.

## Security Boundary

- `OUTLOOK_TARGET_MAILBOX` is the only Graph mailbox path allowed.
- `OUTLOOK_REPLY_TO` is the only sender the bridge processes.
- OpenShell provider and network rules allow inbox list, in-thread reply, and
  mark-read operations only.
- There is no arbitrary recipient or `sendMail` path.
- The access token remains an OpenShell credential placeholder in the sandbox.

OpenShell `0.0.44` accepts initial OAuth refresh material only through its
`--material KEY=VALUE` CLI argument. Run setup on a single-user host and do not
enable shell tracing; the process is short-lived and the gateway stores that
field as secret material afterward.

## Microsoft Requirements

The Entra application must permit device-code authentication and delegated
Microsoft Graph access for `Mail.ReadWrite`, `Mail.Send`, and `offline_access`.
Your organization may require administrator consent and a Conditional Access
exception for the application and Brev location.

Set these values in the example `.env`:

```dotenv
OUTLOOK_TENANT_ID=
OUTLOOK_CLIENT_ID=
OUTLOOK_TARGET_MAILBOX=
OUTLOOK_REPLY_TO=
```

## Configure

Start the core demo first, then run:

```bash
./scripts/demo.sh outlook-setup
```

The script prints Microsoft's device-login URL and code. Open the exact
verification URL and enter the code; do not open the OAuth token endpoint in a
browser. The script then configures gateway-managed refresh, attaches the
provider, renders the mailbox-scoped policy, and uploads the bridge.

## Validate Without Replying

Send a new message from `OUTLOOK_REPLY_TO` to `OUTLOOK_TARGET_MAILBOX`, then:

```bash
./scripts/demo.sh outlook-test
```

This prints the proposed assistant reply but does not send or mark the message.

## Enable In-Thread Replies

After print-mode validation:

```bash
./scripts/demo.sh outlook-start
tail -f .runtime/outlook.log
```

The bridge records processed message IDs and marks replied messages read.
Stop it with `./scripts/demo.sh outlook-stop`.

## Conditional Access Failure

`AADSTS53003` means sign-in succeeded but tenant policy blocked resource access.
It is not a bad redirect and cannot be fixed by changing GET to POST in the
browser. Send the Entra request/correlation IDs to the tenant administrator and
request approval for the configured application, device-code flow, account,
and Brev egress location. Core web chat, finance skills, Relay, and Phoenix do
not depend on Outlook and continue to work while that approval is pending.
