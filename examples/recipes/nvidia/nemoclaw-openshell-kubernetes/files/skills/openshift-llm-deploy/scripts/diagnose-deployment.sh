#!/bin/sh
# Collect a bounded, credential-safe diagnosis for a model deployment. This is
# intentionally read-only so Hermes can show a useful cause instead of an
# opaque terminal failure.
set -u

# Hermes tool executions do not inherit the container's chart PATH.
export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

usage() {
  cat >&2 <<'EOF'
usage: diagnose-deployment.sh --namespace NAME --release NAME [--apply-log FILE]
EOF
  exit 64
}

namespace=
release=
apply_log=

while [ "$#" -gt 0 ]; do
  case "$1" in
    --namespace) namespace=${2:-}; shift 2 ;;
    --release) release=${2:-}; shift 2 ;;
    --apply-log) apply_log=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done

[ -n "$namespace" ] && [ -n "$release" ] || usage

workdir=$(mktemp -d "${TMPDIR:-/tmp}/hermes-llm-diagnose.XXXXXX") || exit 1
trap 'rm -rf "$workdir"' EXIT HUP INT TERM
label="app.kubernetes.io/instance=$release"

redact() {
  sed -E \
    -e 's/hf_[A-Za-z0-9_-]+/[REDACTED_HF_TOKEN]/g' \
    -e 's/(Authorization: Bearer )[A-Za-z0-9._-]+/\1[REDACTED]/g' \
    -e 's/(HF_TOKEN=)[^[:space:]]+/\1[REDACTED]/g'
}

if [ -n "$apply_log" ] && [ -r "$apply_log" ]; then
  tail -n 80 "$apply_log" >"$workdir/apply.log" 2>&1 || true
fi

oc -n "$namespace" get dynamographdeployments.nvidia.com "$release" -o yaml \
  >"$workdir/dgd.txt" 2>&1 || true
oc -n "$namespace" get deployment,statefulset,job,service,pvc -l "$label" -o wide \
  >"$workdir/resources.txt" 2>&1 || true
oc -n "$namespace" get deployment -l "$label" -o json \
  >"$workdir/deployments.json" 2>/dev/null || printf '{"items": []}\n' >"$workdir/deployments.json"
oc -n "$namespace" get pods -o json >"$workdir/pods.json" 2>/dev/null || printf '{"items": []}\n' >"$workdir/pods.json"
oc -n "$namespace" get events -o json >"$workdir/events.json" 2>/dev/null || printf '{"items": []}\n' >"$workdir/events.json"

standard_vllm_ready=$(python3 - "$workdir/deployments.json" <<'PY'
import json
import sys

try:
    deployments = json.load(open(sys.argv[1], encoding="utf-8")).get("items", [])
except Exception:
    deployments = []

for deployment in deployments:
    spec = deployment.get("spec", {}) or {}
    status = deployment.get("status", {}) or {}
    desired = spec.get("replicas", 1)
    available = status.get("availableReplicas", 0) or 0
    if desired and available >= desired:
        print("true")
        break
else:
    print("false")
PY
)

