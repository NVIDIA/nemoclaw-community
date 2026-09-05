<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Native NeMo Relay End-to-End Test

Use this runbook on a Linux or Brev host with real inference credentials to
validate the native Hermes and NeMo Relay integration in:

- `examples/recipes/nvidia/developer-community-chief-of-staff`
- `examples/recipes/nvidia/agentic-ai-learning-path`
- `examples/recipes/nvidia/payment-ops-hermes`

Run the examples sequentially. Chief of Staff and Agentic AI Learning Path use
the same default sandbox name, and all three use Phoenix port `6006`.

## Acceptance criteria

Do not report the branch ready unless all required checks pass:

| Check | Chief of Staff | Learning Path | Payment Ops |
| --- | :---: | :---: | :---: |
| OpenShell `0.0.106`, Hermes `0.20.6`, Relay `0.7.2` | Required | Required | Required |
| Valid native Relay configuration and healthy Hermes API | Required | Required | Required |
| No Relay daemon, ATIF bridge, API bridge, or `socat` process | Required | Required | Required |
| Real model and tool turn | Required | Required | Required |
| Phoenix receives native Relay spans | Required | Required | Required |
| Clean session boundary produces local ATIF | Required | Required | Required |
| Authenticated remote ATIF reaches MinIO with no local duplicate | Required | Required | N/A |
| Failed remote delivery creates a local recovery copy | Required | Required | N/A |
| OpenShell denies an unapproved executable at the ATIF endpoint | Required | Required | N/A |
| Example-specific user workflow succeeds | Required | Required | Required |
| Payment rail stays unreachable from the sandbox | N/A | N/A | Required |

## Safety and evidence rules

- Start from a clean checkout of `fix/update-hermes-native-relay` and record
  `git rev-parse HEAD`. Do not test a different commit accidentally.
- Never copy `.env`, provider credential values, token caches, certificate
  private keys, or an unfiltered process environment into the evidence bundle.
- Keep raw prompts, model responses, Phoenix exports, and ATIF files private if
  they contain sensitive data. A sanitized pass/fail report is sufficient for
  the pull request.
- Use `openshell sandbox exec` for behavioral and policy checks. Direct
  `docker exec` is acceptable only for read-only process and file inspection.
- Capture logs before teardown. Do not destroy volumes until the evidence has
  been reviewed.
- Stop at the first credential leak, unauthorized `2xx`, unexpected payment
  release, or missing recovery copy. Report it as a security failure.

Create a private evidence directory:

```bash
cd /path/to/nemoclaw-community
set -euo pipefail
test "$(git branch --show-current)" = fix/update-hermes-native-relay
git status --short

export EVIDENCE="$HOME/nemoclaw-native-relay-e2e-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$EVIDENCE"
git rev-parse HEAD | tee "$EVIDENCE/commit.txt"
uname -a | tee "$EVIDENCE/host.txt"
docker version | tee "$EVIDENCE/docker-version.txt"
docker compose version | tee "$EVIDENCE/compose-version.txt"
openshell --version | tee "$EVIDENCE/openshell-version.txt"
```

The OpenShell version must be `0.0.106`. Enable provider v2 support once:

```bash
openshell settings set --global --key providers_v2_enabled --value true --yes
```

On a headless host, ensure the user gateway can remain running:

```bash
sudo loginctl enable-linger "$USER"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user start openshell-gateway
```

## Common native integration checks

Run these after every deployment. Set `SANDBOX` to `hermes-direct` for Chief
of Staff and Learning Path, or `payment-ops` for Payment Ops.

