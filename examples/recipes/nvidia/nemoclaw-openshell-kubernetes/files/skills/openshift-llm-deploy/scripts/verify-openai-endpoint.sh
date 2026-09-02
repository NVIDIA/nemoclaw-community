#!/bin/sh
# Verify an OpenAI-compatible endpoint through the Kubernetes Service proxy.
# This works with the chart's bounded HTTP API proxy and needs no streaming tunnel.
set -eu

export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

usage() {
  cat >&2 <<'EOF'
usage: verify-openai-endpoint.sh --namespace NAME --service NAME [--model MODEL] [--timeout SECONDS]
EOF
  exit 64
}

namespace=
service=
requested_model=
timeout_seconds=300

while [ "$#" -gt 0 ]; do
  case "$1" in
    --namespace) namespace=${2:-}; shift 2 ;;
    --service) service=${2:-}; shift 2 ;;
    --model) requested_model=${2:-}; shift 2 ;;
    --timeout) timeout_seconds=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done

[ -n "$namespace" ] && [ -n "$service" ] || usage
case "$namespace" in *[!a-z0-9-]*|-*|*-) usage ;; esac
case "$service" in *[!a-z0-9-]*|-*|*-) usage ;; esac
case "$timeout_seconds" in ''|*[!0-9]*) usage ;; esac

workdir=$(mktemp -d "${TMPDIR:-/tmp}/hermes-llm-verify.XXXXXX") || exit 1
trap 'rm -rf "$workdir"' EXIT HUP INT TERM
service_proxy="/api/v1/namespaces/$namespace/services/http:$service:8000/proxy"
deadline=$(( $(date +%s) + timeout_seconds ))

while [ "$(date +%s)" -lt "$deadline" ]; do
  if oc get --raw="$service_proxy/health" >"$workdir/health.json" 2>"$workdir/health.err" && \
     oc get --raw="$service_proxy/v1/models" >"$workdir/models.json" 2>"$workdir/models.err"; then
    break
  fi
  sleep 10
done

if [ ! -s "$workdir/models.json" ]; then
  reason=$(tail -n 3 "$workdir/models.err" "$workdir/health.err" 2>/dev/null | tr '\n' ' ' | tr -s ' ')
  [ -n "$reason" ] || reason='service-health-or-model-list-not-ready'
  printf '%s\n' \
    'VERIFY_RESULT=pending' \
    "VERIFY_SERVICE=$service" \
    "VERIFY_REASON=$reason" \
    "VERIFY_WAITED_SECONDS=$timeout_seconds"
  exit 1
fi

served_model=$(python3 - "$workdir/models.json" "$requested_model" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
models = [item.get("id", "") for item in data.get("data", []) if item.get("id")]
requested = sys.argv[2]
if requested and requested in models:
    print(requested)
elif models:
    print(models[0])
PY
)

if [ -z "$served_model" ]; then
  printf '%s\n' 'VERIFY_RESULT=failed' "VERIFY_SERVICE=$service" \
    'VERIFY_REASON=v1-models-returned-no-model-id'
  exit 2
fi

python3 - "$workdir/simple.json" "$served_model" <<'PY'
import json
import sys

json.dump(
    {
        "model": sys.argv[2],
        "messages": [{"role": "user", "content": "Reply with exactly: model endpoint ready"}],
        "max_tokens": 256,
        "temperature": 0,
    },
    open(sys.argv[1], "w", encoding="utf-8"),
)
PY
if ! oc create --raw="$service_proxy/v1/chat/completions" -f "$workdir/simple.json" \
  >"$workdir/simple-response.json" 2>"$workdir/simple.err" || \
  ! python3 - "$workdir/simple-response.json" <<'PY'
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
    message = payload.get("choices", [{}])[0].get("message", {})
    assert message.get("content") is not None or message.get("reasoning_content") is not None or message.get("tool_calls")
except Exception:
    raise SystemExit(1)
PY
then
  detail=$(head -c 400 "$workdir/simple-response.json" "$workdir/simple.err" 2>/dev/null | tr '\n' ' ' | tr -s ' ' | sed -E 's/hf_[A-Za-z0-9_-]+/[REDACTED_HF_TOKEN]/g')
  printf '%s\n' 'VERIFY_RESULT=failed' "VERIFY_SERVICE=$service" \
    "VERIFY_MODEL=$served_model" 'VERIFY_REASON=chat-completions-request-failed' \
    "VERIFY_RESPONSE=$detail"
  exit 2
fi

simple_finish_reason=$(python3 - "$workdir/simple-response.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(payload.get("choices", [{}])[0].get("finish_reason", "unknown"))
PY
)

python3 - "$workdir/tool.json" "$served_model" <<'PY'
import json
import sys

json.dump(
    {
        "model": sys.argv[2],
        "messages": [{"role": "user", "content": "Call the get_cluster_time tool now. Do not answer with prose."}],
        "tools": [{"type": "function", "function": {"name": "get_cluster_time", "description": "Return the current UTC time.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}],
        "tool_choice": "required",
        "max_tokens": 256,
        "temperature": 0,
    },
    open(sys.argv[1], "w", encoding="utf-8"),
)
PY
tool_result=not-observed
if oc create --raw="$service_proxy/v1/chat/completions" -f "$workdir/tool.json" \
  >"$workdir/tool-response.json" 2>"$workdir/tool.err"; then
  if python3 - "$workdir/tool-response.json" <<'PY'
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
    message = payload.get("choices", [{}])[0].get("message", {})
    assert message.get("tool_calls") or message.get("function_call")
except Exception:
    raise SystemExit(1)
PY
  then
    tool_result=passed
  fi
else
  tool_result=not-supported-or-rejected
fi

printf '%s\n' \
  'VERIFY_RESULT=ready' \
  "VERIFY_SERVICE=$service" \
  "VERIFY_MODEL=$served_model" \
  'VERIFY_SIMPLE_COMPLETION=passed' \
  "VERIFY_SIMPLE_FINISH_REASON=$simple_finish_reason" \
  "VERIFY_TOOL_CALL=$tool_result" \
  "VERIFY_TRANSPORT=kubernetes-service-proxy/$service"

if [ -n "$requested_model" ] && [ "$requested_model" != "$served_model" ]; then
  printf '%s\n' "VERIFY_REQUESTED_MODEL_NOT_ADVERTISED=$requested_model"
fi