dynamo_ready=$(oc -n "$namespace" get dynamographdeployments.nvidia.com "$release" \
  -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{"\n"}{end}' 2>/dev/null \
  | grep -Fx 'Ready=True' >/dev/null && printf 'true' || printf 'false')

python3 - "$workdir/pods.json" "$release" >"$workdir/pods.txt" <<'PY'
import json
import sys

try:
    pods = json.load(open(sys.argv[1], encoding="utf-8")).get("items", [])
except Exception:
    pods = []
release = sys.argv[2]
for pod in pods:
    metadata = pod.get("metadata", {})
    labels = metadata.get("labels", {}) or {}
    name = metadata.get("name", "")
    if labels.get("app.kubernetes.io/instance") == release or name.startswith(release):
        print(name)
PY

pod_count=0
while IFS= read -r pod; do
  [ -n "$pod" ] || continue
  pod_count=$((pod_count + 1))
  [ "$pod_count" -le 3 ] || break
  safe_name=$(printf '%s' "$pod" | tr -cd 'A-Za-z0-9._-')
  oc -n "$namespace" describe pod "$pod" >"$workdir/pod-$safe_name.describe" 2>&1 || true
  if ! oc -n "$namespace" logs "$pod" --all-containers --tail=80 --previous \
    >"$workdir/pod-$safe_name.logs" 2>&1; then
    oc -n "$namespace" logs "$pod" --all-containers --tail=80 \
      >"$workdir/pod-$safe_name.logs" 2>&1 || true
  fi
done <"$workdir/pods.txt"

python3 - "$workdir/events.json" "$release" >"$workdir/events.txt" <<'PY'
import json
import sys

try:
    events = json.load(open(sys.argv[1], encoding="utf-8")).get("items", [])
except Exception:
    events = []
release = sys.argv[2]
selected = []
for event in events:
    involved = event.get("involvedObject", {}) or {}
    name = involved.get("name", "")
    message = event.get("message", "") or ""
    if name.startswith(release) or release in message:
        stamp = event.get("eventTime") or event.get("lastTimestamp") or event.get("metadata", {}).get("creationTimestamp", "")
        selected.append((stamp, event.get("type", ""), event.get("reason", ""), involved.get("kind", ""), name, message))
for row in sorted(selected)[-20:]:
    print(" | ".join(str(value).replace("\n", " ") for value in row))
PY

result=failed
backend=

if [ "$standard_vllm_ready" = 'true' ]; then
  result=ready
  backend=standard-vllm
  cause='none'
  action='The standard vLLM fallback is available. No retry or replacement action is required.'
elif [ "$dynamo_ready" = 'true' ]; then
  result=ready
  backend=dynamo
  cause='none'
  action='The DynamoGraphDeployment is Ready. No retry or replacement action is required.'
elif grep -Eqi 'did not have enough free storage|CSIStorageCapacity|node\.ocs\.openshift\.io/storage|persistentvolumeclaim.*pending|pod has unbound immediate PersistentVolumeClaims|volume node affinity conflict|node affinity conflict|FailedAttachVolume|FailedMount' "$workdir"/* 2>/dev/null; then
  cause='storage-or-pvc-placement'
  action='Inspect the user-selected PVC storage class, selected-node taints, and CSIStorageCapacity. Ask the user to choose again from the current storage-class inventory before changing classes; use a node-local class only on a selected node with verified node-local capacity. Do not retry the same placement blindly.'
elif grep -Eqi 'Insufficient nvidia.com/gpu|Insufficient cpu|Insufficient memory|didn.t match Pod.s node affinity|node.s didn.t match|FailedScheduling' "$workdir"/* 2>/dev/null; then
  cause='scheduler-capacity-or-node-selection'
  action='Inspect GPU requests by node and choose a node with sufficient allocatable GPUs, CPU, memory, and matching labels.'
elif grep -Eqi 'Illegal option -o pipefail|unsupported-pipefail-shell-wrapper|fallback-command-override' "$workdir"/* 2>/dev/null; then
  cause='unsupported-fallback-shell-wrapper'
  action='Re-render the stock fallback template with flags-only VLLM_ARGS. Do not add command overrides, shell bootstrap code, or pipefail under /bin/sh.'
elif grep -Eqi 'unable to validate against any security context constraint|RoleBinding.*forbidden|cannot bind.*system:openshift:scc' "$workdir"/* 2>/dev/null; then
  cause='dynamo-service-account-scc-prerequisite'
  action='A human OpenShift administrator may grant anyuid only to the reported Dynamo service account with oc adm policy add-scc-to-user, then approve one retry. Hermes must not grant SCC or cluster-admin privileges.'
elif grep -Eqi 'ImagePullBackOff|ErrImagePull|pull access denied|manifest unknown|unauthorized: authentication required' "$workdir"/* 2>/dev/null; then
  cause='image-pull-or-registry-credential'
  action='Verify the pinned runtime image and the name of the existing image-pull Secret. Do not expose registry credentials in chat.'
elif grep -Eqi 'CreateContainerConfigError|secret .* not found|configmap .* not found' "$workdir"/* 2>/dev/null; then
  cause='missing-workload-reference'
  action='Verify the named Secret, ConfigMap, ServiceAccount, and PVC exist in the selected namespace. Credential values must not be read.'
elif grep -Eqi 'cannot import name .increment_coord.|nvidia_cutlass_dsl|vllm_flash_attn.*cutlass' "$workdir"/* 2>/dev/null; then
  cause='dynamo-vllm-runtime-dependency-incompatible'
  action='The selected Dynamo vLLM runtime has an incompatible CUTLASS or FlashAttention dependency for this model. Preserve the cache PVC and use the already-approved standard vLLM fallback; do not retry the same Dynamo image.'
elif grep -Eqi 'CrashLoopBackOff|RunContainerError|Error:|Traceback|fatal:' "$workdir"/* 2>/dev/null; then
  cause='runtime-startup-failure'
  action='Review the bounded pod log excerpt below. Change runtime/backend only when the error proves an incompatibility; do not retry indefinitely.'
elif grep -Eqi 'no matches for kind .*DynamoGraphDeployment|the server could not find the requested resource|requested resource not found' "$workdir"/* 2>/dev/null; then
  cause='dynamo-crd-unavailable'
  action='Use the approved standard vLLM fallback. Do not install or upgrade Dynamo from this model deployment skill.'
else
  cause='deployment-not-ready'
  action='Use the resource state, events, and pod details below to resolve the reported condition before another attempt.'
fi

printf '%s\n' \
  "DIAGNOSIS_RESULT=$result" \
  "DIAGNOSIS_RELEASE=$release" \
  "DIAGNOSIS_NAMESPACE=$namespace" \
  "DIAGNOSIS_CAUSE=$cause" \
  "DIAGNOSIS_ACTION=$action"
[ -n "$backend" ] && printf '%s\n' "DIAGNOSIS_BACKEND=$backend"

printf '\nMODEL_DEPLOYMENT_RESOURCES:\n'
cat "$workdir/resources.txt" 2>/dev/null || true
printf '\nMODEL_DEPLOYMENT_EVENTS:\n'
if [ -s "$workdir/events.txt" ]; then
  redact <"$workdir/events.txt"
else
  printf '%s\n' 'No release-matching events were returned.'
fi
printf '\nMODEL_DEPLOYMENT_EVIDENCE:\n'
for evidence in "$workdir"/apply.log "$workdir"/dgd.txt "$workdir"/pod-*.describe "$workdir"/pod-*.logs; do
  [ -f "$evidence" ] || continue
  printf '%s\n' "--- $(basename "$evidence") ---"
  tail -n 80 "$evidence" | redact
done