```bash
openshell sandbox list | tee "$EVIDENCE/sandbox-list.txt"

openshell sandbox exec --name "$SANDBOX" -- \
  curl -fsS http://127.0.0.1:8642/health \
  | tee "$EVIDENCE/$SANDBOX-health.json"

openshell sandbox exec --name "$SANDBOX" -- \
  /opt/hermes/.venv/bin/python -c \
  'from importlib.metadata import version; print("hermes-agent=" + version("hermes-agent")); print("nemo-relay=" + version("nemo-relay"))' \
  | tee "$EVIDENCE/$SANDBOX-native-versions.txt"

openshell sandbox exec --name "$SANDBOX" -- \
  /opt/hermes/.venv/bin/python -c \
  'import tomllib; from pathlib import Path; from nemo_relay import plugin; p=Path("/etc/nemo-relay/config/plugins.toml"); c=tomllib.loads(p.read_text()); d=plugin.validate(c).get("diagnostics", []); print("diagnostics=", d); assert not d' \
  | tee "$EVIDENCE/$SANDBOX-relay-validation.txt"

openshell sandbox exec --name "$SANDBOX" -- sh -lc \
  'pgrep -af "[h]ermes gateway run"; ! pgrep -af "[n]emo-relay|[s]ocat|[a]tif-bridge"' \
  | tee "$EVIDENCE/$SANDBOX-processes.txt"
```

Pass only when the sandbox is `Ready`, health is successful, the versions are
exactly `0.20.6` and `0.7.2`, Relay reports zero diagnostics, one Hermes gateway
is present, and there is no separate Relay, `socat`, or ATIF bridge process.
The Outlook bridge may be present when Outlook is configured.

Inspect the rendered configuration without publishing it:

```bash
openshell sandbox exec --name "$SANDBOX" -- \
  sed -n '1,220p' /etc/nemo-relay/config/plugins.toml \
  > "$EVIDENCE/$SANDBOX-plugins.toml"
```

Local mode must have ATIF enabled at `/sandbox/atif`, Phoenix configured as
requested, and no ATIF HTTP storage block. Chief of Staff and Learning Path
must also have PII redaction enabled. Relay mode must have exactly one HTTP
storage block ending in `/atif`.

## Validate one ATIF trajectory

Define this helper once in each example shell. A tool-using turn must contain
user and agent steps plus native LLM and tool evidence.

```bash
validate_atif() {
TRACE_FILE="$1" MARKER="$2" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["TRACE_FILE"])
raw = path.read_text(encoding="utf-8")
data = json.loads(raw)
assert data.get("schema_version") == "ATIF-v1.7", data.get("schema_version")
assert os.environ["MARKER"] in raw, "test marker missing"
assert "openshell:resolve:env:" not in raw, "credential placeholder leaked"
steps = data.get("steps")
assert isinstance(steps, list) and steps, "trajectory has no steps"
sources = {step.get("source") for step in steps if isinstance(step, dict)}
assert {"user", "agent"} <= sources, sources
assert any(
    isinstance(step, dict) and (step.get("llm_call_count") or 0) >= 1
    for step in steps
), "LLM evidence missing"
assert any(
    isinstance(step, dict) and (step.get("tool_calls") or step.get("observation"))
    for step in steps
), "tool evidence missing"

# Compare likely secret values without printing them.
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    value = value.strip().strip('"').strip("'")
    if any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
        if value and len(value) >= 8 and "your-" not in value.lower():
            assert value not in raw, f"value for {key} leaked"
print(f"PASS: {path.name} is valid and contains {len(steps)} steps")
PY
}
```

## Chief of Staff

Run from `examples/recipes/nvidia/developer-community-chief-of-staff`.

### Local export

Copy `.env.example` to the ignored `.env`. Set real inference credentials and
at least one complete messaging channel. Slack is the shortest path. Set:

```dotenv
PHOENIX_COLLECTOR_ENDPOINT=http://host.openshell.internal:6006/v1/traces
PHOENIX_PROJECT_NAME=developer-community-chief-of-staff-e2e
ATIF_EXPORT_MODE=local
```

Run:

```bash
python3 scripts/preflight.py
python3 scripts/preflight.py --external
bash scripts/bring-up.sh |& tee "$EVIDENCE/chief-local-bring-up.txt"
export SANDBOX=hermes-direct
```

Run the common native checks. Record the existing trajectories, then require a
real tool turn and a clean native session boundary:

