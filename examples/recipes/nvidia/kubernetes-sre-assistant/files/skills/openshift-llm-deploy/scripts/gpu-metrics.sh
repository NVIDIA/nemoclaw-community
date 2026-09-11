#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Consolidated live GPU telemetry per pod, from the cluster's built-in
# monitoring stack.
#
# This reports measured utilization, which is different from the scheduled GPU
# *requests* shown by cluster-status.sh. A pod can hold 8 GPUs while using none
# of them; only this view can tell the difference.
set -eu

# Hermes tool executions do not inherit the container's chart PATH.
export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

usage() {
  cat >&2 <<'EOF'
usage: gpu-metrics.sh (--namespace NAME | --all-namespaces) [--pod-prefix PREFIX]
EOF
  exit 64
}

namespace=
all_namespaces=
pod_prefix=

while [ "$#" -gt 0 ]; do
  case "$1" in
    --namespace) namespace=${2:-}; shift 2 ;;
    --all-namespaces) all_namespaces=1; shift ;;
    --pod-prefix) pod_prefix=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done

if [ -n "$namespace" ] && [ -n "$all_namespaces" ]; then
  usage
fi
if [ -z "$namespace" ] && [ -z "$all_namespaces" ]; then
  usage
fi

skill_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
query_metrics="$skill_root/scripts/query-metrics.sh"

# DCGM attributes GPU consumers with the exported_* labels. The plain
# namespace/pod labels identify the DCGM exporter itself, so filtering on them
# silently returns nothing.
if [ -n "$all_namespaces" ]; then
  selector='exported_namespace!=""'
else
  selector="exported_namespace=\"$namespace\""
fi

dcgm_names='DCGM_FI_DEV_GPU_UTIL|DCGM_FI_DEV_FB_USED|DCGM_FI_DEV_FB_FREE|DCGM_FI_DEV_POWER_USAGE|DCGM_FI_DEV_GPU_TEMP|DCGM_FI_DEV_MEM_COPY_UTIL'

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT INT TERM

if ! "$query_metrics" --query "{__name__=~\"$dcgm_names\",$selector}" >"$workdir/gpu.json"; then
  echo 'gpu-metrics: GPU telemetry query failed (see the error above)' >&2
  exit 75
fi

# Serving-side metrics are exposed by Dynamo on the worker system port and the
# frontend http port, and by standard vLLM on the http port. They only appear
# once a PodMonitor makes user-workload monitoring scrape those pods.
serving_names='dynamo_component_inflight_requests|dynamo_component_gpu_cache_usage_percent|dynamo_request_queue|dynamo_work_handler_queue_depth|vllm:generation_tokens_total|vllm:prompt_tokens_total|vllm:e2e_request_latency_seconds_bucket|vllm:external_prefix_cache_hits_total|vllm:external_prefix_cache_queries_total'
if [ -n "$all_namespaces" ]; then
  serving_selector='namespace!=""'
else
  serving_selector="namespace=\"$namespace\""
fi
"$query_metrics" --query "{__name__=~\"$serving_names\",$serving_selector}" \
  >"$workdir/serving.json" 2>/dev/null || : >"$workdir/serving.json"

python3 - "$workdir/gpu.json" "$workdir/serving.json" "$pod_prefix" <<'PY'
import json
import sys


def load(path):
    try:
        with open(path) as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    if payload.get('status') != 'success':
        return []
    return payload.get('data', {}).get('result', [])


gpu_result = load(sys.argv[1])
serving_result = load(sys.argv[2])
pod_prefix = sys.argv[3]


