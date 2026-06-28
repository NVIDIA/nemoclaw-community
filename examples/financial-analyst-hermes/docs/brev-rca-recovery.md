# Brev RCA And Recovery Runbook

This runbook documents the failure we saw during the Brev booth demo setup and
the exact recovery path for the financial assistant.

## Executive Summary

The UI was not the agent. The healthy path is:

```text
Browser
  -> finance_ui_server.py on :18080
  -> Hermes API in the OpenShell sandbox on :8642
  -> host NeMo Relay sidecar on :4040
  -> configured chat-completions API
  -> Phoenix on :6006 for traces
```

The critical missing piece was this environment variable on the running Hermes
gateway process:

```bash
NEMO_RELAY_GATEWAY_URL=http://host.openshell.internal:4040
```

Without it, Hermes can still answer and can still call tools such as
`skill_view`, but the in-process `nemo-relay` plugin cannot forward tool hook
events to Relay. Phoenix then misses the tool spans even though the agent used
the skills.

## What Happened

1. The original helper script drifted from the live architecture. It could
   start the UI against Relay directly, which bypasses Hermes and therefore
   bypasses Hermes skills, tool calls, and Hermes-native traces.
2. The live system was later corrected to UI -> Hermes -> Relay, but a manual
   Hermes restart omitted `NEMO_RELAY_GATEWAY_URL`.
3. That created a split-brain symptom:
   - chat requests worked,
   - Hermes logs showed `skill_view completed`,
   - Phoenix showed fresh LLM spans,
   - Phoenix did not show fresh `skill_view` tool spans.
4. During manual recovery, a nested shell command also wrote malformed Relay
   TOML once. Relay exited immediately with:

```text
TOML parse error ... kind = observability ... string values must be quoted
```

5. `.env` loading also failed under `set -u` when an env value referenced a
   variable defined earlier in the same file. The startup scripts now relax
   nounset only while sourcing `.env`.

## Required Runtime Invariants

These must all be true for the booth demo to be healthy:

| Component | Required state |
| --- | --- |
| Finance UI | Listens on `0.0.0.0:18080` and proxies `/v1/*` to Hermes, not Relay. |
| Hermes API | Runs inside the OpenShell sandbox and listens on `127.0.0.1:18642`; `socat` exposes sandbox port `8642`. |
| Hermes model route | Points at `http://host.openshell.internal:4040/v1` so model traffic goes through host Relay. |
| Hermes env | Includes `NEMO_RELAY_GATEWAY_URL=http://host.openshell.internal:4040`. |
| Hermes no-proxy | Includes `host.openshell.internal` and the host bridge IP so Relay calls do not go through the sandbox proxy. |
| Relay | Listens on host `0.0.0.0:4040` and forwards to `FINANCE_API_URL`. |
| Phoenix | Listens on host `0.0.0.0:6006`; Relay exports OpenInference spans to `http://127.0.0.1:6006/v1/traces`. |
| Hermes config | Enables the `nemo-relay` plugin and the relay hooks from `agents/hermes/relay-hooks.yaml`. |
| Skills | Finance skills are installed and scoped with `scripts/install-skills.sh`. |

## One-Command Recovery

Run this inside the Brev instance:

```bash
cd "$(find ~/financial-assistant-agent ~/nemoclaw-community -path '*/examples/financial-analyst-hermes' -type d 2>/dev/null | sort | tail -1)"
bash scripts/recover-brev-demo.sh
```

If the machine has more than one Hermes sandbox container, set the intended
container explicitly:

```bash
cd "$(find ~/financial-assistant-agent ~/nemoclaw-community -path '*/examples/financial-analyst-hermes' -type d 2>/dev/null | sort | tail -1)"
docker ps --format '{{.Names}}'

export FINANCE_HERMES_CONTAINER=<the-openshell-hermes-container-name>
bash scripts/recover-brev-demo.sh
```

The recovery script:

- loads `.env`,
- starts Phoenix,
- writes a valid `.nemo-relay/plugins.toml`,
- restarts host Relay on `0.0.0.0:4040`,
- refreshes the Hermes SOUL and `nemo-relay` plugin in the sandbox,
- restarts Hermes with `NEMO_RELAY_GATEWAY_URL`,
- starts the UI against the Hermes sandbox API,
- asks “What skills do you have?” through the UI route,
- verifies fresh `skill_view` tool spans in Phoenix.

## Manual Verification

Check that the UI is proxying to Hermes:

```bash
curl -sf http://127.0.0.1:18080/health | python3 -m json.tool
```

Expected shape:

```json
{
  "status": "ok",
  "platform": "finance-ui",
  "upstream": "http://<hermes-container-ip>:8642",
  "model": "<configured model>"
}
```

Check the running processes:

