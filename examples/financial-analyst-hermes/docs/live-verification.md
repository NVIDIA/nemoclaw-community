# Live Verification

Last updated: 2026-06-09

This page records the current verified state of the Brev-hosted financial
assistant demo.

## Brev Deployment

- Public UI: `https://demo-ykokji2ig.brevlab.com/`
- Brev server: `financial-assistant-agent`
- Active release path:
  `/home/ubuntu/financial-assistant-agent/releases/20260609001354-3315a0f2`
- Branch: `feature/hermes-financial-assistant`
- Verification source: current pushed feature branch

Live health:

```json
{"status":"ok","platform":"finance-ui","upstream":"http://127.0.0.1:8642","model":"nvidia/nemotron-3-ultra-550b-a55b"}
```

Live config:

```json
{"model":"nvidia/nemotron-3-ultra-550b-a55b","upstream_label":"Build API"}
```

## Runtime Evidence

The Brev host is running:

- OpenShell gateway container
- Hermes sandbox container:
  `openshell-financial-analyst-0a86a162-5f08-4466-bb56-1574ab176069`
- Finance UI server on port `18080`
- OpenShell inference timeout set to `240s` for the Build API Ultra route
- Phoenix container: `observability-phoenix-1`
- NeMo Relay sidecar in the sandbox:
  `/sandbox/.hermes/bin/nemo-relay --bind 127.0.0.1:4040`

## UI Verification

Passed checks:

- `npm test`: 7 tests passed.
- `npm run build`: passed.
- Public `https://demo-ykokji2ig.brevlab.com/health`: passed with
  `nvidia/nemotron-3-ultra-550b-a55b`.
- Public `https://demo-ykokji2ig.brevlab.com/config`: passed with `Build API`.
- Direct Build API smoke: passed with `nvidia/nemotron-3-ultra-550b-a55b`.
- Minimal Hermes route smoke: passed with `nvidia/nemotron-3-ultra-550b-a55b`.

Current caveat:

- Full public Playwright UI smoke with an open-ended assistant prompt was not
  used as the post-correction pass condition because Ultra responses through
  Hermes can exceed the browser smoke timing. The UI is deployed and serving the
  corrected model/config, while route verification is covered by the direct and
  Hermes API smoke checks above.

Observed UI behavior:

- No visible API URL or API token field.
- No Demo Prompts, Ten-Question Eval, Session Context, Skill Usage, Tool Calls,
  or Run Telemetry panels.
- Enter submits the composer.
- The composer starts empty.
- Responses stream into the conversation.
- The thinking state displays animated `Thinking ...` dots before token output.
- Markdown is rendered with `markdown-it`.
- Safe inline HTML can render; unsafe HTML is sanitized with `DOMPurify`.

## Phoenix And NeMo Relay

Recent live Phoenix evidence from `/api/phoenix/recent`:

```json
{
  "ok": true,
  "span_count": 12,
  "kinds": ["llm", "tool"],
  "projects": ["financial-assistant-relay"]
}
```

The trace path is Hermes/Relay-to-Phoenix, not a synthetic UI span.

## Outlook

Implemented:

- `scripts/setup-outlook-provider.sh` configures the OpenShell Outlook provider
  using gateway-managed Microsoft Graph refresh-token rotation.
- `scripts/login-ms-graph.py` runs Microsoft device-code login.
- `scripts/outlook_finance_bridge.py` runs the one-owner bridge:
  - reads only `OUTLOOK_TARGET_MAILBOX`,
  - processes only `OUTLOOK_REPLY_TO`,
  - replies only in-thread,
  - persists processed message IDs.

Verified:

- Fixture rehearsal passed against the public Brev `/v1` endpoint in
  `--reply-mode print`.

Current external blocker:

- Real Microsoft Graph send/reply is blocked by tenant conditional access for
  the attempted account/app sign-in. The observed Microsoft error was
  `AADSTS53003`.
- Once tenant policy permits the agent account/app device-code login, rerun:

```bash
bash scripts/setup-outlook-provider.sh financial-analyst
python3 scripts/outlook_finance_bridge.py \
  --api-url http://127.0.0.1:8642/v1 \
  --limit 1 \
  --reply-mode print
```

Use `--reply-mode graph` only after print-mode validation succeeds.

## Requirement Status

Completed:

- NemoHermes/NemoClaw financial assistant example.
- Finance skills, tools, API access, and Brev deployment docs.
- Streaming financial assistant UI deployed on Brev.
- Markdown and safe HTML rendering.
- NVIDIA logo and demo resource links.
- Nemotron Ultra live route: `nvidia/nemotron-3-ultra-550b-a55b`.
- Direct Build API smoke and minimal Hermes route smoke passed with the
  corrected model ID.
- Phoenix and NeMo Relay producing real spans.
- Outlook fixture bridge and provider setup path.

Not fully completed:

- Real Outlook Graph send/reply awaits tenant conditional-access approval.
