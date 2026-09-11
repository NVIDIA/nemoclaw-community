#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Apply a DynamoGraphDeployment, surface a bounded diagnosis on failure, and
# fall back to standard vLLM only after a confirmed Dynamo incompatibility or
# runtime failure. A long model download remains a pending state, not a failure.
set -eu

# Hermes tool executions do not inherit the container's chart PATH.
export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

usage() {
  cat >&2 <<'EOF'
usage: dynamo-first-deploy.sh \
  --namespace NAME --release NAME --fallback-manifest FILE \
  --platform openshift|kubernetes --node NAME --fallback-image IMAGE \
  [--deployment-mode dynamo|standard-vllm] \
  [--dynamo-manifest FILE --dynamo-image IMAGE] \
  [--timeout SECONDS] [--verify-timeout SECONDS] [--model MODEL] \
  [--openshift-scc NAME] \
  [--allow-fallback] [--expose] [--enable-vllm-metrics]
EOF
  exit 64
}

namespace=
release=
dynamo_manifest=
fallback_manifest=
platform=
deployment_mode=dynamo
timeout_seconds=150
verify_timeout_seconds=300
served_model=
node_name=
dynamo_image=
fallback_image=
openshift_scc=anyuid
# The wrapper is called only after one user confirmation that covers the
# Dynamo attempt and automatic standard-vLLM recovery on explicit failure.
allow_fallback=true
expose=false
enable_vllm_metrics=true


while [ "$#" -gt 0 ]; do
  case "$1" in
    --namespace) namespace=${2:-}; shift 2 ;;
    --release) release=${2:-}; shift 2 ;;
    --dynamo-manifest) dynamo_manifest=${2:-}; shift 2 ;;
    --fallback-manifest) fallback_manifest=${2:-}; shift 2 ;;
    --platform) platform=${2:-}; shift 2 ;;
    --deployment-mode) deployment_mode=${2:-}; shift 2 ;;
    --timeout) timeout_seconds=${2:-}; shift 2 ;;
    --verify-timeout) verify_timeout_seconds=${2:-}; shift 2 ;;
    --model) served_model=${2:-}; shift 2 ;;
    --node) node_name=${2:-}; shift 2 ;;
    --dynamo-image) dynamo_image=${2:-}; shift 2 ;;
    --fallback-image) fallback_image=${2:-}; shift 2 ;;
    --openshift-scc) openshift_scc=${2:-}; shift 2 ;;
    --allow-fallback) allow_fallback=true; shift ;;
    --expose) expose=true; shift ;;
    --enable-vllm-metrics) enable_vllm_metrics=true; shift ;;
    --disable-vllm-metrics) enable_vllm_metrics=false; shift ;;
    *) usage ;;
  esac
done

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
failure_classifier="$script_dir/classify-dynamo-failure.py"

[ -n "$namespace" ] && [ -n "$release" ] && [ -n "$fallback_manifest" ] && \
  [ -n "$platform" ] && [ -n "$node_name" ] && [ -n "$fallback_image" ] || usage
[ -f "$fallback_manifest" ] || {
  printf '%s\n' 'DYNAMO_RESULT=invalid-manifest'
  exit 65
}
case "$platform" in openshift|kubernetes) ;; *) usage ;; esac
case "$deployment_mode" in dynamo|standard-vllm) ;; *) usage ;; esac
if [ "$deployment_mode" = dynamo ]; then
  [ -n "$dynamo_manifest" ] && [ -n "$dynamo_image" ] && [ -f "$dynamo_manifest" ] || usage
  [ -r "$failure_classifier" ] || usage
fi
case "$timeout_seconds" in ''|*[!0-9]*) usage ;; esac
case "$verify_timeout_seconds" in ''|*[!0-9]*) usage ;; esac