```bash
openshell sandbox exec --name "$SANDBOX" -- sh -lc \
  'find /sandbox/atif -maxdepth 1 -type f -name "hermes-atif-*.json" -print | sort' \
  > "$EVIDENCE/chief-local-before.txt"

export MARKER="CHIEF-NATIVE-RELAY-$(date -u +%Y%m%dT%H%M%SZ)"
openshell sandbox exec --name "$SANDBOX" -- \
  env HERMES_HOME=/sandbox/.hermes-data hermes -z \
  "Use the terminal tool to print ${MARKER}, then reply with exactly ${MARKER}." \
  |& tee "$EVIDENCE/chief-local-turn.txt"

openshell sandbox exec --name "$SANDBOX" -- sh -lc \
  'find /sandbox/atif -maxdepth 1 -type f -name "hermes-atif-*.json" -print | sort' \
  > "$EVIDENCE/chief-local-after.txt"
comm -13 "$EVIDENCE/chief-local-before.txt" "$EVIDENCE/chief-local-after.txt" \
  > "$EVIDENCE/chief-local-new.txt"
MATCHING_TRACE=$(openshell sandbox exec --name "$SANDBOX" -- \
  env MARKER="$MARKER" python3 -c \
  'import glob, os, pathlib; m=[p for p in glob.glob("/sandbox/atif/hermes-atif-*.json") if os.environ["MARKER"] in pathlib.Path(p).read_text(errors="ignore")]; assert len(m) == 1, m; print(m[0])')
grep -Fxq -- "$MATCHING_TRACE" "$EVIDENCE/chief-local-new.txt"
```

Download the new file, set `TRACE_FILE` to it, and run the ATIF validator:

```bash
NEW_TRACE="$MATCHING_TRACE"
mkdir -p "$EVIDENCE/chief-local"
openshell sandbox download "$SANDBOX" "$NEW_TRACE" "$EVIDENCE/chief-local/"
TRACE_FILE=$(find "$EVIDENCE/chief-local" -type f \
  -name "$(basename "$NEW_TRACE")" -print -quit)
validate_atif "$TRACE_FILE" "$MARKER"
bash scripts/download-traces.sh > "$EVIDENCE/chief-local-trace-archive.txt"
```

In Phoenix at `http://SERVER:6006`, select project
`developer-community-chief-of-staff-e2e`. Require a completed top-level Agent
span plus LLM and tool children for the marker. Save a screenshot and confirm
that no credential value or unresolved OpenShell placeholder is visible.

Exercise the configured channel. For Slack, run:

```bash
python3 scripts/slack_delivery_diagnostic.py --mode dm \
  |& tee "$EVIDENCE/chief-slack.txt"
```

Require `Slack delivery diagnostic passed.` For Outlook, use the end-to-end
steps in `docs/set-up-outlook-bridge.md`. One working configured channel is
enough for this Relay acceptance test.

### Remote MinIO export and recovery

Capture local evidence, then recreate the deployment because export mode is
baked into the image:

```bash
bash scripts/tear-down.sh --stop-host-services
```

Change the ignored `.env` to:

```dotenv
ATIF_EXPORT_MODE=relay
ATIF_RELAY_BACKEND=minio
ATIF_RELAY_BUCKET=nemo-relay-traces
ATIF_RELAY_KEY_PREFIX=hermes/
```

Bring it up, run the common native checks again, and require both host services:

```bash
bash scripts/bring-up.sh |& tee "$EVIDENCE/chief-relay-bring-up.txt"
export SANDBOX=hermes-direct
curl -fsS http://127.0.0.1:6006/ >/dev/null
curl --cacert extras/atif-export-relay/tls/ca.crt \
  -fsS https://localhost:18443/healthz
docker compose -f extras/docker-compose.yml --profile '*' ps \
  | tee "$EVIDENCE/chief-relay-services.txt"
```

Load the private environment without echoing it and define a MinIO listing
helper:

```bash
set -a
. ./.env
set +a
export BUCKET="${ATIF_RELAY_BUCKET:-nemo-relay-traces}"
MINIO_USER="${NEMOCLAW_MINIO_ROOT_USER:-minioadmin}"
MINIO_PASSWORD="${NEMOCLAW_MINIO_ROOT_PASSWORD:-minioadmin}"
minio_keys() {
  docker run --rm --network=host \
    -e "MC_HOST_local=http://${MINIO_USER}:${MINIO_PASSWORD}@localhost:9000" \
    minio/mc ls --recursive "local/${BUCKET}/" | awk '{print $NF}' | sort
}
minio_key_for_marker() {
  local marker="$1" candidates="$2" key match=""
  while IFS= read -r key; do
    test -n "$key" || continue
    if docker run --rm --network=host \
      -e "MC_HOST_local=http://${MINIO_USER}:${MINIO_PASSWORD}@localhost:9000" \
      minio/mc cat "local/${BUCKET}/${key}" \
      | MARKER="$marker" python3 -c \
        'import os, sys; raise SystemExit(0 if os.environ["MARKER"] in sys.stdin.read() else 1)'
    then
      test -z "$match" || return 2
      match="$key"
    fi
  done < "$candidates"
  test -n "$match" || return 1
  printf '%s\n' "$match"
}
```

