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

{{- define "nemoclaw-openshell.operatorClientName" -}}
{{- $fullname := include "nemoclaw-openshell.fullname" . -}}
{{- $candidate := printf "%s-operator-client" $fullname -}}
{{- if le (len $candidate) 52 -}}
{{- $candidate -}}
{{- else -}}
{{- printf "%s-%s-operator-client" ($fullname | trunc 27 | trimSuffix "-") ($fullname | sha256sum | trunc 8) -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.operatorClientServiceAccountName" -}}
{{- include "nemoclaw-openshell.operatorClientName" . -}}
{{- end -}}

{{- define "nemoclaw-openshell.operatorClientSubject" -}}
{{- printf "system:serviceaccount:%s:%s" .Release.Namespace (include "nemoclaw-openshell.operatorClientServiceAccountName" .) -}}
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

{{- define "nemoclaw-openshell.metricsProxyName" -}}
{{- printf "%s-metrics-proxy" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "nemoclaw-openshell.metricsCaConfigMapName" -}}
{{- default (printf "%s-metrics-service-ca" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-") .Values.sre.openshiftLlmDeploy.metrics.caConfigMapRef.name -}}
{{- end -}}

{{- define "nemoclaw-openshell.modelDeployNamespace" -}}
{{- default .Release.Namespace .Values.sre.openshiftLlmDeploy.targetNamespace -}}
{{- end -}}

{{- define "nemoclaw-openshell.modelRunnerServiceAccountName" -}}
{{- default (printf "%s-llm-runner" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-") .Values.sre.openshiftLlmDeploy.modelRunnerServiceAccount.name -}}
{{- end -}}

{{- define "nemoclaw-openshell.proxyAuthSecretName" -}}
{{- default (printf "%s-sre-proxy-auth" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-") .Values.sre.proxy.authSecretRef.name -}}
{{- end -}}

{{- define "nemoclaw-openshell.proxyTlsSecretName" -}}
{{- default (printf "%s-proxy-tls" (include "nemoclaw-openshell.fullname" .) | trunc 63 | trimSuffix "-") .Values.sre.proxy.tlsSecretRef.name -}}
{{- end -}}

{{- define "nemoclaw-openshell.sreSkillsPartName" -}}
{{- $suffix := printf "-sre-skills-%03d" (int .index) -}}
{{- $prefix := include "nemoclaw-openshell.fullname" .root | trunc (int (sub 63 (len $suffix))) | trimSuffix "-" -}}
{{- printf "%s%s" $prefix $suffix -}}
{{- end -}}

{{- define "nemoclaw-openshell.openshiftSandboxUid" -}}
{{- $uidConfig := .Values.openshell.server.openshift.sandboxUid -}}
{{- $sandboxUid := $uidConfig.value -}}
{{- if eq $sandboxUid nil -}}
  {{- $namespace := lookup "v1" "Namespace" "" .Release.Namespace -}}
  {{- if not $namespace -}}
    {{- fail (printf "openshell.server.openshift.sandboxUid.enabled=true requires the release namespace %q to exist so Helm can resolve its openshift.io/sa.scc.uid-range annotation; pre-create the namespace or set openshell.server.openshift.sandboxUid.value only for offline rendering" .Release.Namespace) -}}
  {{- end -}}
  {{- $uidRange := index (default (dict) $namespace.metadata.annotations) "openshift.io/sa.scc.uid-range" | default "" -}}
  {{- if not (regexMatch "^[0-9]+/[0-9]+$" $uidRange) -}}
    {{- fail (printf "release namespace %q has no valid openshift.io/sa.scc.uid-range annotation" .Release.Namespace) -}}
  {{- end -}}
  {{- $parts := splitList "/" $uidRange -}}
  {{- $rangeStart := atoi (index $parts 0) -}}
  {{- $rangeSize := atoi (index $parts 1) -}}
  {{- $offset := int $uidConfig.offset -}}
  {{- if or (le $offset 0) (ge $offset $rangeSize) -}}
    {{- fail (printf "openshell.server.openshift.sandboxUid.offset must be greater than zero and less than the namespace SCC UID-range size (%d)" $rangeSize) -}}
  {{- end -}}
  {{- $sandboxUid = add $rangeStart $offset -}}
{{- end -}}
{{- if le (int $sandboxUid) 0 -}}
  {{- fail "openshell.server.openshift.sandboxUid.value must be a positive integer when set" -}}
{{- end -}}
{{- int $sandboxUid -}}
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
{{- $basePolicy := .Files.Get "files/policy.yaml" -}}
{{- if .Values.sre.enabled -}}
  {{- $basePolicy = replace "  read_only:\n" "  read_only:\n    - /chart-bin\n" $basePolicy -}}
{{- end -}}
{{ $basePolicy -}}
{{- if .Values.sre.enabled }}
  kubernetes_sre:
    name: kubernetes_sre
    endpoints:
      - host: {{ printf "%s.%s.svc.cluster.local" (include "nemoclaw-openshell.sreProxyName" .) .Release.Namespace }}
        port: {{ .Values.sre.proxy.port }}
        protocol: rest
        # Preserve the chart proxy's private-CA TLS session. OpenShell still
        # enforces exact host/port/binary policy; the chart proxy enforces L7.
        tls: skip
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
      - { path: /chart-bin/oc }
      - { path: /chart-bin/kubectl }
{{- end }}
{{- if .Values.sre.openshiftLlmDeploy.deletion.enabled }}
  openshift_llm_delete:
    name: openshift_llm_delete
    endpoints:
      - host: {{ printf "%s.%s.svc.cluster.local" (include "nemoclaw-openshell.modelDeleteProxyName" .) .Release.Namespace }}
        port: {{ .Values.sre.proxy.port }}
        protocol: rest
        tls: skip
        enforcement: enforce
        rules:
          - allow: { method: GET, path: "/**" }
          - allow: { method: DELETE, path: "/**" }
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/local/bin/curl }
      - { path: /usr/bin/python3* }
      - { path: /opt/hermes/.venv/bin/python }
      - { path: /chart-bin/oc }
      - { path: /chart-bin/kubectl }
{{- end }}
{{- if .Values.sre.openshiftLlmDeploy.metrics.enabled }}
  cluster_metrics:
    name: cluster_metrics
    endpoints:
      - host: {{ printf "%s.%s.svc.cluster.local" (include "nemoclaw-openshell.metricsProxyName" .) .Release.Namespace }}
        port: {{ .Values.sre.proxy.port }}
        protocol: rest
        tls: skip
        enforcement: enforce
        rules:
          - allow: { method: GET, path: "/**" }
    binaries:
      - { path: /chart-bin/oc }
      - { path: /chart-bin/kubectl }
{{- end }}
{{- if .Values.sre.openshiftLlmDeploy.enabled }}
  model_release_metadata:
    name: model_release_metadata
    endpoints:
      - host: api.github.com
        port: 443
        protocol: rest
        enforcement: enforce
        rules:
          - allow: { method: GET, path: "/repos/vllm-project/vllm/releases/latest" }
          - allow: { method: GET, path: "/repos/ai-dynamo/dynamo/releases/latest" }
      - host: github.com
        port: 443
        protocol: rest
        enforcement: enforce
        rules:
          - allow: { method: GET, path: "/vllm-project/vllm/releases/latest" }
          - allow: { method: GET, path: "/vllm-project/vllm/releases/tag/**" }
      - host: hub.docker.com
        port: 443
        protocol: rest
        enforcement: enforce
        rules:
          - allow: { method: GET, path: "/v2/repositories/vllm/vllm-openai/tags/**" }
      - host: nvcr.io
        port: 443
        protocol: rest
        enforcement: enforce
        rules:
          - allow: { method: GET, path: "/proxy_auth" }
          - allow: { method: GET, path: "/v2/nvidia/ai-dynamo/vllm-runtime/manifests/**" }
          - allow: { method: GET, path: "/v2/nvidia/ai-dynamo/tensorrtllm-runtime/manifests/**" }
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/local/bin/curl }
{{- end }}
{{- end -}}
