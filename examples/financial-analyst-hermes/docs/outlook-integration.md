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

Real Graph read/reply after provider setup:

```bash
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:8642/v1 \
  --limit 5 \
  --reply-mode graph
```

Use `--reply-mode print` during first validation so no emails are sent until you
have reviewed the generated response format.
