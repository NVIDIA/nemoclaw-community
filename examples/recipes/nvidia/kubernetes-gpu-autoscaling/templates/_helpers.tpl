{{/* SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. */}}
{{/* SPDX-License-Identifier: Apache-2.0 */}}
{{- define "nemoclaw-gpu.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nemoclaw-gpu.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "nemoclaw-gpu.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nemoclaw-gpu.labels" -}}
helm.sh/chart: {{ include "nemoclaw-gpu.chart" . }}
{{ include "nemoclaw-gpu.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "nemoclaw-gpu.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nemoclaw-gpu.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
component: gpu-agent
nemoclaw.ai/workload-type: gpu
{{- end }}

{{- define "nemoclaw-gpu.namespace" -}}
{{- .Values.namespace.name }}
{{- end }}

{{- define "nemoclaw-gpu.ingressAuthSecretName" -}}
{{- printf "%s-agent-ingress-auth" (include "nemoclaw-gpu.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nemoclaw-gpu.gatewayName" -}}
{{- printf "%s-agent" (include "nemoclaw-gpu.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nemoclaw-gpu.httpRouteName" -}}
{{- printf "%s-agent" (include "nemoclaw-gpu.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nemoclaw-gpu.openShellHttpRouteName" -}}
{{- printf "%s-openshell" (include "nemoclaw-gpu.httpRouteName" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nemoclaw-gpu.httpPathMatchType" -}}
{{- /* Map chart pathType (Prefix|Exact) to Gateway API PathMatchType. */ -}}
{{- $pathType := .Values.ingress.pathType | default "Prefix" -}}
{{- if eq $pathType "Exact" -}}
Exact
{{- else -}}
PathPrefix
{{- end -}}
{{- end }}

{{- define "nemoclaw-gpu.inferenceApiSecretName" -}}
{{- if .Values.inference.auth.existingSecret -}}
{{- .Values.inference.auth.existingSecret -}}
{{- else -}}
{{- printf "%s-agent-inference-api" (include "nemoclaw-gpu.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{- define "nemoclaw-gpu.replicas" -}}
{{- if .Values.gpuScaling.oneReplicaPerGpu -}}
{{- .Values.gpuScaling.count | int }}
{{- else -}}
{{- .Values.replicaCount | int }}
{{- end -}}
{{- end }}

{{- define "nemoclaw-gpu.ollamaResources" -}}
requests:
  cpu: {{ .Values.gpuScaling.perPodCpuRequest | quote }}
  memory: {{ .Values.gpuScaling.perPodMemory | quote }}
  nvidia.com/gpu: {{ .Values.gpuScaling.perPodGpu | quote }}
limits:
  cpu: {{ .Values.gpuScaling.perPodCpuLimit | quote }}
  memory: {{ .Values.gpuScaling.perPodMemoryLimit | quote }}
  nvidia.com/gpu: {{ .Values.gpuScaling.perPodGpu | quote }}
{{- end }}

{{- define "nemoclaw-gpu.agentResources" -}}
requests:
  cpu: {{ .Values.gpuScaling.agentCpuRequest | quote }}
  memory: {{ .Values.gpuScaling.agentMemory | quote }}
limits:
  cpu: {{ .Values.gpuScaling.agentCpuLimit | quote }}
  memory: {{ .Values.gpuScaling.agentMemoryLimit | quote }}
{{- end }}

{{- /*
One replica = one GPU in GPU mode, so the HPA must never be allowed to scale past
maxGpus even if maxReplicas is set higher — extra pods would just sit Pending with
no GPU to schedule onto. Use the lower of the two positive limits in that mode.
*/}}
{{- define "nemoclaw-gpu.hpaMaxReplicas" -}}
{{- $maxReplicas := int .Values.autoscaling.maxReplicas -}}
{{- $maxGpus := int .Values.autoscaling.maxGpus -}}
{{- if .Values.gpuScaling.oneReplicaPerGpu -}}
{{- if and (gt $maxReplicas 0) (gt $maxGpus 0) -}}
{{- min $maxReplicas $maxGpus -}}
{{- else if gt $maxGpus 0 -}}
{{- $maxGpus -}}
{{- else if gt $maxReplicas 0 -}}
{{- $maxReplicas -}}
{{- else -}}
{{- 10 -}}
{{- end -}}
{{- else if gt $maxReplicas 0 -}}
{{- $maxReplicas -}}
{{- else -}}
{{- 10 -}}
{{- end -}}
{{- end }}

{{- define "nemoclaw-gpu.hpaMinReplicas" -}}
{{- $min := int .Values.autoscaling.minReplicas -}}
{{- if lt $min 1 -}}
{{- 1 -}}
{{- else -}}
{{- $min -}}
{{- end -}}
{{- end }}

{{- define "nemoclaw-gpu.hpaMetric" -}}
{{- $metric := .Values.autoscaling.metric | default "gpu" -}}
{{- if eq $metric "gpu" -}}
gpu_utilization_percent
{{- else if eq $metric "latency_p50" -}}
nemoclaw_llm_latency_p50_milliseconds
{{- else if eq $metric "latency_p95" -}}
nemoclaw_llm_latency_p95_milliseconds
{{- else if eq $metric "latency_avg" -}}
nemoclaw_llm_latency_avg_milliseconds
{{- else if eq $metric "request_rate" -}}
nemoclaw_llm_request_rate
{{- else -}}
{{- fail (printf "autoscaling.metric %q is unsupported; use gpu, latency_p50, latency_p95, latency_avg, or request_rate" $metric) -}}
{{- end -}}
{{- end }}

{{- define "nemoclaw-gpu.hpaMetricTarget" -}}
{{- $metric := .Values.autoscaling.metric | default "gpu" -}}
{{- if eq $metric "gpu" -}}
{{- .Values.autoscaling.targetGPUUtilizationPercentage | toString -}}
{{- else if or (eq $metric "latency_p50") (eq $metric "latency_p95") (eq $metric "latency_avg") -}}
{{- .Values.autoscaling.targetLatencyMilliseconds | toString -}}
{{- else if eq $metric "request_rate" -}}
{{- .Values.autoscaling.targetRequestRate | toString -}}
{{- else -}}
{{- fail (printf "autoscaling.metric %q is unsupported" $metric) -}}
{{- end -}}
{{- end }}

{{- define "nemoclaw-gpu.hpaMetricDisplay" -}}
{{- $metric := .Values.autoscaling.metric | default "gpu" -}}
{{- if eq $metric "gpu" -}}
GPU utilization % (DCGM)
{{- else if eq $metric "latency_p50" -}}
LLM end-to-end latency p50 (ms)
{{- else if eq $metric "latency_p95" -}}
LLM end-to-end latency p95 (ms)
{{- else if eq $metric "latency_avg" -}}
LLM end-to-end latency avg (ms)
{{- else if eq $metric "request_rate" -}}
Successful chat completions per second (per pod)
{{- end -}}
{{- end }}
