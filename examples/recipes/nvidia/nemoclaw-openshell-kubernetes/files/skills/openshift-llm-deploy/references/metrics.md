# Metrics query reference

The SRE runtime sends direct Prometheus query paths to the chart's dedicated
metrics proxy. That proxy owns the fixed upstream Service identity and never
accepts a monitoring bearer token, disables TLS verification, or opens a local
port-forward.

Use `scripts/query-metrics.sh --query '<promql>'` for OpenShift's
`openshift-monitoring/thanos-querier`. Standard Kubernetes clusters need a
compatible Prometheus service or should treat this optional workflow as
unavailable.

Useful queries:

- GPU utilization: `DCGM_FI_DEV_GPU_UTIL{exported_namespace="<namespace>"}`
- GPU memory used: `DCGM_FI_DEV_FB_USED{exported_namespace="<namespace>"}`
- GPU power: `DCGM_FI_DEV_POWER_USAGE{exported_namespace="<namespace>"}`
- GPU temperature: `DCGM_FI_DEV_GPU_TEMP{exported_namespace="<namespace>"}`
- vLLM generation tokens: `rate(vllm:generation_tokens_total[5m])`
- vLLM prompt tokens: `rate(vllm:prompt_tokens_total[5m])`
- Dynamo inflight: `dynamo_component_inflight_requests`
- Dynamo KV cache: `dynamo_component_gpu_cache_usage_percent`

DCGM's `namespace`, `pod`, and `container` labels describe the exporter.
The consuming workload is identified by `exported_namespace`,
`exported_pod`, and `exported_container`.

Do not infer readiness from the presence of a time series. Correlate metrics
with workload readiness and the endpoint verification helper.
