#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Query OpenShift Thanos through the chart's exact-target HTTPS proxy.
set -eu

export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

usage() {
  echo "usage: query-metrics.sh --query PROMQL [--namespace NAME] [--service NAME] [--port PORT]" >&2
  exit 64
}

query=
configured_namespace=${MONITORING_NAMESPACE:-openshift-monitoring}
configured_service=${MONITORING_SERVICE:-thanos-querier}
configured_port=${MONITORING_SERVICE_PORT:-9091}
monitoring_namespace=$configured_namespace
service=$configured_service
port=$configured_port
while [ "$#" -gt 0 ]; do
  case "$1" in
    --query) query=${2:-}; shift 2 ;;
    --namespace) monitoring_namespace=${2:-}; shift 2 ;;
    --service) service=${2:-}; shift 2 ;;
    --port) port=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done

[ -n "$query" ] || usage
[ "${MONITORING_ENABLED:-false}" = true ] && [ -r "${METRICS_KUBECONFIG:-}" ] || {
  echo "query-metrics: the chart's exact-target metrics proxy is disabled" >&2
  exit 77
}
[ "$monitoring_namespace" = "$configured_namespace" ] && \
  [ "$service" = "$configured_service" ] && [ "$port" = "$configured_port" ] || {
  echo "query-metrics: target overrides are outside the chart allowlist" >&2
  exit 77
}
[ "${#query}" -le 16384 ] || {
  echo "query-metrics: PromQL exceeds 16384 bytes" >&2
  exit 64
}
case "$monitoring_namespace/$service/$port" in
  *[!A-Za-z0-9._/-]*) echo "query-metrics: invalid service target" >&2; exit 64 ;;
esac

encoded=$(python3 - "$query" <<'PY'
import sys
from urllib.parse import quote

print(quote(sys.argv[1], safe=""))
PY
)
# The kubeconfig already targets the chart's exact-service metrics proxy. That
# proxy owns the fixed upstream Service identity and accepts only these direct
# Prometheus API paths; never let a caller supply a Kubernetes Service path.
path="/api/v1/query?query=$encoded"
if ! oc --kubeconfig "$METRICS_KUBECONFIG" get --raw "$path"; then
  cat >&2 <<'EOF'
query-metrics: monitoring query failed. On OpenShift, verify that the SRE
metrics ServiceAccount has cluster-monitoring-view and the injected service CA.
On Kubernetes, configure a compatible Prometheus API service.
EOF
  exit 75
fi
