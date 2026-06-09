# Outlook Integration

Outlook is not a built-in NemoClaw messaging channel today. NemoClaw's built-in
channel commands cover chat-style bridges such as Slack, Telegram, Discord,
WeChat, and WhatsApp. For Outlook, use the same Microsoft Graph / OpenShell
provider pattern as `examples/personal-community-sentiment-triage`.

## Architecture

```text
Outlook mailbox
  -> Microsoft Graph
  -> OpenShell L7 proxy with provider-token substitution
  -> outlook_finance_bridge.py
  -> Hermes `/v1/chat/completions`
  -> Microsoft Graph reply
```

The sandbox should see only an OpenShell placeholder for
`MS_GRAPH_ACCESS_TOKEN`; OpenShell substitutes a live token on egress.

## Provider

This example includes:

```text
providers/outlook-email.yaml
```

It describes a delegated Microsoft Graph provider with OAuth refresh-token
rotation. It is adapted from the sentiment triage agent's Outlook provider.

## Entra App

Create an application registration with public client/device-code flow enabled.
Grant delegated Microsoft Graph permissions:

- `Mail.Read`
- `Mail.Send`
- `offline_access`

For shared mailbox search, also follow your organization's delegate-access
policy before querying another user's mailbox.

## Bridge

Fixture rehearsal:

```bash
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:18080/v1 \
  --fixture fixtures/outlook-emails.json \
  --limit 1
```

## Configure the OpenShell Provider

Put the non-secret mailbox values and Entra app IDs in the repo root `.env` or
this example's `.env`:

```dotenv
OUTLOOK_TENANT_ID=<directory-tenant-id>
OUTLOOK_CLIENT_ID=<application-client-id>
OUTLOOK_TARGET_MAILBOX=<agent mailbox>
OUTLOOK_REPLY_TO=<your mailbox>
OUTLOOK_ALLOWED_SENDERS=<same value as OUTLOOK_REPLY_TO>
```

Then run:

```bash
bash scripts/setup-outlook-provider.sh financial-analyst
```

The setup helper:

- imports `providers/outlook-email.yaml`,
- enables OpenShell provider v2 if needed,
- runs Microsoft Graph device-code login as `OUTLOOK_TARGET_MAILBOX`,
- registers the refresh token with OpenShell's gateway-managed refresh flow,
- rotates `MS_GRAPH_ACCESS_TOKEN` once so the provider is ready.

If Microsoft returns a conditional-access error such as `AADSTS53003`, the
login succeeded but the tenant blocked access for that app, device, location, or
policy. Fix that policy/app assignment first, then rerun the helper. The script
does not register a half-configured provider after a failed login.

Real Graph read/reply after provider setup:

```bash
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:8642/v1 \
  --limit 5 \
  --reply-mode graph
```

Use `--reply-mode print` during first validation so no emails are sent until you
have reviewed the generated response format.

## One-Owner Mailbox Mode

The finance bridge is intentionally narrow:

- `OUTLOOK_TARGET_MAILBOX` is the only mailbox it reads and replies from.
- `OUTLOOK_REPLY_TO` is the only sender it will process.
- Replies are sent only in-thread via Microsoft Graph's message reply API.
- Processed message IDs are persisted under
  `$HERMES_HOME/outlook/processed.json` to avoid duplicate replies.

Required sandbox env:

```text
OUTLOOK_TARGET_MAILBOX=<agent mailbox>
OUTLOOK_REPLY_TO=<your mailbox>
OUTLOOK_ALLOWED_SENDERS=<same value as OUTLOOK_REPLY_TO>
MS_GRAPH_ACCESS_TOKEN=openshell:resolve:env:MS_GRAPH_ACCESS_TOKEN
```

On Brev, apply the Python bridge policy:

```bash
nemohermes financial-analyst policy-add \
  --from-file examples/financial-analyst-hermes/presets/financial-outlook-mailbox.yaml \
  --yes
```

Then run the bridge in polling mode inside the sandbox:

```bash
python3 /sandbox/.hermes/outlook/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:8642/v1 \
  --reply-mode graph \
  --poll \
  --interval 30 \
  --limit 3
```

If `financial-analyst` was already running before the Outlook provider was
created, recreate or restart the sandbox with the provider attached before
expecting OpenShell token substitution to work from inside the sandbox.