```bash
ps -eo pid,cmd | grep -E 'finance_ui_server|nemo-relay' | grep -v grep
docker exec "$FINANCE_HERMES_CONTAINER" sh -lc \
  'ps -eo pid,user,args | grep -E "hermes gateway run|socat.*8642" | grep -v grep'
```

Check the Hermes process env:

```bash
docker exec "$FINANCE_HERMES_CONTAINER" sh -lc '
pid="$(pgrep -f "^/opt/hermes/.venv/bin/python /usr/local/bin/hermes gateway run" | head -1)"
tr "\0" "\n" < "/proc/$pid/environ" | grep -E "^(NEMO_RELAY_GATEWAY_URL|NO_PROXY|no_proxy)="
'
```

You should see:

```text
NEMO_RELAY_GATEWAY_URL=http://host.openshell.internal:4040
```

Ask the skills question through the UI route:

```bash
curl -sf http://127.0.0.1:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Finance-Run-Id: manual-skills-check' \
  -d "{
    \"model\": \"${FINANCE_MODEL}\",
    \"messages\": [
      {
        \"role\": \"user\",
        \"content\": \"What skills do you have? Please inspect your installed finance skills and answer concisely.\"
      }
    ],
    \"max_tokens\": 1200,
    \"reasoning_effort\": \"high\"
  }" | python3 -m json.tool
```

Check Hermes saw actual tool calls:

```bash
docker exec "$FINANCE_HERMES_CONTAINER" sh -lc \
  'grep -R "tool skill_view completed" /sandbox/.hermes/logs /tmp/gateway.log 2>/dev/null | tail -20'
```

Check Phoenix saw the matching tool spans:

```bash
curl -sf http://127.0.0.1:18080/api/phoenix/recent | python3 -m json.tool
```

Look for a fresh row like:

```json
{
  "project": "financial-assistant-relay",
  "name": "skill_view",
  "kind": "tool"
}
```

For an exact count of fresh spans:

```bash
python3 - <<'PY'
import json
import urllib.request

query = """
{
  projects {
    edges {
      node {
        name
        spans(first: 1000) {
          edges {
            node { name spanKind startTime trace { traceId } }
          }
        }
      }
    }
  }
}
"""
req = urllib.request.Request(
    "http://127.0.0.1:6006/graphql",
    data=json.dumps({"query": query}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=10) as response:
    payload = json.load(response)

rows = []
for project_edge in payload.get("data", {}).get("projects", {}).get("edges", []):
    project = project_edge["node"]["name"]
    for span_edge in project_edge["node"]["spans"]["edges"]:
        span = span_edge["node"]
        if span.get("name") == "skill_view":
            rows.append(
                (
                    span.get("startTime"),
                    project,
                    span.get("spanKind"),
                    span.get("name"),
                    (span.get("trace") or {}).get("traceId", "")[-8:],
                )
            )

for row in sorted(rows)[-10:]:
    print("\t".join(str(value) for value in row))
print("skill_view_count=", len(rows))
PY
```

## Common Failure Modes

### UI says `Failed to fetch`

Check whether the UI process is alive and whether its upstream is Hermes:

```bash
curl -sf http://127.0.0.1:18080/health | python3 -m json.tool
```

If `upstream` is Relay or the endpoint is unreachable, run:

```bash
bash scripts/recover-brev-demo.sh
```

### Hermes answers but Phoenix has no tool spans

This usually means `NEMO_RELAY_GATEWAY_URL` is missing from the Hermes process.
Run:

```bash
bash scripts/recover-brev-demo.sh
```

Then verify:

```bash
curl -sf http://127.0.0.1:18080/api/phoenix/recent | python3 -m json.tool
```

### Relay exits immediately

Read the Relay log:

```bash
sed -n '1,200p' .runtime/nemo-relay.log
```

If the error is TOML parsing, delete the generated file and rerun recovery:

```bash
rm -f .nemo-relay/plugins.toml
bash scripts/recover-brev-demo.sh
```

### `.env` fails with `unbound variable`

Use the scripts in this repo instead of sourcing with `set -u` yourself. They
temporarily disable nounset while reading `.env`.

Manual fallback:

```bash
set -a
set +u
. ./.env
set -u
set +a
```

### Multiple Hermes containers exist

List containers and pin the one used by the demo:

```bash
docker ps --format '{{.Names}}'
export FINANCE_HERMES_CONTAINER=<the-container-that-has-/sandbox/.hermes>
bash scripts/recover-brev-demo.sh
```

## What A Passing Recovery Looks Like

The final lines should include:

```text
fresh_skill_view_spans=4 trace=<trace suffix>
Financial assistant recovery complete.
```

One `skill_view` span is enough to prove the hook path works. Four spans are
expected for the current skills question because Hermes reads the four finance
skill instruction files before answering.
