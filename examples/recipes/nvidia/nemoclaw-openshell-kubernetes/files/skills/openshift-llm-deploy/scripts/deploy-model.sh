#!/bin/sh
# Render and run one chart-governed Dynamo-first deployment. This wrapper keeps
# manifest construction out of model-generated shell commands.
set -eu

# Hermes tool executions do not inherit the container's chart PATH.
export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

usage() {
  cat >&2 <<'EOF'
usage: deploy-model.sh \
  --namespace NAME --release NAME --model MODEL --node NODE --gpus COUNT \
  --storage-class NAME --pvc-size SIZE --memory-request QUANTITY \
  --memory-limit QUANTITY --hf-secret NAME --platform openshift|kubernetes \
  [--max-model-len TOKENS] [--deployment-mode dynamo|standard-vllm] \
  [--dynamo-backend vllm|trtllm] \
  [--trtllm-engine-args ARGUMENTS] [--allow-fallback] [--expose]
EOF
  exit 64
}

namespace=
release=
model=
node=
gpus=
storage_class=
pvc_size=
memory_request=
memory_limit=
hf_secret=
platform=
max_model_len=32768
deployment_mode=dynamo
dynamo_backend=vllm
trtllm_engine_args=
# A confirmed Dynamo deployment automatically moves to standard vLLM only
# after an explicit Dynamo failure. The skill's confirmation covers this.
allow_fallback=true
expose=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --namespace) namespace=${2:-}; shift 2 ;;
    --release) release=${2:-}; shift 2 ;;
    --model) model=${2:-}; shift 2 ;;
    --node) node=${2:-}; shift 2 ;;
    --gpus) gpus=${2:-}; shift 2 ;;
    --storage-class) storage_class=${2:-}; shift 2 ;;
    --pvc-size) pvc_size=${2:-}; shift 2 ;;
    --memory-request) memory_request=${2:-}; shift 2 ;;
    --memory-limit) memory_limit=${2:-}; shift 2 ;;
    --hf-secret) hf_secret=${2:-}; shift 2 ;;
    --platform) platform=${2:-}; shift 2 ;;
    --max-model-len) max_model_len=${2:-}; shift 2 ;;
    --deployment-mode) deployment_mode=${2:-}; shift 2 ;;
    --dynamo-backend) dynamo_backend=${2:-}; shift 2 ;;
    --trtllm-engine-args) trtllm_engine_args=${2:-}; shift 2 ;;
    --allow-fallback) allow_fallback=true; shift ;;
    --expose) expose=true; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

emit_failure() {
  reason=$1
  action=$2
  printf '%s\n' \
    'DEPLOYMENT_RESULT=failed' \
    "DEPLOYMENT_REASON=$reason" \
    "DEPLOYMENT_ACTION=$action"
  exit 0
}

if [ -z "$namespace" ] || [ -z "$release" ] || [ -z "$model" ] || [ -z "$node" ] || \
  [ -z "$gpus" ] || [ -z "$storage_class" ] || [ -z "$pvc_size" ] || \
  [ -z "$memory_request" ] || [ -z "$memory_limit" ] || [ -z "$hf_secret" ] || \
  [ -z "$platform" ]; then
  emit_failure 'missing-required-deployment-input' 'Collect the missing deployment values, then run this wrapper once. Do not render a manifest manually.'
fi

case "$platform" in openshift|kubernetes) ;; *) emit_failure 'invalid-platform' 'Use openshift or kubernetes.' ;; esac
case "$deployment_mode" in dynamo|standard-vllm) ;; *) emit_failure 'invalid-deployment-mode' 'Use dynamo or standard-vllm.' ;; esac
case "$dynamo_backend" in vllm|trtllm) ;; *) emit_failure 'invalid-dynamo-backend' 'Use vllm or trtllm.' ;; esac
case "$gpus" in ''|*[!0-9]*) emit_failure 'invalid-gpu-count' 'Use a positive integer GPU count.' ;; esac
case "$max_model_len" in ''|*[!0-9]*) emit_failure 'invalid-max-model-len' 'Use a positive integer max model length.' ;; esac
if [ "$gpus" -lt 1 ] || [ "$max_model_len" -lt 1 ]; then
  emit_failure 'invalid-numeric-deployment-input' 'GPU count and max model length must both be greater than zero.'
