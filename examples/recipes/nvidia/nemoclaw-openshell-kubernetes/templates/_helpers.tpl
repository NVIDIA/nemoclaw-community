# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

{{- define "nemoclaw-openshell.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "nemoclaw-openshell.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "nemoclaw-openshell.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "nemoclaw-openshell.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "nemoclaw-openshell.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nemoclaw-openshell.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "nemoclaw-openshell.releaseIdentityHash" -}}
{{- printf "%s/%s" .Release.Namespace .Release.Name | sha256sum | trunc 8 -}}
{{- end -}}

{{- define "nemoclaw-openshell.agentName" -}}
{{- if .Values.agent.sandbox.name -}}
{{- .Values.agent.sandbox.name -}}
{{- else if eq .Values.openshell.mode "existing" -}}
{{- printf "%s-%s" (.Release.Name | trunc 10 | trimSuffix "-") (include "nemoclaw-openshell.releaseIdentityHash" .) | trunc 19 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-hermes" .Release.Name | trunc 19 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.stateClaimName" -}}
{{- default (printf "%s-hermes-state" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-") .Values.persistence.existingClaim -}}
{{- end -}}

{{- define "nemoclaw-openshell.lifecycleServiceAccountName" -}}
{{- if .Values.lifecycle.serviceAccount.create -}}
{{- default (printf "%s-lifecycle" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-") .Values.lifecycle.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.lifecycle.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.gatewayName" -}}
{{- if eq .Values.openshell.mode "existing" -}}
{{- .Values.openshell.existing.name -}}
{{- else if .Values.openshell.fullnameOverride -}}
{{- .Values.openshell.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default "openshell" .Values.openshell.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.gatewayEndpoint" -}}
{{- if eq .Values.openshell.mode "existing" -}}
{{- .Values.openshell.existing.endpoint -}}
{{- else -}}
{{- printf "https://%s.%s.svc.cluster.local:%d" (include "nemoclaw-openshell.gatewayName" .) .Release.Namespace (int .Values.openshell.service.port) -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.clientTLSSecretName" -}}
{{- if eq .Values.openshell.mode "existing" -}}
{{- .Values.openshell.existing.clientTLSSecretName -}}
{{- else -}}
{{- .Values.openshell.server.tls.clientTlsSecretName -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.sandboxServiceAccountName" -}}
{{- if .Values.openshell.sandboxServiceAccount.create -}}
{{- default (printf "%s-sandbox" (include "nemoclaw-openshell.gatewayName" .) | trunc 63 | trimSuffix "-") .Values.openshell.sandboxServiceAccount.name -}}
{{- else -}}
{{- default "default" .Values.openshell.sandboxServiceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.sreProxyName" -}}
{{- printf "%s-sre-proxy" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "nemoclaw-openshell.modelDeleteProxyName" -}}
{{- printf "%s-model-delete-proxy" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "nemoclaw-openshell.proxyAuthSecretName" -}}
{{- default (printf "%s-sre-proxy-auth" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-") .Values.sre.proxy.authSecretRef.name -}}
{{- end -}}

{{- define "nemoclaw-openshell.providerName" -}}
{{- if .Values.agent.model.providerName -}}
{{- .Values.agent.model.providerName -}}
{{- else if eq .Values.openshell.mode "existing" -}}
{{- printf "%s-model-%s" (include "nemoclaw-openshell.fullname" . | trunc 48 | trimSuffix "-") (include "nemoclaw-openshell.releaseIdentityHash" .) -}}
{{- else -}}
{{- printf "%s-model" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.clusterResourceName" -}}
{{- printf "%s-%s" (printf "%s-%s" .Release.Namespace (include "nemoclaw-openshell.fullname" .) | trunc 54 | trimSuffix "-") (include "nemoclaw-openshell.releaseIdentityHash" .) -}}
{{- end -}}

{{- define "nemoclaw-openshell.policy" -}}
{{ .Files.Get "files/policy.yaml" -}}
{{- if .Values.sre.enabled }}
  kubernetes_sre:
    name: kubernetes_sre
    endpoints:
      - host: {{ printf "%s.%s.svc.cluster.local" (include "nemoclaw-openshell.sreProxyName" .) .Release.Namespace }}
        port: {{ .Values.sre.proxy.port }}
        protocol: rest
        enforcement: enforce
        rules:
          - allow: { method: GET, path: "/**" }
          - allow: { method: PATCH, path: "/**" }
          {{- if eq .Values.sre.rbac.mode "broad-no-delete" }}
          - allow: { method: POST, path: "/**" }
          - allow: { method: PUT, path: "/**" }
          {{- end }}
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/local/bin/curl }
      - { path: /usr/bin/python3* }
      - { path: /opt/hermes/.venv/bin/python }
{{- end }}
{{- if .Values.sre.openshiftLlmDeploy.deletion.enabled }}
  openshift_llm_delete:
    name: openshift_llm_delete
    endpoints:
      - host: {{ printf "%s.%s.svc.cluster.local" (include "nemoclaw-openshell.modelDeleteProxyName" .) .Release.Namespace }}
        port: {{ .Values.sre.proxy.port }}
        protocol: rest
        enforcement: enforce
        rules:
          - allow: { method: GET, path: "/**" }
          - allow: { method: DELETE, path: "/**" }
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/local/bin/curl }
      - { path: /usr/bin/python3* }
      - { path: /opt/hermes/.venv/bin/python }
{{- end }}
{{- end -}}