diagnose_script="$script_dir/diagnose-deployment.sh"
verify_script="$script_dir/verify-openai-endpoint.sh"
workdir=$(mktemp -d "${TMPDIR:-/tmp}/hermes-dynamo-deploy.XXXXXX") || exit 1
trap 'rm -rf "$workdir"' EXIT HUP INT TERM
deadline=$(( $(date +%s) + timeout_seconds ))
label="app.kubernetes.io/instance=$release"
dynamo_service_account="${release}-k8s-service-discovery"
model_runner_service_account=${OPENSHIFT_LLM_RUNNER_SERVICE_ACCOUNT:-}

emit_phase() {
  printf '%s\n' "DEPLOYMENT_PHASE=$1" "DEPLOYMENT_RELEASE=$release" "DEPLOYMENT_NAMESPACE=$namespace"
}

emit_result() {
  printf '%s\n' "DEPLOYMENT_RESULT=$1"
}

observe_release() {
  observation_phase=$1
  pods=$(oc -n "$namespace" get pods -l "$label" \
    -o jsonpath='{range .items[*]}{.metadata.name}{":"}{.status.phase}{":"}{range .status.containerStatuses[*]}{.state.waiting.reason}{","}{end}{";"}{end}' \
    2>/dev/null || true)
  dgd=$(oc -n "$namespace" get dynamographdeployments.nvidia.com "$release" \
    -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{":"}{.reason}{","}{end}' \
    2>/dev/null || true)
  printf '%s\n' "DEPLOYMENT_OBSERVATION=phase=${observation_phase};dgd=${dgd:-not-found};pods=${pods:-not-created-yet}"
}

invalid_manifest() {
  backend=$1
  reason=$2
  action=$3
  printf '%s\n' \
    "${backend}_RESULT=failed" \
    "${backend}_REASON=invalid-manifest-${reason}" \
    "${backend}_ACTION=${action}"
}

validate_rendered_manifest() {
  backend=$1
  manifest=$2
  expected_image=$3

  if ! grep -Fq "kubernetes.io/hostname: $node_name" "$manifest"; then
    invalid_manifest "$backend" 'missing-node-placement' 'Re-render the chart template with the selected node; do not apply or patch a manifest without explicit placement.'
    return 1
  fi
  if ! grep -Fq "image: $expected_image" "$manifest"; then
    invalid_manifest "$backend" 'unexpected-runtime-image' 'Use the chart-selected runtime image; do not substitute an image manually.'
    return 1
  fi
  if grep -Eqi 'pipefail|set[[:space:]]+-[^[:space:]]*o[[:space:]]+pipefail' "$manifest"; then
    invalid_manifest "$backend" 'unsupported-pipefail-shell-wrapper' 'Use the stock template arguments only. Do not add shell wrappers or pipefail to a vLLM manifest.'
    return 1
  fi
  if grep -Fq 'name: HF_TOKEN' "$manifest" || grep -Fq 'secretKeyRef:' "$manifest"; then
    invalid_manifest "$backend" 'serving-manifest-references-credential' 'The model server must use the local PVC cache only. Re-render the stock template without an HF token or Secret reference.'
    return 1
  fi
  if [ "$backend" = FALLBACK ] && ! grep -Fq -- '- /models/model' "$manifest"; then
    invalid_manifest "$backend" 'fallback-not-using-local-model-cache' 'The standard vLLM fallback must use /models/model after the isolated downloader populates the cache.'
    return 1
  fi
  if [ "$backend" = DYNAMO ] && ! grep -Fq -- '--model "/models/model"' "$manifest" && ! grep -Fq -- '--model-path "/models/model"' "$manifest"; then
    invalid_manifest "$backend" 'dynamo-not-using-local-model-cache' 'The Dynamo worker must use /models/model after the isolated downloader populates the cache.'
    return 1
  fi
  if [ "$backend" = FALLBACK ] && grep -Eq '^[[:space:]]*command:' "$manifest"; then
    invalid_manifest "$backend" 'fallback-command-override' 'Use the stock fallback template without command overrides; VLLM_ARGS may contain only vLLM argument list entries.'
    return 1
  fi
  if [ "$backend" = FALLBACK ] && { [ -z "$model_runner_service_account" ] || ! grep -Fq "serviceAccountName: $model_runner_service_account" "$manifest"; }; then
    invalid_manifest "$backend" 'unexpected-service-account' 'Use only the model-runner ServiceAccount configured by Helm for the standard vLLM fallback.'
    return 1
  fi
  if [ "$backend" = DYNAMO ] && sed -n '/command: \["python3", "-m", "dynamo.frontend"\]/,/^    - name: /p' "$manifest" | grep -Fq -- '--model-path'; then
    invalid_manifest "$backend" 'frontend-model-path-is-repository-id' 'The Dynamo frontend must not receive a Hugging Face repository ID as --model-path. Use the stock template: the worker downloads the model and the frontend receives only the served model name.'
    return 1
  fi
  return 0
}

report_dynamo_scc_prerequisite() {
  [ "$platform" = openshift ] || return 0
  [ -n "$openshift_scc" ] || return 0

  emit_phase 'reporting-dynamo-service-account-scc-prerequisite'
  printf '%s\n' \
    "DYNAMO_SCC_SERVICEACCOUNT=$dynamo_service_account" \
    'DYNAMO_SCC_GRANT=human-managed' \
    "DYNAMO_SCC_ACTION=If OpenShift admission rejects the Dynamo workload, a human administrator may run: oc adm policy add-scc-to-user $openshift_scc -z $dynamo_service_account -n $namespace" \
    'DYNAMO_SCC_NOTE=Hermes and this Helm chart never grant SCC or cluster-admin privileges automatically.'
}

print_apply_log() {
  log_file=$1
  [ -f "$log_file" ] || return 0
  printf '%s\n' "--- $(basename "$log_file") ---"
  tail -n 80 "$log_file"
}

diagnose() {
  log_file=$1
  if [ -r "$diagnose_script" ]; then
    sh "$diagnose_script" --namespace "$namespace" --release "$release" --apply-log "$log_file" || true
  else
    printf '%s\n' 'DIAGNOSIS_RESULT=unavailable' 'DIAGNOSIS_ACTION=Inspect the apply output and release-matching pods manually.'
    print_apply_log "$log_file"
  fi
}

transient_api_error() {
  grep -Eqi 'Unable to connect to the server|TLS handshake timeout|i/o timeout|connection reset|the server is currently unable' "$1"
}

dynamo_crd_unavailable() {
  grep -Eqi 'no matches for kind .*DynamoGraphDeployment|the server could not find the requested resource|requested resource not found' "$1"
}

apply_with_single_retry() {
  manifest=$1
  log_file=$2
  : >"$log_file"
  if oc -n "$namespace" apply -f "$manifest" >"$log_file" 2>&1; then
    return 0
  fi
  if transient_api_error "$log_file"; then
    printf '%s\n' 'DEPLOYMENT_RETRY=one-safe-api-retry-after-transient-apply-error'
    sleep 5
    if oc -n "$namespace" apply -f "$manifest" >>"$log_file" 2>&1; then
      printf '%s\n' 'DEPLOYMENT_RETRY_RESULT=success'
      return 0
    fi
  fi
  return 1
}

find_frontend_service() {
  service=$(oc -n "$namespace" get service "$release" -o name 2>/dev/null || true)
  if [ -n "$service" ]; then
    printf '%s\n' "$release"
    return 0
  fi
  oc -n "$namespace" get service --no-headers 2>/dev/null |
    awk -v target="$release" 'index($1, target) == 1 && tolower($1) ~ /frontend/ {print $1; exit}'
}

dynamo_is_ready() {
  conditions=$(oc -n "$namespace" get dynamographdeployments.nvidia.com "$release" \
    -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{"\n"}{end}' 2>/dev/null || true)
  printf '%s\n' "$conditions" | grep -Fxq 'Ready=True'
}

explicit_failure() {
  dgd_conditions=$(oc -n "$namespace" get dynamographdeployments.nvidia.com "$release" \
    -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{":"}{.reason}{";"}{end}' 2>/dev/null || true)
  case "$dgd_conditions" in
    *Failed=True*|*Error=True*|*Failure=True*)
      printf '%s\n' "dgd-condition:$dgd_conditions"
      return 0
      ;;
  esac

  pod_state=$(oc -n "$namespace" get pods \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\t"}{range .status.containerStatuses[*]}{.state.waiting.reason}{","}{end}{"\n"}{end}' 2>/dev/null || true)
  if printf '%s\n' "$pod_state" | awk -v target="$release" '
      index($1, target) == 1 && ($2 == "Failed" || $3 ~ /(ImagePullBackOff|ErrImagePull|CrashLoopBackOff|CreateContainerConfigError|RunContainerError)/) {
        print $0; found = 1
      }
      END { exit found ? 0 : 1 }
    ' >"$workdir/explicit-failure.txt"; then
    reason=$(tr '\n' ';' <"$workdir/explicit-failure.txt")
    printf '%s\n' "pod-state:$reason"
    return 0
  fi
  return 1
}

dynamo_failure_decision() {
  dgd_conditions=$(oc -n "$namespace" get dynamographdeployments.nvidia.com "$release" \
    -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{":"}{.reason}{";"}{end}' 2>/dev/null || true)
  pod_state_file="$workdir/dynamo-pod-state.txt"
  runtime_log_file="$workdir/dynamo-runtime.log"
  pod_names_file="$workdir/dynamo-pod-names.txt"
  oc -n "$namespace" get pods -l "$label" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\t"}{range .status.containerStatuses[*]}{.state.waiting.reason}{","}{end}{"\n"}{end}' \
    >"$pod_state_file" 2>/dev/null || : >"$pod_state_file"
  : >"$runtime_log_file"

  # Runtime logs are consulted only after Kubernetes or the DGD reports a
  # terminal-looking state. They are never printed by the classifier.
  if grep -Eq 'Failed|ImagePullBackOff|ErrImagePull|InvalidImageName|CreateContainer|RunContainerError|ContainerCannotRun|CrashLoopBackOff' \
    "$pod_state_file" 2>/dev/null || \
    printf '%s\n' "$dgd_conditions" | grep -Eq '(Failed|Error|Failure)=True:'; then
    oc -n "$namespace" get pods -l "$label" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
      >"$pod_names_file" 2>/dev/null || : >"$pod_names_file"
    while IFS= read -r pod; do
      case "$pod" in
        "$release"*)
          if ! oc -n "$namespace" logs "$pod" --all-containers --tail=80 --previous \
            >>"$runtime_log_file" 2>/dev/null; then
            oc -n "$namespace" logs "$pod" --all-containers --tail=80 \
              >>"$runtime_log_file" 2>/dev/null || true
          fi
          ;;
      esac
    done <"$pod_names_file"
  fi

  python3 "$failure_classifier" \
    --dgd-conditions "$dgd_conditions" \
    --pod-state-file "$pod_state_file" \
    --runtime-log-file "$runtime_log_file"
}

report_dynamo_terminal_failure() {
  reason=$1
  diagnose "$dynamo_apply_log"
  printf '%s\n' \
    'DYNAMO_RESULT=failed' \
    "DYNAMO_REASON=$reason" \
    'DYNAMO_FALLBACK=not-safe-for-this-failure-class' \
    'DYNAMO_NEXT_ACTION=resolve-the-reported-registry-rbac-storage-scheduling-or-runtime-cause-before-changing-backends'
  emit_result failed
}

publish_endpoint() {
  service=$1
  if [ "$expose" != true ]; then
    printf '%s\n' "SERVICE_ENDPOINT=http://$service.$namespace.svc.cluster.local:8000"
    return 0
  fi

  if [ "$platform" = openshift ]; then
    service_port=$(oc -n "$namespace" get service "$service" -o jsonpath='{.spec.ports[0].name}' 2>/dev/null || true)
    if [ -n "$service_port" ]; then
      oc -n "$namespace" create route edge "$release" --service="$service" --port="$service_port" \
        --dry-run=client -o yaml | oc -n "$namespace" apply -f - >/dev/null
    else
      oc -n "$namespace" create route edge "$release" --service="$service" \
        --dry-run=client -o yaml | oc -n "$namespace" apply -f - >/dev/null
    fi
    oc -n "$namespace" label route "$release" \
      "app.kubernetes.io/instance=$release" \
      'app.kubernetes.io/managed-by=hermes' \
      'app.kubernetes.io/component=inference' --overwrite >/dev/null
    host=$(oc -n "$namespace" get route "$release" -o jsonpath='{.spec.host}')
    [ -n "$host" ] || return 1
    printf '%s\n' "ENDPOINT=https://$host"
    return 0
  fi

  oc -n "$namespace" patch service "$service" --type merge \
    -p '{"spec":{"type":"NodePort"}}' >/dev/null
  node_port=$(oc -n "$namespace" get service "$service" -o jsonpath='{.spec.ports[0].nodePort}')
  node_address=$(oc get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
  [ -n "$node_port" ] && [ -n "$node_address" ] || return 1
  printf '%s\n' "ENDPOINT=http://$node_address:$node_port"
}

verify_and_report() {
  backend=$1
  service=$2
  if [ ! -r "$verify_script" ]; then
    printf '%s\n' 'VERIFY_RESULT=failed' 'VERIFY_ACTION=The bundled endpoint verifier is missing or unreadable.'
    return 2
  fi
  if [ -n "$served_model" ]; then
    sh "$verify_script" --namespace "$namespace" --service "$service" \
      --model "$served_model" --timeout "$verify_timeout_seconds"
  else
    sh "$verify_script" --namespace "$namespace" --service "$service" \
      --timeout "$verify_timeout_seconds"
  fi
}

verify_and_report_with_endpoint() {
  backend=$1
  backend_label=$2
  service=$3
  emit_phase "verifying-${backend}-endpoint"
  if verify_and_report "$backend" "$service"; then
    if publish_endpoint "$service"; then
      printf '%s\n' 'ENDPOINT_RESULT=ready'
    else
      printf '%s\n' \
        'ENDPOINT_RESULT=failed' \
        'ENDPOINT_ACTION=backend-is-verified-but-exposure-creation-failed; inspect-the-Route-or-NodePort-resource-before-retrying-exposure'
    fi
    printf '%s\n' "DEPLOYMENT_BACKEND=$backend_label" "${backend}_RESULT=ready" "MODEL_RELEASE=$release"
    emit_result ready
    return 0
  else
    verify_status=$?
  fi
  if [ "$verify_status" -eq 1 ]; then
  printf '%s\n' "DEPLOYMENT_BACKEND=$backend_label" "${backend}_RESULT=pending" \
      "${backend}_NEXT_ACTION=endpoint-not-ready-after-verification-window; rerun status without creating a second deployment"
    emit_result pending
    return 1
  fi
  printf '%s\n' "DEPLOYMENT_BACKEND=$backend_label" "${backend}_RESULT=failed" \
    "${backend}_REASON=endpoint-verification-failed"
  emit_result failed
  return 2
}
apply_vllm_podmonitor() {
  if [ "$enable_vllm_metrics" != true ]; then
    return 0
  fi
  script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
  skill_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
  renderer="$script_dir/render-template.py"
  podmonitor_manifest="$workdir/vllm-podmonitor.yaml"
  if ! python3 "$renderer" --template "$skill_root/templates/vllm-podmonitor.yaml" --output "$podmonitor_manifest" --set NAMESPACE="$namespace"; then
    printf '%s\n' 'VLLM_PODMONITOR_RESULT=render-failed' >&2
    return 1
  fi
  if oc -n "$namespace" apply -f "$podmonitor_manifest" >/dev/null 2>&1; then
    printf '%s\n' 'VLLM_PODMONITOR_RESULT=applied'
  else
    printf '%s\n' 'VLLM_PODMONITOR_RESULT=apply-failed' >&2
    return 1
  fi
}

run_fallback() {
  reason=$1
  emit_phase 'dynamo-failed-evaluating-fallback'
  printf '%s\n' 'DYNAMO_RESULT=failed' "DYNAMO_REASON=$reason"
  if [ "$allow_fallback" != true ]; then
    printf '%s\n' 'DYNAMO_FALLBACK=not-approved' 'DYNAMO_NEXT_ACTION=obtain-explicit-fallback-approval-before-changing-the-backend'
    emit_result failed
    return 0
  fi

  emit_phase 'removing-failed-dynamo-graph'
  printf '%s\n' 'DYNAMO_FALLBACK=starting-standard-vllm'
  if oc -n "$namespace" get dynamographdeployments.nvidia.com "$release" >/dev/null 2>&1; then
    if [ -z "${MODEL_DELETE_KUBECONFIG:-}" ] || \
      ! oc --kubeconfig "$MODEL_DELETE_KUBECONFIG" -n "$namespace" delete \
        dynamographdeployments.nvidia.com "$release" --wait=false >/dev/null 2>&1; then
      printf '%s\n' \
        'DYNAMO_FALLBACK=blocked-by-delete-policy' \
        'DYNAMO_NEXT_ACTION=Enable the namespace-scoped exact-resource model deletion option for this DynamoGraphDeployment, or have a human remove it before approving fallback.'
      emit_result failed
      return 0
    fi
  fi
  sleep 5
  fallback_log="$workdir/fallback-apply.log"
  emit_phase 'applying-standard-vllm-fallback'
  if ! apply_with_single_retry "$fallback_manifest" "$fallback_log"; then
    printf '%s\n' 'FALLBACK_RESULT=failed' 'FALLBACK_REASON=standard-vllm-apply-failed'
    diagnose "$fallback_log"
    emit_result failed
    return 0
  fi

  emit_phase 'waiting-for-standard-vllm-fallback'
  observe_release 'fallback-applied'
  if oc -n "$namespace" rollout status "deployment/$release" --timeout="${timeout_seconds}s"; then
    if verify_and_report_with_endpoint FALLBACK standard-vllm-fallback "$release"; then
      apply_vllm_podmonitor
      return 0
    else
      fallback_verify_status=$?
    fi
    if [ "$fallback_verify_status" -eq 2 ]; then
      diagnose "$fallback_log"
    fi
    return 0
  fi

  if explicit_failure; then
    printf '%s\n' 'FALLBACK_RESULT=failed' 'FALLBACK_REASON=standard-vllm-runtime-failure'
    diagnose "$fallback_log"
    emit_result failed
  else
    printf '%s\n' 'FALLBACK_RESULT=pending' \
      'FALLBACK_NEXT_ACTION=model-is-still-downloading-or-initializing; rerun status later without redeploying'
    observe_release 'fallback-observation-timeout'
    emit_result pending
  fi
}

run_standard_vllm() {
  direct_log="$workdir/standard-vllm-apply.log"
  emit_phase 'applying-standard-vllm'
  if ! apply_with_single_retry "$fallback_manifest" "$direct_log"; then
    printf '%s\n' 'STANDARD_VLLM_RESULT=failed' 'STANDARD_VLLM_REASON=standard-vllm-apply-failed'
    diagnose "$direct_log"
    emit_result failed
    return 0
  fi

  emit_phase 'waiting-for-standard-vllm'
  observe_release 'standard-vllm-applied'
  if oc -n "$namespace" rollout status "deployment/$release" --timeout="${timeout_seconds}s"; then
    if verify_and_report_with_endpoint STANDARD_VLLM standard-vllm "$release"; then
      apply_vllm_podmonitor
      return 0
    else
      direct_verify_status=$?
    fi
    if [ "$direct_verify_status" -eq 2 ]; then
      diagnose "$direct_log"
    fi
    return 0
  fi

  if explicit_failure; then
    printf '%s\n' 'STANDARD_VLLM_RESULT=failed' 'STANDARD_VLLM_REASON=standard-vllm-runtime-failure'
    diagnose "$direct_log"
    emit_result failed
  else
    printf '%s\n' 'STANDARD_VLLM_RESULT=pending' \
      'STANDARD_VLLM_NEXT_ACTION=model-is-still-downloading-or-initializing; rerun-status-later-without-redeploying'
    observe_release 'standard-vllm-observation-timeout'
    emit_result pending
  fi
}

emit_phase 'validating-rendered-manifests'
if ! validate_rendered_manifest FALLBACK "$fallback_manifest" "$fallback_image"; then
  emit_result failed
  exit 0
fi
if [ "$deployment_mode" = standard-vllm ]; then
  run_standard_vllm
  exit 0
fi
if ! validate_rendered_manifest DYNAMO "$dynamo_manifest" "$dynamo_image"; then
  emit_result failed
  exit 0
fi
report_dynamo_scc_prerequisite

dynamo_apply_log="$workdir/dynamo-apply.log"
emit_phase 'applying-dynamo-graph'
if ! apply_with_single_retry "$dynamo_manifest" "$dynamo_apply_log"; then
  if dynamo_crd_unavailable "$dynamo_apply_log"; then
    diagnose "$dynamo_apply_log"
    run_fallback 'dynamo-crd-unavailable'
  else
    printf '%s\n' 'DYNAMO_RESULT=failed' 'DYNAMO_REASON=dgd-apply-failed'
    diagnose "$dynamo_apply_log"
    printf '%s\n' 'DYNAMO_NEXT_ACTION=resolve-the-diagnosis-before-another-deployment-attempt'
    emit_result failed
  fi
  exit 0
fi

emit_phase 'waiting-for-dynamo-graph'
last_observation=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  now=$(date +%s)
  if [ $((now - last_observation)) -ge 30 ]; then
    observe_release 'dynamo-waiting'
    last_observation=$now
  fi
  failure_decision=$(dynamo_failure_decision)
  failure_class=$(printf '%s\n' "$failure_decision" | awk -F= '$1 == "DYNAMO_FAILURE_CLASS" {print $2; exit}')
  failure_reason=$(printf '%s\n' "$failure_decision" | awk -F= '$1 == "DYNAMO_FAILURE_REASON" {print $2; exit}')
  case "$failure_class" in
    fallback)
      diagnose "$dynamo_apply_log"
      run_fallback "$failure_reason"
      exit 0
      ;;
    terminal)
      report_dynamo_terminal_failure "$failure_reason"
      exit 0
      ;;
  esac
  if dynamo_is_ready; then
    frontend_service=$(find_frontend_service || true)
  else
    frontend_service=
  fi
  if [ -n "$frontend_service" ]; then
    if verify_and_report_with_endpoint DYNAMO "$frontend_service"; then
      exit 0
    else
      verify_status=$?
    fi
    if [ "$verify_status" -eq 1 ]; then
      exit 0
    fi
    diagnose "$dynamo_apply_log"
    printf '%s\n' \
      'DYNAMO_RESULT=failed' \
      'DYNAMO_REASON=dynamo-endpoint-verification-failed' \
      'DYNAMO_FALLBACK=not-safe-for-endpoint-or-transport-failure' \
      'DYNAMO_NEXT_ACTION=inspect-the-Dynamo-service-and-verifier-result-before-changing-the-serving-backend'
    emit_result failed
    exit 0
  fi
  sleep 5
done

failure_decision=$(dynamo_failure_decision)
failure_class=$(printf '%s\n' "$failure_decision" | awk -F= '$1 == "DYNAMO_FAILURE_CLASS" {print $2; exit}')
failure_reason=$(printf '%s\n' "$failure_decision" | awk -F= '$1 == "DYNAMO_FAILURE_REASON" {print $2; exit}')
case "$failure_class" in
  fallback)
    diagnose "$dynamo_apply_log"
    run_fallback "$failure_reason"
    exit 0
    ;;
  terminal)
    report_dynamo_terminal_failure "$failure_reason"
    exit 0
    ;;
esac

frontend_service=$(find_frontend_service || true)
printf '%s\n' \
  'DEPLOYMENT_BACKEND=dynamo' \
  'DYNAMO_RESULT=pending' \
  "DYNAMO_FRONTEND_SERVICE=${frontend_service:-not-created-yet}" \
  'DYNAMO_NEXT_ACTION=the-model-is-still-downloading-or-initializing; rerun cluster status later without creating a second deployment'
observe_release 'dynamo-observation-timeout'
emit_result pending
