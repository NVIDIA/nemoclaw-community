#!/bin/sh
set -eu

# Hermes tool executions do not inherit the container's chart PATH.
export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

printf '%-38s %-12s %-12s %-12s\n' NODE GPU_CAPACITY GPU_ALLOCATABLE GPU_FREE
oc get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.capacity.nvidia\.com/gpu}{"\t"}{.status.allocatable.nvidia\.com/gpu}{"\n"}{end}' |
while IFS='\t' read -r node capacity allocatable; do
  [ -n "$node" ] || continue
  capacity=${capacity:-0}
  allocatable=${allocatable:-0}
  requested=$(oc get pods -A -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.resources.requests.nvidia\.com/gpu}{"\n"}{end}{end}' 2>/dev/null | awk '{sum += $1} END {print sum + 0}')
  # Kubernetes does not report per-node requested GPUs in a portable API. The
  # table still exposes the hard capacity; inspect pods scheduled to a chosen
  # node before committing a workload there.
  printf '%-38s %-12s %-12s %-12s\n' "$node" "$capacity" "$allocatable" "inspect-pods"
done

printf '\nGPU pods by node:\n'
oc get pods -A -o custom-columns='NAMESPACE:.metadata.namespace,POD:.metadata.name,NODE:.spec.nodeName,GPU:.spec.containers[*].resources.requests.nvidia\.com/gpu' --no-headers
