{{/*
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
*/}}
{{- define "sre-autoheal.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sre-autoheal.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "sre-autoheal.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
app.kubernetes.io/name: {{ include "sre-autoheal.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: sre-autoheal
{{- end -}}

{{- define "sre-autoheal.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sre-autoheal.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "sre-autoheal.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "sre-autoheal.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "sre-autoheal.image" -}}
{{- if .Values.image.digest -}}
{{ .Values.image.repository }}@{{ .Values.image.digest }}
{{- else -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}
{{- end -}}

{{/* Full agent config rendered as JSON (the agent reads JSON without PyYAML). */}}
{{- define "sre-autoheal.agentConfig" -}}
{{- $cfg := deepCopy .Values.agentConfig -}}
{{- $_ := set $cfg "cluster" (dict "platform" "auto" "transport" "http" "request_timeout_seconds" 30) -}}
{{- $mem := merge (dict "backend" .Values.memory.backend "path" "/var/lib/sre-autoheal/memory.json" "configmap_name" (printf "%s-memory" (include "sre-autoheal.fullname" .)) "configmap_namespace" .Release.Namespace) (default dict $cfg.memory) -}}
{{- $_ := set $cfg "memory" $mem -}}
{{- $llm := dict "enabled" .Values.llm.enabled "provider" .Values.llm.provider "base_url" .Values.llm.baseUrl "model" .Values.llm.model "timeout_seconds" .Values.llm.timeoutSeconds "max_tokens" .Values.llm.maxTokens "effort" .Values.llm.effort "redact_logs" .Values.llm.redactLogs "api_key_env" "SRE_AUTOHEAL_LLM_API_KEY" -}}
{{- $_ := set $cfg "llm" $llm -}}
{{- $n := .Values.notifications -}}
{{- $notify := dict
      "environment" $n.environment
      "cluster_name" $n.clusterName
      "runbook_base_url" $n.runbookBaseUrl
      "events" $n.events
      "dedupe_seconds" $n.dedupeSeconds
      "posture_dedupe_seconds" $n.postureDedupeSeconds
      "stdout" (dict "enabled" $n.stdout)
      "slack" (dict "enabled" $n.slack.enabled "channel" $n.slack.channel "mention_on_escalation" $n.slack.mentionOnEscalation "webhook_url_env" "SRE_AUTOHEAL_SLACK_WEBHOOK_URL" "bot_token_env" "SRE_AUTOHEAL_SLACK_BOT_TOKEN")
      "email" (dict "enabled" $n.email.enabled "smtp_host" $n.email.smtpHost "smtp_port" $n.email.smtpPort "starttls" $n.email.starttls "ssl" $n.email.ssl "from_addr" $n.email.from "to_addrs" $n.email.to "username_env" "SRE_AUTOHEAL_SMTP_USERNAME" "password_env" "SRE_AUTOHEAL_SMTP_PASSWORD")
      "webhook" (dict "enabled" $n.webhook.enabled "headers" $n.webhook.headers "url_env" "SRE_AUTOHEAL_WEBHOOK_URL") -}}
{{- $_ := set $cfg "notify" $notify -}}
{{- $cfg | toPrettyJson -}}
{{- end -}}

{{/* Parent (hermes-webui-openshell) fullname, mirroring its own helper. */}}
{{- define "sre-autoheal.parentFullname" -}}
{{- $parent := .Values.parentIntegration.hermesWebuiOpenshell.parentChartName -}}
{{- if contains $parent .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $parent | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "sre-autoheal.parentConfigMapName" -}}
{{- default (printf "%s-sre-autoheal-parent" (include "sre-autoheal.parentFullname" .)) .Values.parentIntegration.hermesWebuiOpenshell.configMapName -}}
{{- end -}}

{{- define "sre-autoheal.parentApiKeySecretName" -}}
{{- default (printf "%s-runtime" (include "sre-autoheal.parentFullname" .)) .Values.parentIntegration.hermesWebuiOpenshell.apiKeySecretName -}}
{{- end -}}

{{/* All config overlay ConfigMaps (parent + extraConfigMaps) as a list of names. */}}
{{- define "sre-autoheal.overlayConfigMaps" -}}
{{- $names := list -}}
{{- if .Values.parentIntegration.hermesWebuiOpenshell.enabled -}}
{{- $names = append $names (include "sre-autoheal.parentConfigMapName" .) -}}
{{- end -}}
{{- range .Values.extraConfigMaps -}}
{{- $names = append $names . -}}
{{- end -}}
{{- toJson $names -}}
{{- end -}}
