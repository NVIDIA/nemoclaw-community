#!/bin/sh
# Inventory through the general no-delete proxy. Destructive calls use only the
# separate namespace-scoped proxy and exact operator-approved resource names.
set -eu

export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

usage() {
  cat >&2 <<'EOF'
usage: remove-model.sh --namespace NAME --release NAME --platform openshift|kubernetes \
  [--action inventory|delete] [--purge-storage] [--confirm]
EOF
  exit 64
}

namespace=
release=
platform=
action=inventory
purge_storage=false
confirmed=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --namespace) namespace=${2:-}; shift 2 ;;
    --release) release=${2:-}; shift 2 ;;
    --platform) platform=${2:-}; shift 2 ;;
    --action) action=${2:-}; shift 2 ;;
    --purge-storage) purge_storage=true; shift ;;
    --confirm) confirmed=true; shift ;;
    *) usage ;;
  esac
done

[ -n "$namespace" ] && [ -n "$release" ] && [ -n "$platform" ] || usage
case "$platform" in openshift|kubernetes) ;; *) usage ;; esac
case "$action" in inventory|delete) ;; *) usage ;; esac
case "$namespace" in *[!a-z0-9-]*|-*|*-) usage ;; esac
case "$release" in *[!a-z0-9-]*|-*|*-) usage ;; esac

label="app.kubernetes.io/instance=$release"

inventory() {
  printf '%s\n' \
    'REMOVE_INVENTORY=begin' \
    "REMOVE_NAMESPACE=$namespace" \
    "REMOVE_RELEASE=$release" \
    "REMOVE_STORAGE_ACTION=$( [ "$purge_storage" = true ] && printf purge-requested || printf retain )"
  oc -n "$namespace" get dynamographdeployments.nvidia.com "$release" --ignore-not-found -o wide 2>&1 || true
  oc -n "$namespace" get deployment,statefulset,job,service,pvc -l "$label" -o wide 2>&1 || true
  oc -n "$namespace" get horizontalpodautoscalers,routes,podmonitors -l "$label" -o wide 2>&1 || true
  printf '%s\n' 'REMOVE_INVENTORY=end'
}

inventory

if [ "$action" = inventory ]; then
  printf '%s\n' 'REMOVE_RESULT=inventory-only'
  exit 0
fi

if [ "$confirmed" != true ]; then
  printf '%s\n' 'REMOVE_RESULT=confirmation-required'
  exit 64
fi

configured_namespace=${OPENSHIFT_LLM_DELETE_NAMESPACE:-}
delete_kubeconfig=${MODEL_DELETE_KUBECONFIG:-}
allowed_json=${OPENSHIFT_LLM_DELETE_ALLOWED_RESOURCES:-}
if [ -z "$configured_namespace" ] || [ "$namespace" != "$configured_namespace" ] || \
  [ -z "$delete_kubeconfig" ] || [ ! -r "$delete_kubeconfig" ] || [ -z "$allowed_json" ]; then
  printf '%s\n' \
    'REMOVE_RESULT=delete-not-authorized' \
    'REMOVE_ACTION=Enable the chart model-deletion option for this exact namespace and exact resources, then restart the Hermes Sandbox.'
  exit 77
fi

workdir=$(mktemp -d "${TMPDIR:-/tmp}/hermes-model-remove.XXXXXX") || exit 1
trap 'rm -rf "$workdir"' EXIT HUP INT TERM
allowlist="$workdir/allowlist.tsv"
if ! printf '%s' "$allowed_json" | python3 -c '
import json
import re
import sys

entries = json.load(sys.stdin)
if not isinstance(entries, list) or not entries:
    raise SystemExit(1)
for entry in entries:
    if not isinstance(entry, dict) or set(entry) != {"apiGroup", "resource", "name"}:
        raise SystemExit(1)
    group, resource, name = (entry["apiGroup"], entry["resource"], entry["name"])
    if not all(isinstance(value, str) for value in (group, resource, name)):
        raise SystemExit(1)
    if not resource or not name or not re.fullmatch(r"[A-Za-z0-9.-]+", group or "core"):
        raise SystemExit(1)
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9.]*[a-z0-9])?", resource):
        raise SystemExit(1)
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9.]*[a-z0-9])?", name):
        raise SystemExit(1)
    print(f"{group}\t{resource}\t{name}")
' >"$allowlist"; then
  printf '%s\n' 'REMOVE_RESULT=invalid-delete-allowlist'
  exit 65
fi

deleted=0
skipped_storage=0
while IFS="$(printf '\t')" read -r api_group resource name; do
  case "$name" in
    "$release"|"$release"-*) ;;
    *)
      printf '%s\n' \
        'REMOVE_RESULT=delete-allowlist-ownership-mismatch' \
        "REMOVE_RESOURCE=$api_group/$resource/$name"
      exit 65
      ;;
  esac
  if [ "$resource" = secrets ]; then
    printf '%s\n' 'REMOVE_RESULT=secret-delete-forbidden'
    exit 65
  fi
  if [ "$resource" = persistentvolumeclaims ] && [ "$purge_storage" != true ]; then
    skipped_storage=$((skipped_storage + 1))
    continue
  fi
  resource_type=$resource
  [ -z "$api_group" ] || resource_type="$resource.$api_group"
  if ! oc --kubeconfig "$delete_kubeconfig" -n "$namespace" delete \
    "$resource_type" "$name" --ignore-not-found=true --wait=false; then
    printf '%s\n' \
      'REMOVE_RESULT=exact-delete-failed' \
      "REMOVE_RESOURCE=$api_group/$resource/$name"
    exit 1
  fi
  deleted=$((deleted + 1))
done <"$allowlist"

printf '%s\n' \
  'REMOVE_RESULT=exact-resource-removal-started' \
  "REMOVE_EXACT_RESOURCES=$deleted" \
  "REMOVE_STORAGE=$( [ "$skipped_storage" -gt 0 ] && printf retained || printf per-allowlist )" \
  'REMOVE_HF_TOKEN_SECRET=external-reference-not-read-or-deleted'