Run a uniquely marked tool turn. Its clean one-shot exit is the native session
boundary:

```bash
minio_keys > "$EVIDENCE/chief-minio-before.txt"
export MARKER="CHIEF-REMOTE-RELAY-$(date -u +%Y%m%dT%H%M%SZ)"
openshell sandbox exec --name "$SANDBOX" -- \
  env HERMES_HOME=/sandbox/.hermes-data hermes -z \
  "Use the terminal tool to print ${MARKER}, then reply with exactly ${MARKER}." \
  |& tee "$EVIDENCE/chief-remote-turn.txt"

OBJECT_KEY=""
for _ in $(seq 1 30); do
  minio_keys > "$EVIDENCE/chief-minio-after.txt"
  comm -13 "$EVIDENCE/chief-minio-before.txt" "$EVIDENCE/chief-minio-after.txt" \
    > "$EVIDENCE/chief-minio-new.txt"
  if OBJECT_KEY=$(minio_key_for_marker "$MARKER" \
    "$EVIDENCE/chief-minio-new.txt"); then
    break
  fi
  sleep 1
done
test -n "$OBJECT_KEY"
docker run --rm --network=host \
  -e "MC_HOST_local=http://${MINIO_USER}:${MINIO_PASSWORD}@localhost:9000" \
  minio/mc cat "local/${BUCKET}/${OBJECT_KEY}" \
  > "$EVIDENCE/chief-remote-trajectory.json"
validate_atif "$EVIDENCE/chief-remote-trajectory.json" "$MARKER"
```

Successful remote delivery must not create a matching local recovery file:

```bash
! openshell sandbox exec --name "$SANDBOX" -- env MARKER="$MARKER" python3 -c \
  'import glob, os, pathlib, sys; sys.exit(1 if any(os.environ["MARKER"] in pathlib.Path(p).read_text(errors="ignore") for p in glob.glob("/sandbox/atif/hermes-atif-*.json")) else 0)'
```

Confirm executable-bound egress. The approved Hermes Python process delivered
the prior object; an otherwise valid `curl` request must not:

```bash
export BLOCKED_OBJECT="blocked-$(date -u +%Y%m%dT%H%M%SZ).json"
STATUS=$(openshell sandbox exec --name "$SANDBOX" -- \
  env BLOCKED_OBJECT="$BLOCKED_OBJECT" bash -lc '
    curl -sS -o /tmp/atif-binary-probe.out -w "%{http_code}" \
      -X POST https://host.openshell.internal:18443/atif \
      -H "Authorization: Bearer ${ATIF_RELAY_AUTH_TOKEN}" \
      -H "Content-Type: application/json" \
      -H "X-NeMo-Relay-ATIF-Filename: ${BLOCKED_OBJECT}" \
      --data "{\"schema_version\":\"ATIF-v1.7\"}" || true
' | tail -n 1)
case "$STATUS" in 2*) echo "FAIL: curl received $STATUS"; exit 1;; esac
! minio_keys | grep -Fq "$BLOCKED_OBJECT"
openshell logs "$SANDBOX" --since 10m -n 5000 \
  > "$EVIDENCE/chief-binary-denial.log"
```

The expected status is `403`. Another non-`2xx` is acceptable only when the
object is absent and the OpenShell log explains the denial. A `2xx` or stored
object is a security failure.

Finally, stop the host relay and require native Relay's local recovery path:

