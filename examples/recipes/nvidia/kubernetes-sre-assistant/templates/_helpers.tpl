# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
{{- /*
Naming helpers. Every helper below depends only on .Release and
.Values.global.sre so it renders identically from this chart's own templates
and from the deployer subchart's tpl-rendered values (global values are shared
with subcharts). Names are deterministic: <release>-sre-* for this chart and
<release>-deployer for the subchart (deployer.nameOverride=deployer).
*/ -}}

{{- define "sre-assistant.name" -}}
kubernetes-sre-assistant
{{- end -}}

{{- define "sre-assistant.fullname" -}}
{{- printf "%s-sre" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sre-assistant.deployerFullname" -}}
{{- printf "%s-deployer" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sre-assistant.releaseIdentityHash" -}}
{{- printf "%s/%s" .Release.Namespace .Release.Name | sha256sum | trunc 8 -}}
{{- end -}}

{{- define "sre-assistant.clusterResourceName" -}}
{{- printf "%s-%s" (printf "%s-%s" .Release.Namespace (include "sre-assistant.fullname" .) | trunc 54 | trimSuffix "-") (include "sre-assistant.releaseIdentityHash" .) -}}
{{- end -}}

{{- define "sre-assistant.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sre-assistant.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "sre-assistant.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "sre-assistant.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "sre-assistant.proxyName" -}}
{{- printf "%s-proxy" (include "sre-assistant.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sre-assistant.modelDeleteProxyName" -}}
{{- printf "%s-model-delete-proxy" (include "sre-assistant.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sre-assistant.metricsProxyName" -}}
{{- printf "%s-metrics-proxy" (include "sre-assistant.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sre-assistant.runtimeConfigMapName" -}}
{{- printf "%s-runtime" (include "sre-assistant.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sre-assistant.contractConfigMapName" -}}
{{- printf "%s-contract" (include "sre-assistant.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sre-assistant.skillsPartName" -}}
{{- $suffix := printf "-skills-%03d" (int .index) -}}
{{- $prefix := include "sre-assistant.fullname" .root | trunc (int (sub 63 (len $suffix))) | trimSuffix "-" -}}
{{- printf "%s%s" $prefix $suffix -}}
{{- end -}}

{{- define "sre-assistant.proxyAuthSecretName" -}}
{{- default (printf "%s-proxy-auth" (include "sre-assistant.fullname" .) | trunc 63 | trimSuffix "-") .Values.global.sre.proxy.authSecretRef.name -}}
{{- end -}}

{{- define "sre-assistant.proxyTlsSecretName" -}}
{{- default (printf "%s-proxy-tls" (include "sre-assistant.fullname" .) | trunc 63 | trimSuffix "-") .Values.global.sre.proxy.tlsSecretRef.name -}}
{{- end -}}

{{- define "sre-assistant.metricsCaConfigMapName" -}}
{{- default (printf "%s-metrics-service-ca" (include "sre-assistant.fullname" .) | trunc 63 | trimSuffix "-") .Values.global.sre.openshiftLlmDeploy.metrics.caConfigMapRef.name -}}
{{- end -}}

{{- define "sre-assistant.modelDeployNamespace" -}}
{{- default .Release.Namespace .Values.global.sre.openshiftLlmDeploy.targetNamespace -}}
{{- end -}}

{{- define "sre-assistant.modelRunnerServiceAccountName" -}}
{{- default (printf "%s-llm-runner" (include "sre-assistant.fullname" .) | trunc 63 | trimSuffix "-") .Values.global.sre.openshiftLlmDeploy.modelRunnerServiceAccount.name -}}
{{- end -}}

{{- /* https://<service>.<namespace>.svc.cluster.local:<proxy port> */ -}}
{{- define "sre-assistant.proxyEndpoint" -}}
{{- printf "https://%s.%s.svc.cluster.local:%d" .name .root.Release.Namespace (int .root.Values.global.sre.proxy.port) -}}
{{- end -}}

{{- define "sre-assistant.proxyHost" -}}
{{- printf "%s.%s.svc.cluster.local" .name .root.Release.Namespace -}}
{{- end -}}
