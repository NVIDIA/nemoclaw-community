{{/*
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
Shared pod template for the Deployment (watch) and CronJob (heal --once) modes.
*/}}
{{- define "sre-autoheal.podSpec" -}}
{{- $root := .root -}}
{{- $args := .args -}}
{{- $overlays := include "sre-autoheal.overlayConfigMaps" $root | fromJsonArray -}}
{{- $parent := $root.Values.parentIntegration.hermesWebuiOpenshell -}}
serviceAccountName: {{ include "sre-autoheal.serviceAccountName" $root }}
automountServiceAccountToken: true
{{- with $root.Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with $root.Values.priorityClassName }}
priorityClassName: {{ . }}
{{- end }}
securityContext:
  {{- toYaml $root.Values.podSecurityContext | nindent 2 }}
containers:
  - name: agent
    image: {{ include "sre-autoheal.image" $root }}
    imagePullPolicy: {{ $root.Values.image.pullPolicy }}
    securityContext:
      {{- toYaml $root.Values.containerSecurityContext | nindent 6 }}
    command: ["python3", "-m", "sre_autoheal"]
    args:
      {{- toYaml $args | nindent 6 }}
    workingDir: /opt/sre-autoheal
    env:
      - name: PYTHONPATH
        value: /opt/sre-autoheal
      - name: PYTHONUNBUFFERED
        value: "1"
      - name: SRE_AUTOHEAL_CONFIG
        value: /etc/sre-autoheal/config.json
      - name: SRE_AUTOHEAL_KNOWLEDGE
        value: /opt/sre-autoheal/knowledge/failure_patterns.json
      - name: SRE_AUTOHEAL_NAMESPACE
        valueFrom: {fieldRef: {fieldPath: metadata.namespace}}
      {{- if gt (len $overlays) 0 }}
      - name: SRE_AUTOHEAL_CONFIG_DIR
        value: /etc/sre-autoheal/conf.d
      {{- end }}
      {{- if and $root.Values.llm.enabled $root.Values.llm.apiKeySecret.name }}
      - name: SRE_AUTOHEAL_LLM_API_KEY
        valueFrom: {secretKeyRef: {name: {{ $root.Values.llm.apiKeySecret.name }}, key: {{ $root.Values.llm.apiKeySecret.key }}}}
      {{- else if and $root.Values.llm.enabled $parent.enabled }}
      - name: SRE_AUTOHEAL_LLM_API_KEY
        valueFrom: {secretKeyRef: {name: {{ include "sre-autoheal.parentApiKeySecretName" $root }}, key: {{ $parent.apiKeySecretKey }}, optional: true}}
      {{- end }}
      {{- if and $root.Values.notifications.slack.enabled $root.Values.notifications.slack.secret.name }}
      - name: SRE_AUTOHEAL_SLACK_WEBHOOK_URL
        valueFrom: {secretKeyRef: {name: {{ $root.Values.notifications.slack.secret.name }}, key: {{ $root.Values.notifications.slack.secret.webhookKey }}, optional: true}}
      - name: SRE_AUTOHEAL_SLACK_BOT_TOKEN
        valueFrom: {secretKeyRef: {name: {{ $root.Values.notifications.slack.secret.name }}, key: {{ $root.Values.notifications.slack.secret.botTokenKey }}, optional: true}}
      {{- end }}
      {{- if and $root.Values.notifications.email.enabled $root.Values.notifications.email.secret.name }}
      - name: SRE_AUTOHEAL_SMTP_USERNAME
        valueFrom: {secretKeyRef: {name: {{ $root.Values.notifications.email.secret.name }}, key: {{ $root.Values.notifications.email.secret.usernameKey }}, optional: true}}
      - name: SRE_AUTOHEAL_SMTP_PASSWORD
        valueFrom: {secretKeyRef: {name: {{ $root.Values.notifications.email.secret.name }}, key: {{ $root.Values.notifications.email.secret.passwordKey }}, optional: true}}
      {{- end }}
      {{- if and $root.Values.notifications.webhook.enabled $root.Values.notifications.webhook.secret.name }}
      - name: SRE_AUTOHEAL_WEBHOOK_URL
        valueFrom: {secretKeyRef: {name: {{ $root.Values.notifications.webhook.secret.name }}, key: {{ $root.Values.notifications.webhook.secret.urlKey }}}}
      {{- end }}
    resources:
      {{- toYaml $root.Values.resources | nindent 6 }}
    volumeMounts:
      - name: config
        mountPath: /etc/sre-autoheal
        readOnly: true
      {{- if gt (len $overlays) 0 }}
      - name: config-overlays
        mountPath: /etc/sre-autoheal/conf.d
        readOnly: true
      {{- end }}
      {{- if $root.Values.agentSource.fromConfigMap }}
      - name: agent-src
        mountPath: /opt/sre-autoheal/sre_autoheal
        readOnly: true
      - name: knowledge
        mountPath: /opt/sre-autoheal/knowledge
        readOnly: true
      {{- end }}
      - name: tmp
        mountPath: /tmp
      {{- if eq $root.Values.memory.backend "file" }}
      - name: memory
        mountPath: /var/lib/sre-autoheal
      {{- end }}
volumes:
  - name: config
    configMap:
      name: {{ include "sre-autoheal.fullname" $root }}-config
  {{- if gt (len $overlays) 0 }}
  - name: config-overlays
    projected:
      sources:
        {{- range $overlays }}
        - configMap:
            name: {{ . }}
        {{- end }}
  {{- end }}
  {{- if $root.Values.agentSource.fromConfigMap }}
  - name: agent-src
    configMap:
      name: {{ include "sre-autoheal.fullname" $root }}-agent
  - name: knowledge
    configMap:
      name: {{ include "sre-autoheal.fullname" $root }}-knowledge
  {{- end }}
  - name: tmp
    emptyDir: {}
  {{- if eq $root.Values.memory.backend "file" }}
  - name: memory
    {{- if $root.Values.memory.persistence.enabled }}
    persistentVolumeClaim:
      claimName: {{ default (printf "%s-memory" (include "sre-autoheal.fullname" $root)) $root.Values.memory.persistence.existingClaim }}
    {{- else }}
    emptyDir: {}
    {{- end }}
  {{- end }}
{{- with $root.Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with $root.Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with $root.Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}