```bash
RELAY_ID=$(docker compose -f extras/docker-compose.yml --profile '*' \
  ps -q atif-export-relay)
test -n "$RELAY_ID"
trap 'docker start "$RELAY_ID" >/dev/null 2>&1 || true' EXIT
minio_keys > "$EVIDENCE/chief-recovery-minio-before.txt"
docker stop "$RELAY_ID"
export RECOVERY_MARKER="CHIEF-RELAY-RECOVERY-$(date -u +%Y%m%dT%H%M%SZ)"
openshell sandbox exec --name "$SANDBOX" -- \
  env HERMES_HOME=/sandbox/.hermes-data hermes -z \
  "Use the terminal tool to print ${RECOVERY_MARKER}, then reply with exactly ${RECOVERY_MARKER}." \
  |& tee "$EVIDENCE/chief-recovery-turn.txt"

for _ in $(seq 1 90); do
  RECOVERY_PATH=$(openshell sandbox exec --name "$SANDBOX" -- \
    env MARKER="$RECOVERY_MARKER" python3 -c \
    'import glob, os, pathlib; print(next((p for p in glob.glob("/sandbox/atif/hermes-atif-*.json") if os.environ["MARKER"] in pathlib.Path(p).read_text(errors="ignore")), ""))')
  test -n "$RECOVERY_PATH" && break
  sleep 1
done
test -n "$RECOVERY_PATH"
openshell sandbox exec --name "$SANDBOX" -- cat "$RECOVERY_PATH" \
  > "$EVIDENCE/chief-recovery-trajectory.json"
validate_atif "$EVIDENCE/chief-recovery-trajectory.json" "$RECOVERY_MARKER"
minio_keys > "$EVIDENCE/chief-recovery-minio-after.txt"
comm -13 "$EVIDENCE/chief-recovery-minio-before.txt" \
  "$EVIDENCE/chief-recovery-minio-after.txt" \
  > "$EVIDENCE/chief-recovery-minio-new.txt"
while IFS= read -r key; do
  test -n "$key" || continue
  if docker run --rm --network=host \
    -e "MC_HOST_local=http://${MINIO_USER}:${MINIO_PASSWORD}@localhost:9000" \
    minio/mc cat "local/${BUCKET}/${key}" \
    | MARKER="$RECOVERY_MARKER" python3 -c \
      'import os, sys; raise SystemExit(0 if os.environ["MARKER"] in sys.stdin.read() else 1)'
  then
    echo "FAIL: recovery marker reached MinIO" >&2
    exit 1
  fi
done < "$EVIDENCE/chief-recovery-minio-new.txt"
docker start "$RELAY_ID"
trap - EXIT
```

Run one final remote turn to prove delivery resumed. Capture Relay, Hermes, and
OpenShell logs before teardown.

## Agentic AI Learning Path

After tearing down Chief of Staff, run from
`examples/recipes/nvidia/agentic-ai-learning-path`. Repeat the native,
ATIF, Phoenix, MinIO, executable-denial, and recovery procedures with these
substitutions:

| Item | Learning Path value |
| --- | --- |
| Phoenix project | `agentic-ai-learning-path-e2e` |
| Local marker prefix | `LEARNING-NATIVE-RELAY` |
| Remote marker prefix | `LEARNING-REMOTE-RELAY` |
| Recovery marker prefix | `LEARNING-RELAY-RECOVERY` |
| One-shot command | Add `--accept-hooks` before `-z` |
| Evidence filename prefix | `learning-` |

Before deployment, run the example's offline gate:

```bash
bash tests/validate-example.sh |& tee "$EVIDENCE/learning-offline.txt"
```

Require its final `VALIDATE: PASS`. Set real inference credentials and one
complete messaging channel in the ignored `.env`. Exercise that channel once.

Also run the workshop/operator smoke path from
`skills/setup-workshop-nemoclaw-operator/SKILL.md`: build and apply the derived
workshop policy, run `verify-sandbox-ready.sh`, stage the workshop skills, run
the README's one-shot setup prompt, forward port `8888`, and require the lab
page plus the 11 module tiles. This confirms that the simplified Hermes image
still supports the example's primary workflow. Use the Learning Path README,
not its vendored Chief-of-Staff verification prompt suite, as the authority.

## Payment Ops

