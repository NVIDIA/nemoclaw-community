# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Modified for this recipe: resolve a dedicated OpenShift gateway UID/GID.

{{/*
Gateway pod template shared by the StatefulSet and Deployment workload shapes.
*/}}
{{- define "openshell.gatewayPodTemplate" -}}
{{- $gatewaySecurityContext := deepCopy .Values.securityContext -}}
{{- $gatewayUidConfig := .Values.server.openshift.gatewayUid -}}
{{- if $gatewayUidConfig.enabled -}}
  {{- $gatewayUid := $gatewayUidConfig.value -}}
  {{- if eq $gatewayUid nil -}}
    {{- $namespace := lookup "v1" "Namespace" "" .Release.Namespace -}}
    {{- if not $namespace -}}
      {{- fail (printf "server.openshift.gatewayUid.enabled=true requires the release namespace %q to exist so Helm can resolve its openshift.io/sa.scc.uid-range annotation; pre-create the namespace or set server.openshift.gatewayUid.value only for offline rendering" .Release.Namespace) -}}
    {{- end -}}
    {{- $uidRange := index (default (dict) $namespace.metadata.annotations) "openshift.io/sa.scc.uid-range" | default "" -}}
    {{- if not (regexMatch "^[0-9]+/[0-9]+$" $uidRange) -}}
      {{- fail (printf "release namespace %q has no valid openshift.io/sa.scc.uid-range annotation" .Release.Namespace) -}}
    {{- end -}}
    {{- $parts := splitList "/" $uidRange -}}
    {{- $rangeStart := atoi (index $parts 0) -}}
    {{- $rangeSize := atoi (index $parts 1) -}}
    {{- $offset := int $gatewayUidConfig.offset -}}
    {{- if or (le $offset 0) (ge $offset $rangeSize) -}}
      {{- fail (printf "server.openshift.gatewayUid.offset must be greater than zero and less than the namespace SCC UID-range size (%d)" $rangeSize) -}}
    {{- end -}}
    {{- $gatewayUid = add $rangeStart $offset -}}
  {{- end -}}
  {{- if le (int $gatewayUid) 0 -}}
    {{- fail "server.openshift.gatewayUid.value must be a positive integer when set" -}}
  {{- end -}}
  {{- $_ := set $gatewaySecurityContext "runAsUser" (int $gatewayUid) -}}
{{- end -}}
metadata:
  annotations:
    # Roll the gateway workload when the rendered gateway TOML changes - the
    # gateway only reads /etc/openshell/gateway.toml at startup, so without
    # this annotation a `helm upgrade` that only mutates the ConfigMap would
    # leave pods running with stale config.
    checksum/gateway-config: {{ include (print $.Template.BasePath "/gateway-config.yaml") . | sha256sum }}
    {{- with .Values.podAnnotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  labels:
    {{- include "openshell.labels" . | nindent 4 }}
    {{- with .Values.podLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  terminationGracePeriodSeconds: {{ .Values.podLifecycle.terminationGracePeriodSeconds }}
  {{- with .Values.imagePullSecrets }}
  imagePullSecrets:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  serviceAccountName: {{ include "openshell.serviceAccountName" . }}
  {{- if .Values.server.hostGatewayIP }}
  hostAliases:
    - ip: {{ .Values.server.hostGatewayIP | quote }}
      hostnames:
        - host.docker.internal
        - host.openshell.internal
  {{- end }}
  securityContext:
    {{- toYaml .Values.podSecurityContext | nindent 4 }}
  containers:
    - name: openshell-gateway
      securityContext:
        {{- toYaml $gatewaySecurityContext | nindent 8 }}
      image: {{ include "openshell.image" . | quote }}
      imagePullPolicy: {{ .Values.image.pullPolicy }}
      args:
        - --config
        - /etc/openshell/gateway.toml
        {{- if not .Values.server.externalDbSecret }}
        - --db-url
        - {{ .Values.server.dbUrl | quote }}
        {{- end }}
      env:
        {{- if not (or .Values.server.credentialDrivers.kubernetesSecrets.enabled .Values.server.credentialDrivers.vault.enabled) }}
        - name: {{ include "openshell.credentialStorageKeyEncryptionKeyEnvName" . }}
          valueFrom:
            secretKeyRef:
              name: {{ include "openshell.credentialStorageKeyEncryptionKeySecretName" . }}
              key: {{ include "openshell.credentialStorageKeyEncryptionKeySecretKey" . }}
        {{- end }}
        {{- if .Values.server.externalDbSecret }}
        - name: OPENSHELL_DB_URL
          valueFrom:
            secretKeyRef:
              name: {{ .Values.server.externalDbSecret }}
              key: uri
        {{- end }}
        # Most gateway settings live in the ConfigMap-backed TOML file
        # mounted at /etc/openshell/gateway.toml. Secret-bearing settings use
        # env vars that the TOML references by name. Some process-level
        # settings consumed by libraries outside gateway code also remain here.
        {{- if and .Values.server.oidc.issuer .Values.server.oidc.caConfigMapName }}
        # OIDC issuer custom-CA: rustls-native-certs treats SSL_CERT_FILE
        # as a replacement for its native trust store. When the operator
        # supplies a system bundle path, keep that public bundle in
        # SSL_CERT_FILE and add this ConfigMap through SSL_CERT_DIR instead.
        # This preserves both cluster-private OIDC and public model endpoint
        # trust without disabling TLS verification.
        - name: SSL_CERT_FILE
          value: {{ default "/etc/openshell-tls/oidc-ca/ca.crt" .Values.server.oidc.systemCaBundlePath }}
        {{- if .Values.server.oidc.systemCaBundlePath }}
        - name: SSL_CERT_DIR
          value: /etc/openshell-tls/oidc-ca
        {{- end }}
        {{- end }}
        - name: OPENSHELL_TELEMETRY_ENABLED
          value: {{ .Values.server.telemetryEnabled | quote }}
        {{- if .Values.server.providerTokenGrants.spiffe.enabled }}
        - name: OPENSHELL_GATEWAY_SPIFFE_WORKLOAD_API_SOCKET
          value: {{ .Values.server.providerTokenGrants.spiffe.workloadApiSocketPath | quote }}
        {{- end }}
      volumeMounts:
        {{- if eq (include "openshell.workloadKind" .) "statefulset" }}
        - name: openshell-data
          mountPath: /var/openshell
        {{- end }}
        - name: gateway-config
          mountPath: /etc/openshell
          readOnly: true
        - name: sandbox-jwt
          mountPath: /etc/openshell-jwt
          readOnly: true
        {{- if not .Values.server.disableTls }}
        - name: tls-cert
          mountPath: /etc/openshell-tls/server
          readOnly: true
        {{- if .Values.certManager.serverIssuerRef.name }}
        - name: tls-external-cert
          mountPath: /etc/openshell-tls/server-external
          readOnly: true
        {{- end }}
        {{- if or .Values.server.tls.clientCaSecretName (and .Values.pkiInitJob.enabled (not .Values.certManager.enabled)) (and .Values.certManager.enabled .Values.certManager.clientCaFromServerTlsSecret) }}
        - name: tls-client-ca
          mountPath: /etc/openshell-tls/client-ca
          readOnly: true
        {{- end }}
        {{- end }}
        {{- if and .Values.server.oidc.issuer .Values.server.oidc.caConfigMapName }}
        - name: oidc-ca
          mountPath: /etc/openshell-tls/oidc-ca
          readOnly: true
        {{- end }}
        {{- if .Values.server.providerTokenGrants.spiffe.enabled }}
        - name: spiffe-workload-api
          mountPath: {{ dir .Values.server.providerTokenGrants.spiffe.workloadApiSocketPath | quote }}
          readOnly: true
        {{- end }}
      ports:
        - name: grpc
          containerPort: {{ .Values.service.port }}
          protocol: TCP
        - name: health
          containerPort: {{ .Values.service.healthPort }}
          protocol: TCP
        {{- if .Values.service.metricsPort }}
        - name: metrics
          containerPort: {{ .Values.service.metricsPort }}
          protocol: TCP
        {{- end }}
      startupProbe:
        httpGet:
          path: /healthz
          port: health
        periodSeconds: {{ .Values.probes.startup.periodSeconds }}
        timeoutSeconds: {{ .Values.probes.startup.timeoutSeconds }}
        failureThreshold: {{ .Values.probes.startup.failureThreshold }}
      livenessProbe:
        httpGet:
          path: /healthz
          port: health
        initialDelaySeconds: {{ .Values.probes.liveness.initialDelaySeconds }}
        periodSeconds: {{ .Values.probes.liveness.periodSeconds }}
        timeoutSeconds: {{ .Values.probes.liveness.timeoutSeconds }}
        failureThreshold: {{ .Values.probes.liveness.failureThreshold }}
      readinessProbe:
        httpGet:
          path: /readyz
          port: health
        initialDelaySeconds: {{ .Values.probes.readiness.initialDelaySeconds }}
        periodSeconds: {{ .Values.probes.readiness.periodSeconds }}
        timeoutSeconds: {{ .Values.probes.readiness.timeoutSeconds }}
        failureThreshold: {{ .Values.probes.readiness.failureThreshold }}
      resources:
        {{- toYaml .Values.resources | nindent 8 }}
  volumes:
    - name: gateway-config
      configMap:
        name: {{ include "openshell.fullname" . }}-config
    - name: sandbox-jwt
      secret:
        secretName: {{ include "openshell.sandboxJwtSecretName" . }}
        defaultMode: {{ .Values.server.sandboxJwt.secretDefaultMode | default 0400 }}
    {{- if not .Values.server.disableTls }}
    - name: tls-cert
      secret:
        secretName: {{ .Values.server.tls.certSecretName }}
    {{- if .Values.certManager.serverIssuerRef.name }}
    - name: tls-external-cert
      secret:
        secretName: {{ include "openshell.fullname" . }}-server-external-tls
    {{- end }}
    {{- if or .Values.server.tls.clientCaSecretName (and .Values.pkiInitJob.enabled (not .Values.certManager.enabled)) (and .Values.certManager.enabled .Values.certManager.clientCaFromServerTlsSecret) }}
    - name: tls-client-ca
      secret:
        {{- if or (and .Values.pkiInitJob.enabled (not .Values.certManager.enabled)) (and .Values.certManager.enabled .Values.certManager.clientCaFromServerTlsSecret) }}
        secretName: {{ .Values.server.tls.certSecretName }}
        items:
          - key: ca.crt
            path: ca.crt
        {{- else }}
        secretName: {{ .Values.server.tls.clientCaSecretName }}
        {{- end }}
    {{- end }}
    {{- end }}
    {{- if and .Values.server.oidc.issuer .Values.server.oidc.caConfigMapName }}
    - name: oidc-ca
      configMap:
        name: {{ .Values.server.oidc.caConfigMapName }}
    {{- end }}
    {{- if .Values.server.providerTokenGrants.spiffe.enabled }}
    - name: spiffe-workload-api
      csi:
        driver: csi.spiffe.io
        readOnly: true
    {{- end }}
  {{- with .Values.nodeSelector }}
  nodeSelector:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with .Values.affinity }}
  affinity:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with .Values.tolerations }}
  tolerations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