def number(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# Key GPU telemetry by the consuming pod and the physical GPU index.
gpus = {}
for series in gpu_result:
    metric = series['metric']
    pod = metric.get('exported_pod') or ''
    if pod_prefix and not pod.startswith(pod_prefix):
        continue
    key = (metric.get('exported_namespace') or '-', pod, metric.get('gpu') or '?')
    entry = gpus.setdefault(key, {'node': metric.get('Hostname') or '-',
                                  'model': metric.get('modelName') or '-'})
    entry[metric.get('__name__')] = number(series['value'][1])

if not gpus:
    print('No GPU telemetry matched. Common causes:')
    print('  - the namespace has no GPU pods currently scheduled')
    print('  - DCGM metrics must be selected with exported_namespace, not namespace')
    print('  - the service account lacks the cluster-monitoring-view ClusterRole')
    raise SystemExit(0)

print('%-46s %-4s %-7s %-15s %-9s %-7s %s' % (
    'POD', 'GPU', 'UTIL%', 'MEM_USED/TOTAL', 'POWER_W', 'TEMP_C', 'NODE'))

pods = {}
for (ns, pod, gpu), entry in sorted(gpus.items(), key=lambda kv: (kv[0][0], kv[0][1], int(kv[0][2]) if kv[0][2].isdigit() else 0)):
    util = entry.get('DCGM_FI_DEV_GPU_UTIL')
    used = entry.get('DCGM_FI_DEV_FB_USED')
    free = entry.get('DCGM_FI_DEV_FB_FREE')
    power = entry.get('DCGM_FI_DEV_POWER_USAGE')
    temp = entry.get('DCGM_FI_DEV_GPU_TEMP')

    total = (used + free) if (used is not None and free is not None) else None
    mem = '%.0f/%.0f GiB' % (used / 1024.0, total / 1024.0) if total else '-'

    label = pod if pod else '(unattributed)'
    print('%-46s %-4s %-7s %-15s %-9s %-7s %s' % (
        label[:46], gpu,
        '-' if util is None else '%.0f' % util,
        mem,
        '-' if power is None else '%.0f' % power,
        '-' if temp is None else '%.0f' % temp,
        entry['node']))

    bucket = pods.setdefault((ns, label), {'gpus': 0, 'util': [], 'used': 0.0, 'power': 0.0})
    bucket['gpus'] += 1
    if util is not None:
        bucket['util'].append(util)
    if used is not None:
        bucket['used'] += used
    if power is not None:
        bucket['power'] += power

print()
print('%-46s %-10s %-8s %-10s %s' % ('POD_TOTAL', 'NAMESPACE', 'GPUS', 'MEAN_UTIL%', 'MEM_USED_GIB'))
for (ns, pod), bucket in sorted(pods.items()):
    mean_util = sum(bucket['util']) / len(bucket['util']) if bucket['util'] else 0.0
    print('%-46s %-10s %-8d %-10.0f %.0f' % (
        pod[:46], ns[:10], bucket['gpus'], mean_util, bucket['used'] / 1024.0))

# Serving-side view, when the PodMonitor is in place.
serving = {}
dynamo_metrics = {'dynamo_component_inflight_requests', 'dynamo_request_queue', 'dynamo_work_handler_queue_depth', 'dynamo_component_gpu_cache_usage_percent'}
vllm_metrics = {'vllm:generation_tokens_total', 'vllm:prompt_tokens_total', 'vllm:e2e_request_latency_seconds_bucket', 'vllm:external_prefix_cache_hits_total', 'vllm:external_prefix_cache_queries_total'}
all_serving_metrics = dynamo_metrics | vllm_metrics
for series in serving_result:
    metric = series['metric']
    pod = metric.get('pod') or '-'
    if pod_prefix and not pod.startswith(pod_prefix):
        continue
    value = number(series['value'][1])
    if value is None:
        continue
    name = metric.get('__name__')
    if name not in all_serving_metrics:
        continue
    bucket = serving.setdefault(pod, {})
    bucket[name] = bucket.get(name, 0.0) + value
    if metric.get('model'):
        bucket['model'] = metric['model']
    if metric.get('model_name'):
        bucket['model'] = metric['model_name']
    if metric.get('dynamo_component'):
        bucket['component'] = metric['dynamo_component']

print()
if serving:
    # Print Dynamo metrics if present
    dynamo_pods = {pod: bucket for pod, bucket in serving.items() if any(m in bucket for m in dynamo_metrics)}
    if dynamo_pods:
        print('%-46s %-18s %-10s %-10s %s' % (
            'POD (Dynamo)', 'MODEL', 'INFLIGHT', 'QUEUED', 'KV_CACHE%'))
        for pod, bucket in sorted(dynamo_pods.items()):
            print('%-46s %-18s %-10.0f %-10.0f %.1f' % (
                pod[:46],
                str(bucket.get('model', '-'))[:18],
                bucket.get('dynamo_component_inflight_requests', 0.0),
                bucket.get('dynamo_request_queue', 0.0) + bucket.get('dynamo_work_handler_queue_depth', 0.0),
                bucket.get('dynamo_component_gpu_cache_usage_percent', 0.0)))
    # Print vLLM metrics if present
    vllm_pods = {pod: bucket for pod, bucket in serving.items() if any(m in bucket for m in vllm_metrics)}
    if vllm_pods:
        print('%-46s %-18s %-12s %-12s %s' % (
            'POD (vLLM)', 'MODEL', 'GEN_TOK/s', 'PROMPT_TOK/s', 'CACHE_HIT%'))
        for pod, bucket in sorted(vllm_pods.items()):
            gen_toks = bucket.get('vllm:generation_tokens_total', 0.0)
            prompt_toks = bucket.get('vllm:prompt_tokens_total', 0.0)
            cache_hits = bucket.get('vllm:external_prefix_cache_hits_total', 0.0)
            cache_queries = bucket.get('vllm:external_prefix_cache_queries_total', 1.0)
            cache_pct = (cache_hits / cache_queries * 100.0) if cache_queries > 0 else 0.0
            print('%-46s %-18s %-12.1f %-12.1f %.1f' % (
                pod[:46],
                str(bucket.get('model', '-'))[:18],
                gen_toks,
                prompt_toks,
                cache_pct))
else:
    print('SERVING: no serving metrics (Dynamo or vLLM) are being scraped yet.')
    print('  For Dynamo: apply templates/dynamo-podmonitor.yaml to the model namespace')
    print('  For vLLM: apply templates/vllm-podmonitor.yaml to the model namespace')
    print('  Both require enableUserWorkload: true in cluster monitoring config.')
PY