fi

model=${model#https://huggingface.co/}
model=${model%/}
case "$model" in ''|/*|*//*|*[!A-Za-z0-9._/-]*) emit_failure 'invalid-hugging-face-model-id' 'Use a Hugging Face repository ID in the form organization/model.' ;; esac
case "$release" in *[!a-z0-9-]*|-*|*-) emit_failure 'invalid-release-name' 'Use a lowercase DNS-1123 release name without leading or trailing hyphens.' ;; esac
if [ "${#release}" -gt 40 ]; then
  emit_failure 'release-name-too-long' 'Use a release name of 40 characters or fewer so Dynamo service-account names remain valid.'
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
skill_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
defaults_file="$skill_root/dynamo-defaults.yaml"
renderer="$script_dir/render-template.py"
launcher="$script_dir/dynamo-first-deploy.sh"
diagnose="$script_dir/diagnose-deployment.sh"
resolver="$script_dir/resolve-vllm-image.sh"
dynamo_resolver="$script_dir/resolve-dynamo-image.sh"

for required in "$defaults_file" "$renderer" "$launcher" "$diagnose" "$resolver" "$dynamo_resolver"; do
  [ -r "$required" ] || emit_failure 'skill-runtime-incomplete' 'The chart-provided deployment skill is incomplete. Reconcile the Helm release before retrying.'
done

# The model-cache PVC and downloader are pinned to the selected GPU node.
# Reject placements that the scheduler already proves cannot work before a Job,
# PVC, or token-bearing downloader is created. TopoLVM is node-local: a class
# can exist cluster-wide while having no capacity on the selected node.
storage_provisioner=$(oc get storageclass "$storage_class" -o jsonpath='{.provisioner}' 2>/dev/null || true)
[ -n "$storage_provisioner" ] || \
  emit_failure 'storage-class-not-found' 'Select one of the storage classes presented to the user, then run this wrapper with that exact class name.'

if ! oc get node "$node" >/dev/null 2>&1; then
  emit_failure 'selected-node-not-found' 'Select an existing GPU node, then run the chart-managed wrapper again.'
fi

storage_taint_effects=$(oc get node "$node" \
  -o jsonpath='{range .spec.taints[?(@.key=="node.ocs.openshift.io/storage")]}{.effect}{" "}{end}' \
  2>/dev/null || true)
case " $storage_taint_effects " in
  *' NoSchedule '*)
    emit_failure 'selected-node-storage-tainted' 'The selected node is reserved for OpenShift storage and this chart does not tolerate that taint. Select an untainted GPU node, then revalidate the user-selected storage class.'
    ;;
esac

if [ "$storage_provisioner" = 'topolvm.io' ]; then
  storage_capacity_json=$(oc get csistoragecapacity -A -o json 2>/dev/null || true)
  [ -n "$storage_capacity_json" ] || \
    emit_failure 'node-local-storage-capacity-unverified' 'TopoLVM capacity could not be inspected. Select a node with verified capacity for the user-selected class, or return to storage-class selection.'
  storage_capacity_state=$(printf '%s' "$storage_capacity_json" | python3 -c '
import json
import re
import sys

storage_class, node, requested = sys.argv[1:]
try:
    items = json.load(sys.stdin).get("items", [])
except (json.JSONDecodeError, OSError):
    raise SystemExit(1)

def quantity(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]+)?", str(value or ""))
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2) or ""
    factors = {
        "": 1, "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40,
        "Pi": 2**50, "Ei": 2**60, "K": 10**3, "M": 10**6,
        "G": 10**9, "T": 10**12, "P": 10**15, "E": 10**18,
    }
    factor = factors.get(suffix)
    return None if factor is None else number * factor

requested_bytes = quantity(requested)
if requested_bytes is None:
    print("request-unparseable")
    raise SystemExit(0)

for item in items:
    if item.get("storageClassName") != storage_class:
        continue
    labels = (item.get("nodeTopology") or {}).get("matchLabels") or {}
    if labels.get("topology.topolvm.io/node") != node:
        continue
    available_bytes = quantity(item.get("capacity"))
    if available_bytes is not None and available_bytes >= requested_bytes:
        print("available")
        raise SystemExit(0)
print("unavailable")
' "$storage_class" "$node" "$pvc_size" 2>/dev/null || true)
  case "$storage_capacity_state" in
    available) ;;
    request-unparseable)
      emit_failure 'node-local-storage-request-unparseable' 'Use a Kubernetes storage quantity such as 20Gi, then revalidate the user-selected storage class and node.'
      ;;
    *)
      emit_failure 'node-local-storage-unavailable-on-selected-node' 'The selected node-local class has no verified capacity for this PVC on the selected node. Select a node with CSIStorageCapacity or return to storage-class selection.'
      ;;
  esac
fi

yaml_value() {
  key=$1
  value=$(awk -F ': ' -v wanted="$key" '$1 == wanted {print $2; exit}' "$defaults_file" | sed -e 's/^"//' -e 's/"$//')
  [ -n "$value" ] || return 1
  printf '%s\n' "$value"
}

dynamo_image=
dynamo_runtime_version=
case "$dynamo_backend" in
  vllm)
    dynamo_resolution=$(sh "$dynamo_resolver" \
      --default-image "$(yaml_value vllmRuntimeImage || true)" \
      --default-runtime-version "$(yaml_value vllmRuntimeVersion || true)" \
      --backend vllm --model "$model" --overrides-file "$defaults_file") || \
      emit_failure 'dynamo-release-resolution-failed' 'The chart-provided Dynamo resolver failed. Reconcile the Helm release before retrying.'
    dynamo_image=$(printf '%s\n' "$dynamo_resolution" | awk -F= '$1 == "DYNAMO_IMAGE" {print $2; exit}')
    [ -n "$dynamo_image" ] || \
      emit_failure 'dynamo-release-resolution-invalid' 'The Dynamo resolver did not return an image. Reconcile the Helm release before retrying.'
    dynamo_template="$skill_root/templates/dynamo-vllm-graph-deployment.yaml"
    ;;
  trtllm)
    [ -n "$trtllm_engine_args" ] || emit_failure 'trtllm-engine-args-required' 'Use TensorRT-LLM only with a known engine configuration path.'
    dynamo_resolution=$(sh "$dynamo_resolver" \
      --default-image "$(yaml_value tensorrtllmRuntimeImage || true)" \
      --default-runtime-version "$(yaml_value tensorrtllmRuntimeVersion || true)" \
      --backend trtllm --model "$model" --overrides-file "$defaults_file") || \
      emit_failure 'dynamo-release-resolution-failed' 'The chart-provided Dynamo resolver failed. Reconcile the Helm release before retrying.'
    dynamo_image=$(printf '%s\n' "$dynamo_resolution" | awk -F= '$1 == "DYNAMO_IMAGE" {print $2; exit}')
    [ -n "$dynamo_image" ] || \
      emit_failure 'dynamo-release-resolution-invalid' 'The Dynamo resolver did not return an image. Reconcile the Helm release before retrying.'
    dynamo_template="$skill_root/templates/dynamo-tensorrtllm-graph-deployment.yaml"
    ;;
esac
dynamo_runtime_version=$(printf '%s\n' "$dynamo_resolution" | awk -F= '$1 == "DYNAMO_RUNTIME_VERSION" {print $2; exit}')
printf '%s\n' "$dynamo_runtime_version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || \
  emit_failure 'dynamo-release-resolution-invalid' 'The Dynamo resolver did not return a valid runtime compatibility version. Reconcile the Helm release before retrying.'
fallback_image=$(yaml_value standardVllmImage || true)
observation_timeout=$(yaml_value observationTimeoutSeconds || true)
verification_timeout=$(yaml_value verificationTimeoutSeconds || true)
download_observation_timeout=$(yaml_value downloadObservationTimeoutSeconds || true)
download_timeout=$(yaml_value downloadTimeoutSeconds || true)
image_pull_secret_name=$(yaml_value imagePullSecretName || true)
[ -n "$dynamo_image" ] && [ -n "$fallback_image" ] && [ -n "$observation_timeout" ] && [ -n "$verification_timeout" ] && [ -n "$download_observation_timeout" ] && [ -n "$download_timeout" ] || \
  emit_failure 'dynamo-defaults-invalid' 'The chart-provided Dynamo defaults are incomplete. Reconcile the Helm release before retrying.'

dynamo_image_pull_secrets='[]'
if [ -n "$image_pull_secret_name" ]; then
  case "$image_pull_secret_name" in
    *[!a-z0-9-]*|-*|*-)
      emit_failure 'invalid-image-pull-secret-name' 'Set modelDeployment.dynamo.imagePullSecretName to one existing DNS-1123 Secret name, without exposing its value.'
      ;;
  esac
  if [ "${#image_pull_secret_name}" -gt 63 ]; then
    emit_failure 'invalid-image-pull-secret-name' 'Set modelDeployment.dynamo.imagePullSecretName to one existing DNS-1123 Secret name of 63 characters or fewer.'
  fi
  dynamo_image_pull_secrets=$(printf '[{"name":"%s"}]' "$image_pull_secret_name")
fi

vllm_resolution=$(sh "$resolver" --default-image "$fallback_image" --model "$model" --overrides-file "$defaults_file") || \
  emit_failure 'vllm-release-resolution-failed' 'The chart-provided vLLM resolver failed. Reconcile the Helm release before retrying.'
resolved_vllm_image=$(printf '%s\n' "$vllm_resolution" | awk -F= '$1 == "VLLM_IMAGE" {print $2; exit}')
[ -n "$resolved_vllm_image" ] || \
  emit_failure 'vllm-release-resolution-invalid' 'The vLLM resolver did not return an image. Reconcile the Helm release before retrying.'
fallback_image=$resolved_vllm_image

hf_intake_file="$skill_root/hf-token-intake.yaml"
[ -r "$hf_intake_file" ] || emit_failure 'hf-token-intake-config-missing' 'The chart-provided external Secret reference is missing. Reconcile the Helm release before retrying.'
hf_intake_value() {
  key=$1
  awk -F ': ' -v wanted="$key" '$1 == wanted {print $2; exit}' "$hf_intake_file" | sed -e 's/^"//' -e 's/"$//'
}
configured_namespace=$(hf_intake_value namespace)
configured_hf_secret=$(hf_intake_value secretName)
configured_hf_secret_key=$(hf_intake_value secretKey)
model_runner_service_account=$(hf_intake_value modelRunnerServiceAccount)
[ -n "$configured_namespace" ] && [ -n "$configured_hf_secret" ] && \
  [ -n "$configured_hf_secret_key" ] && [ -n "$model_runner_service_account" ] || \
  emit_failure 'hf-token-intake-config-invalid' 'The chart external Secret reference or model runner identity is incomplete.'
[ "$namespace" = "$configured_namespace" ] || \
  emit_failure 'unexpected-model-namespace' 'Use only the target namespace configured by Helm for this skill.'
[ "$namespace" = "${OPENSHIFT_LLM_TARGET_NAMESPACE:-}" ] || \
  emit_failure 'unexpected-model-namespace' 'The runtime target namespace does not match the chart-provided skill configuration.'
[ "$hf_secret" = "$configured_hf_secret" ] || \
  emit_failure 'unexpected-hf-token-secret' 'Use only the existing Secret name configured by Helm. The agent cannot substitute or inspect another Secret.'
[ "$configured_hf_secret" = "${OPENSHIFT_LLM_HF_SECRET_NAME:-}" ] && \
  [ "$configured_hf_secret_key" = "${OPENSHIFT_LLM_HF_SECRET_KEY:-}" ] && \
  [ "$model_runner_service_account" = "${OPENSHIFT_LLM_RUNNER_SERVICE_ACCOUNT:-}" ] || \
  emit_failure 'model-skill-runtime-config-mismatch' 'The mounted skill configuration does not match the chart-managed runtime environment.'

umask 077
workdir=$(mktemp -d "${TMPDIR:-/tmp}/hermes-model-deploy.XXXXXX") || exit 1
trap 'rm -rf "$workdir"' EXIT HUP INT TERM
dynamo_manifest="$workdir/dynamo.yaml"
fallback_manifest="$workdir/fallback.yaml"
download_manifest="$workdir/model-download.yaml"
launcher_log="$workdir/launcher.log"
dry_run_log="$workdir/dry-run.log"
download_job="${release}-model-download"
node_selector_block=$(printf '%s\n' \
  'nodeSelector:' \
  "        kubernetes.io/hostname: $node")
fallback_args=$(printf '%s\n' \
  '- --tensor-parallel-size' \
  "            - \"$gpus\"" \
  '            - --trust-remote-code' \
  '            - --max-model-len' \
  "            - \"$max_model_len\"")

printf '%s\n' \
  'DEPLOYMENT_PHASE=rendering-chart-managed-manifests' \
  "DEPLOYMENT_RELEASE=$release" \
  "DEPLOYMENT_NAMESPACE=$namespace" \
  "DEPLOYMENT_MODEL=$model" \
  "DEPLOYMENT_MODE=$deployment_mode" \
  "DEPLOYMENT_DYNAMO_BACKEND=$dynamo_backend"
printf '%s\n' "$dynamo_resolution"
printf '%s\n' "$vllm_resolution"

if [ "$deployment_mode" = dynamo ]; then
  dynamo_runtime_version_block=$(printf '      runtimeVersionOverride: "%s"' "$dynamo_runtime_version")
  case "$dynamo_backend" in
    vllm)
      if ! python3 "$renderer" --template "$dynamo_template" --output "$dynamo_manifest" \
        --set "NAMESPACE=$namespace" --set "RELEASE=$release" \
        --set "STORAGE_CLASS=$storage_class" --set "PVC_SIZE=$pvc_size" \
        --set "NODE_NAME=$node" --set "DYNAMO_VLLM_IMAGE=$dynamo_image" \
        --set "DYNAMO_RUNTIME_VERSION_BLOCK=$dynamo_runtime_version_block" \
        --set "SERVED_MODEL_NAME=$model" --set "MODEL_ID=$model" \
        --set "DYNAMO_IMAGE_PULL_SECRETS=$dynamo_image_pull_secrets" --set "GPU_COUNT=$gpus" \
        --set "MEMORY_REQUEST=$memory_request" --set "MEMORY_LIMIT=$memory_limit" \
        --set "DYNAMO_VLLM_EXTRA_ARGS=--max-model-len $max_model_len" >"$dry_run_log" 2>&1; then
        cat "$dry_run_log"
        emit_failure 'dynamo-manifest-render-failed' 'The chart wrapper could not render its stock Dynamo manifest. Do not retry with manual YAML.'
      fi
      ;;
    trtllm)
      if ! python3 "$renderer" --template "$dynamo_template" --output "$dynamo_manifest" \
        --set "NAMESPACE=$namespace" --set "RELEASE=$release" \
        --set "STORAGE_CLASS=$storage_class" --set "PVC_SIZE=$pvc_size" \
        --set "NODE_NAME=$node" --set "DYNAMO_TRTLLM_IMAGE=$dynamo_image" \
        --set "DYNAMO_RUNTIME_VERSION_BLOCK=$dynamo_runtime_version_block" \
        --set "SERVED_MODEL_NAME=$model" --set "MODEL_ID=$model" \
        --set "DYNAMO_IMAGE_PULL_SECRETS=$dynamo_image_pull_secrets" --set "GPU_COUNT=$gpus" \
        --set "MEMORY_REQUEST=$memory_request" --set "MEMORY_LIMIT=$memory_limit" \
        --set "TRTLLM_ENGINE_ARGS=$trtllm_engine_args" >"$dry_run_log" 2>&1; then
        cat "$dry_run_log"
        emit_failure 'dynamo-manifest-render-failed' 'The chart wrapper could not render its stock Dynamo manifest. Do not retry with manual YAML.'
      fi
      ;;
  esac
fi

if ! python3 "$renderer" --template "$skill_root/templates/vllm-deployment.yaml" --output "$fallback_manifest" \
  --set "NAMESPACE=$namespace" --set "RELEASE=$release" \
  --set "STORAGE_CLASS=$storage_class" --set "PVC_SIZE=$pvc_size" \
  --set "NODE_SELECTOR_BLOCK=$node_selector_block" --set "VLLM_IMAGE=$fallback_image" \
  --set "MODEL_ID=$model" --set "SERVED_MODEL_NAME=$model" \
  --set "MODEL_RUNNER_SERVICE_ACCOUNT=$model_runner_service_account" \
  --set "VLLM_ARGS=$fallback_args" \
  --set "GPU_COUNT=$gpus" --set "MEMORY_REQUEST=$memory_request" \
  --set "MEMORY_LIMIT=$memory_limit" \
  --set "SERVICE_TYPE=$( [ "$platform" = openshift ] && printf ClusterIP || printf NodePort )" >>"$dry_run_log" 2>&1; then
  cat "$dry_run_log"
  emit_failure 'fallback-manifest-render-failed' 'The chart wrapper could not render its stock vLLM fallback manifest. Do not retry with manual YAML.'
fi

download_image=$dynamo_image
download_image_pull_secrets=$dynamo_image_pull_secrets
if [ "$deployment_mode" = standard-vllm ]; then
  download_image=$fallback_image
  download_image_pull_secrets='[]'
fi
if ! python3 "$renderer" --template "$skill_root/templates/model-download-job.yaml" --output "$download_manifest" \
  --set "NAMESPACE=$namespace" --set "RELEASE=$release" \
  --set "STORAGE_CLASS=$storage_class" --set "PVC_SIZE=$pvc_size" \
  --set "NODE_NAME=$node" --set "DOWNLOAD_IMAGE=$download_image" \
  --set "DOWNLOAD_IMAGE_PULL_SECRETS=$download_image_pull_secrets" \
  --set "MODEL_ID=$model" --set "HF_SECRET_NAME=$hf_secret" \
  --set "HF_SECRET_KEY=$configured_hf_secret_key" \
  --set "MODEL_RUNNER_SERVICE_ACCOUNT=$model_runner_service_account" \
  --set "DOWNLOAD_TIMEOUT_SECONDS=$download_timeout" >>"$dry_run_log" 2>&1; then
  cat "$dry_run_log"
  emit_failure 'model-download-manifest-render-failed' 'The chart wrapper could not render the isolated model-download Job. Do not create an ad hoc download pod.'
fi

if ! oc -n "$namespace" apply --dry-run=client -f "$download_manifest" >"$dry_run_log" 2>&1 || \
  ! oc -n "$namespace" apply --dry-run=client -f "$fallback_manifest" >>"$dry_run_log" 2>&1 || \
  { [ "$deployment_mode" = standard-vllm ] || oc -n "$namespace" apply --dry-run=client -f "$dynamo_manifest" >>"$dry_run_log" 2>&1; }; then
  cat "$dry_run_log"
  emit_failure 'chart-managed-manifest-validation-failed' 'The stock manifests failed client validation. Inspect this one result; do not create another manifest.'
fi

emit_download_phase() {
  printf '%s\n' "DEPLOYMENT_PHASE=$1" "DEPLOYMENT_RELEASE=$release" "DEPLOYMENT_NAMESPACE=$namespace"
}

emit_download_phase 'applying-isolated-model-download'
download_apply_log="$workdir/model-download-apply.log"
if ! oc -n "$namespace" apply -f "$download_manifest" >"$download_apply_log" 2>&1; then
  cat "$download_apply_log"
  emit_failure 'model-download-apply-failed' 'The isolated model-download Job could not be created. Resolve the reported resource error before retrying.'
fi

emit_download_phase 'downloading-model-cache'
if oc -n "$namespace" wait --for=condition=complete "job/$download_job" --timeout="${download_observation_timeout}s" >"$workdir/model-download-wait.log" 2>&1; then
  printf '%s\n' 'MODEL_DOWNLOAD_RESULT=ready'
  printf '%s\n' 'HF_TOKEN_SECRET=external-reference-not-read-or-deleted'
  emit_download_phase 'model-cache-ready'
else
  download_failed=$(oc -n "$namespace" get "job/$download_job" -o jsonpath='{.status.failed}' 2>/dev/null || true)
  if [ -n "$download_failed" ] && [ "$download_failed" != 0 ]; then
    printf '%s\n' 'MODEL_DOWNLOAD_RESULT=failed'
    sh "$diagnose" --namespace "$namespace" --release "$release" --apply-log "$download_apply_log" || true
    emit_failure 'model-download-failed' 'The isolated download Job failed. Its bounded diagnosis is above; verify the external Secret reference only after resolving that cause.'
  fi
  printf '%s\n' \
    'MODEL_DOWNLOAD_RESULT=pending' \
    'HF_TOKEN_SECRET=external-reference-not-read-or-deleted' \
    "MODEL_DOWNLOAD_JOB=$download_job" \
    'DEPLOYMENT_ACTION=The model download is still running. Do not create another deployment. Check this Job later; its TTL removes only the completed Job.' \
    'DEPLOYMENT_RESULT=pending'
  exit 0
fi

set -- sh "$launcher" \
  --namespace "$namespace" --release "$release" \
  --fallback-manifest "$fallback_manifest" \
  --platform "$platform" --node "$node" \
  --deployment-mode "$deployment_mode" --fallback-image "$fallback_image" \
  --timeout "$observation_timeout" --verify-timeout "$verification_timeout" \
  --model "$model" \
  --enable-vllm-metrics
[ "$deployment_mode" = dynamo ] && set -- "$@" --dynamo-manifest "$dynamo_manifest" --dynamo-image "$dynamo_image"
[ "$allow_fallback" = true ] && set -- "$@" --allow-fallback
[ "$expose" = true ] && set -- "$@" --expose
if "$@" >"$launcher_log" 2>&1; then
  cat "$launcher_log"
  exit 0
else
  runner_status=$?
fi

cat "$launcher_log"
if ! grep -Eq '^DEPLOYMENT_RESULT=' "$launcher_log"; then
  printf '%s\n' \
    'DEPLOYMENT_RESULT=failed' \
    "DEPLOYMENT_REASON=launcher-exited-without-result-$runner_status" \
    'DEPLOYMENT_ACTION=Run the chart-provided diagnosis once, then report that result. Do not retry deployment or render another manifest.'
  sh "$diagnose" --namespace "$namespace" --release "$release" --apply-log "$launcher_log" || true
fi
exit 0