Run from `examples/recipes/nvidia/payment-ops-hermes`. Copy `.env.example` to
the ignored `.env`, set `COMPATIBLE_API_KEY`, and run:

```bash
bash scripts/bring-up.sh |& tee "$EVIDENCE/payment-bring-up.txt"
bash scripts/verify.sh |& tee "$EVIDENCE/payment-verify.txt"
python3 scripts/smoke-payment.py |& tee "$EVIDENCE/payment-smoke.txt"
export SANDBOX=payment-ops
```

Run the common native checks. Confirm the host surfaces:

```bash
curl -fsS http://127.0.0.1:6006/ >/dev/null
curl -fsS http://127.0.0.1:8800/ >/dev/null
curl -fsS http://127.0.0.1:8642/health >/dev/null
curl -fsS http://127.0.0.1:8780/released \
  | tee "$EVIDENCE/payment-ledger-before.json"
```

Only ports `8800` (FinGuard) and `6006` (Phoenix) may be exposed publicly.
Keep Hermes `8642` loopback-only and the mock payment rail `8780` private.

Exercise real Hermes tool use through the FinGuard UI API:

```bash
curl -fsS -X POST http://127.0.0.1:8800/api/screen \
  -H 'Content-Type: application/json' -d '{"id":"WIRE-1007"}' \
  | tee "$EVIDENCE/payment-screen-wire.json"
curl -fsS -X POST http://127.0.0.1:8800/api/screen \
  -H 'Content-Type: application/json' -d '{"id":"ACH-2003"}' \
  | tee "$EVIDENCE/payment-screen-ach.json"
```

Require `WIRE-1007` to be `CLEARED_FOR_REVIEW`, `ACH-2003` to be held for
sanctions, and both responses to include a nonempty agent summary with
`evidence_source` equal to `hermes+nemo-relay`.

Test the maker/checker boundary and capture the HTTP status:

```bash
openshell logs "$SANDBOX" --since 10m -n 5000 \
  > "$EVIDENCE/payment-policy-before.log"
DENIALS_BEFORE=$(grep -Fc payments-rail.internal \
  "$EVIDENCE/payment-policy-before.log" || true)
curl -sS -o "$EVIDENCE/payment-agent-release.json" -w '%{http_code}\n' \
  -X POST http://127.0.0.1:8800/api/agent-release \
  -H 'Content-Type: application/json' -d '{"id":"WIRE-1007"}' \
  | tee "$EVIDENCE/payment-agent-release-status.txt"
curl -fsS http://127.0.0.1:8780/released \
  | tee "$EVIDENCE/payment-ledger-after-agent.json"
openshell logs "$SANDBOX" --since 10m -n 5000 \
  > "$EVIDENCE/payment-policy-denial.log"
DENIALS_AFTER=$(grep -Fc payments-rail.internal \
  "$EVIDENCE/payment-policy-denial.log" || true)
test "$(tail -n 1 "$EVIDENCE/payment-agent-release-status.txt")" = 403
cmp -s "$EVIDENCE/payment-ledger-before.json" \
  "$EVIDENCE/payment-ledger-after-agent.json"
test "$DENIALS_AFTER" -gt "$DENIALS_BEFORE"
```

Pass requires all three signals: HTTP `403`, an OpenShell policy denial for
`payments-rail.internal`, and an unchanged ledger. A failed `curl` alone does
not prove policy enforcement; it could be a DNS or TLS failure.

Exercise the separate human path through the UI API, not
`approve_release.py`, because the UI path emits the host audit span:

```bash
curl -fsS -X POST http://127.0.0.1:8800/api/human-release \
  -H 'Content-Type: application/json' \
  -d '{"id":"WIRE-1007","approver":"E2E Operator"}' \
  | tee "$EVIDENCE/payment-human-wire.json"
curl -sS -o "$EVIDENCE/payment-human-ach.json" -w '%{http_code}\n' \
  -X POST http://127.0.0.1:8800/api/human-release \
  -H 'Content-Type: application/json' \
  -d '{"id":"ACH-2003","approver":"E2E Operator"}' \
  | tee "$EVIDENCE/payment-human-ach-status.txt"
```

Require the cleared wire to be released and the held ACH to return `409`.
In Phoenix, project `finguard-payment-ops` must contain native Relay Agent,
LLM, and tool spans for the live prompts. It must also contain separately
attributed `finguard-host-checker` spans with `actor.type=human` for the host
release decisions.

Create a deterministic native session boundary and validate the ATIF file:

```bash
openshell sandbox exec --name "$SANDBOX" -- sh -lc \
  'find /sandbox/atif -maxdepth 1 -type f -name "hermes-atif-*.json" -print | sort' \
  > "$EVIDENCE/payment-atif-before.txt"
export MARKER="PAYMENT-NATIVE-RELAY-$(date -u +%Y%m%dT%H%M%SZ)"
openshell sandbox exec --name "$SANDBOX" -- hermes chat --query \
  "Use payment-screening to screen WIRE-1007; execute the bundled screener, report every check, and include ${MARKER}." \
  |& tee "$EVIDENCE/payment-finalized-turn.txt"
openshell sandbox exec --name "$SANDBOX" -- sh -lc \
  'find /sandbox/atif -maxdepth 1 -type f -name "hermes-atif-*.json" -print | sort' \
  > "$EVIDENCE/payment-atif-after.txt"
comm -13 "$EVIDENCE/payment-atif-before.txt" "$EVIDENCE/payment-atif-after.txt" \
  > "$EVIDENCE/payment-atif-new.txt"
MATCHING_TRACE=$(openshell sandbox exec --name "$SANDBOX" -- \
  env MARKER="$MARKER" python3 -c \
  'import glob, os, pathlib; m=[p for p in glob.glob("/sandbox/atif/hermes-atif-*.json") if os.environ["MARKER"] in pathlib.Path(p).read_text(errors="ignore")]; assert len(m) == 1, m; print(m[0])')
grep -Fxq -- "$MATCHING_TRACE" "$EVIDENCE/payment-atif-new.txt"
NEW_TRACE="$MATCHING_TRACE"
bash scripts/download-traces.sh "$EVIDENCE/payment-atif"
TRACE_FILE=$(find "$EVIDENCE/payment-atif" -type f \
  -name "$(basename "$NEW_TRACE")" -print -quit)
validate_atif "$TRACE_FILE" "$MARKER"
```

Then rerun `bash scripts/bring-up.sh`; it must report that it is reusing the
healthy sandbox. Run `bash scripts/verify.sh` again. Reuse validates health,
exact versions, and zero native Relay config diagnostics; it does not compare
every configuration byte.

## Teardown

Capture these before deleting each sandbox:

```bash
openshell logs "$SANDBOX" --since 30m -n 5000 \
  > "$EVIDENCE/$SANDBOX-openshell.log"
openshell sandbox exec --name "$SANDBOX" -- tail -n 500 /tmp/gateway.log \
  > "$EVIDENCE/$SANDBOX-gateway.log" 2>&1 || true
```

For Chief of Staff and Learning Path:

```bash
bash scripts/download-traces.sh > "$EVIDENCE/$SANDBOX-trace-archive.txt"
bash scripts/tear-down.sh --stop-host-services
```

For Payment Ops:

```bash
bash scripts/download-traces.sh "$EVIDENCE/payment-final-traces"
bash scripts/tear-down.sh --destroy-sandbox
```

Use `--purge-host-services` or `--destroy-sandbox` only after confirming the
evidence is no longer needed. Verify the sandbox is absent and its Compose
services are stopped.

## Final report

Return a concise report with:

1. Commit SHA, host architecture, Docker version, and OpenShell version.
2. One `PASS`, `FAIL`, or `BLOCKED` row for every acceptance criterion above.
3. Hermes/Relay versions and Relay diagnostic counts for each deployment.
4. Sanitized proof of the real response, Phoenix trace, local ATIF, remote
   object, denied executable, recovery copy, and Payment Ops boundary.
5. The first failing command and relevant sanitized log excerpt for any failure.
6. Confirmation that teardown completed and no credentials entered the report.

Do not describe a missing trajectory immediately after an API turn as a Relay
failure. Native Relay finalizes the top-level Agent scope and ATIF trajectory at
a real Hermes session boundary: a one-shot CLI exit, `/new`, `/reset`, session
deletion, or configured expiry.
