# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
{{- /*
Values handed to the kubernetes-deployer subchart. Helm passes subchart values
statically, so values.yaml points each deployer extension point at one of these
named templates; the deployer renders them with tpl inside its own context,
where .Values.global.sre is this chart's configuration and .Release is the
shared release. Each template emits YAML for exactly one extension point.
*/ -}}

{{- /* agent.env: sandbox environment for the Hermes skills. */ -}}
{{- define "sre-assistant.agentEnv" -}}
{{- $sre := .Values.global.sre -}}
KUBERNETES_SRE_ENDPOINT: {{ include "sre-assistant.proxyEndpoint" (dict "root" . "name" (include "sre-assistant.proxyName" .)) | quote }}
KUBECONFIG: /sandbox/.hermes/sre-kubeconfig
SRE_KUBECONFIG: /sandbox/.hermes/sre-kubeconfig
{{- if $sre.openshiftLlmDeploy.enabled }}
OPENSHIFT_LLM_TARGET_NAMESPACE: {{ include "sre-assistant.modelDeployNamespace" . | quote }}
OPENSHIFT_LLM_RUNNER_SERVICE_ACCOUNT: {{ include "sre-assistant.modelRunnerServiceAccountName" . | quote }}
MONITORING_NAMESPACE: {{ $sre.openshiftLlmDeploy.metrics.namespace | quote }}
MONITORING_SERVICE: {{ $sre.openshiftLlmDeploy.metrics.service | quote }}
MONITORING_SERVICE_PORT: {{ $sre.openshiftLlmDeploy.metrics.port | quote }}
MONITORING_ENABLED: {{ $sre.openshiftLlmDeploy.metrics.enabled | quote }}
{{- if $sre.openshiftLlmDeploy.metrics.enabled }}
METRICS_KUBECONFIG: /sandbox/.hermes/metrics-kubeconfig
{{- end }}
{{- if $sre.openshiftLlmDeploy.deletion.enabled }}
OPENSHIFT_LLM_DELETE_ENDPOINT: {{ include "sre-assistant.proxyEndpoint" (dict "root" . "name" (include "sre-assistant.modelDeleteProxyName" .)) | quote }}
OPENSHIFT_LLM_DELETE_NAMESPACE: {{ $sre.openshiftLlmDeploy.deletion.namespace | quote }}
OPENSHIFT_LLM_DELETE_ALLOWED_RESOURCES: {{ $sre.openshiftLlmDeploy.deletion.allowedResources | toJson | quote }}
MODEL_DELETE_KUBECONFIG: /sandbox/.hermes/model-delete-kubeconfig
{{- end }}
{{- end }}
{{- end -}}

{{- /* agent.extraStateMounts: read-only subpaths the seed plugin populates. */ -}}
{{- define "sre-assistant.extraStateMounts" -}}
{{- $sre := .Values.global.sre -}}
- mountPath: /sandbox/.hermes/skills/kubernetes-sre
  subPath: hermes/skills/kubernetes-sre
  readOnly: true
- mountPath: /sandbox/.hermes/.sre-proxy-token
  subPath: hermes/.sre-proxy-token
  readOnly: true
- mountPath: /sandbox/.hermes/sre-kubeconfig
  subPath: hermes/sre-kubeconfig
  readOnly: true
- mountPath: /chart-bin
  subPath: hermes/bin
  readOnly: true
{{- if $sre.openshiftLlmDeploy.enabled }}
- mountPath: /sandbox/.hermes/skills/openshift-llm-deploy
  subPath: hermes/skills/openshift-llm-deploy
  readOnly: true
{{- if $sre.openshiftLlmDeploy.deletion.enabled }}
- mountPath: /sandbox/.hermes/model-delete-kubeconfig
  subPath: hermes/model-delete-kubeconfig
  readOnly: true
{{- end }}
{{- if $sre.openshiftLlmDeploy.metrics.enabled }}
- mountPath: /sandbox/.hermes/metrics-kubeconfig
  subPath: hermes/metrics-kubeconfig
  readOnly: true
{{- end }}
{{- end }}
{{- end -}}

{{- /* policy.networkPolicies: OpenShell egress entries for the chart proxies. */ -}}
{{- define "sre-assistant.networkPolicies" -}}
{{- $sre := .Values.global.sre -}}
kubernetes_sre:
  name: kubernetes_sre
  endpoints:
    - host: {{ include "sre-assistant.proxyHost" (dict "root" . "name" (include "sre-assistant.proxyName" .)) }}
      port: {{ int $sre.proxy.port }}
      protocol: rest
      # Preserve the chart proxy's private-CA TLS session. OpenShell still
      # enforces exact host/port/binary policy; the chart proxy enforces L7.
      tls: skip
      enforcement: enforce
      rules:
        - allow: { method: GET, path: "/**" }
        - allow: { method: PATCH, path: "/**" }
        {{- if eq $sre.rbac.mode "broad-no-delete" }}
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
{{- if $sre.openshiftLlmDeploy.deletion.enabled }}
openshift_llm_delete:
  name: openshift_llm_delete
  endpoints:
    - host: {{ include "sre-assistant.proxyHost" (dict "root" . "name" (include "sre-assistant.modelDeleteProxyName" .)) }}
      port: {{ int $sre.proxy.port }}
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
{{- if and $sre.openshiftLlmDeploy.enabled $sre.openshiftLlmDeploy.metrics.enabled }}
cluster_metrics:
  name: cluster_metrics
  endpoints:
    - host: {{ include "sre-assistant.proxyHost" (dict "root" . "name" (include "sre-assistant.metricsProxyName" .)) }}
      port: {{ int $sre.proxy.port }}
      protocol: rest
      tls: skip
      enforcement: enforce
      rules:
        - allow: { method: GET, path: "/**" }
  binaries:
    - { path: /chart-bin/oc }
    - { path: /chart-bin/kubectl }
{{- end }}
{{- if $sre.openshiftLlmDeploy.enabled }}
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

{{- /* lifecycle.seed.plugins: the single SRE seed plugin. */ -}}
{{- define "sre-assistant.seedPlugins" -}}
{{- $sre := .Values.global.sre -}}
{{- $llm := $sre.openshiftLlmDeploy -}}
- name: sre
  configMapName: {{ include "sre-assistant.runtimeConfigMapName" . | quote }}
  entrypoint: seed_sre.py
  # The reviewed skill archive digest joins the sandbox configuration identity.
  identity: {{ $sre.bundle.sha256 | quote }}
  env:
    - name: SRE_PROXY_ENDPOINT
      value: {{ include "sre-assistant.proxyEndpoint" (dict "root" . "name" (include "sre-assistant.proxyName" .)) | quote }}
    - name: RELEASE_NAMESPACE
      value: {{ ternary (include "sre-assistant.modelDeployNamespace" .) .Release.Namespace $llm.enabled | quote }}
    - name: OPENSHIFT_LLM_DEPLOY_ENABLED
      value: {{ $llm.enabled | quote }}
    - name: MODEL_DELETE_ENABLED
      value: {{ $llm.deletion.enabled | quote }}
    - name: METRICS_ENABLED
      value: {{ $llm.metrics.enabled | quote }}
    {{- if $llm.enabled }}
    - name: DYNAMO_DEFAULTS_JSON
      value: {{ $llm.dynamo | toJson | quote }}
    - name: HF_TOKEN_INTAKE_JSON
      value: {{ dict
        "enabled" false
        "namespace" (include "sre-assistant.modelDeployNamespace" .)
        "secretName" $llm.hfTokenSecretRef.name
        "secretKey" $llm.hfTokenSecretRef.key
        "deleteAfterDownload" false
        "requireTokenForHuggingFaceModels" true
        "modelRunnerServiceAccount" (include "sre-assistant.modelRunnerServiceAccountName" .)
        | toJson | quote }}
    {{- end }}
    {{- if $llm.deletion.enabled }}
    - name: MODEL_DELETE_PROXY_ENDPOINT
      value: {{ include "sre-assistant.proxyEndpoint" (dict "root" . "name" (include "sre-assistant.modelDeleteProxyName" .)) | quote }}
    - name: MODEL_DELETE_NAMESPACE
      value: {{ $llm.deletion.namespace | quote }}
    {{- end }}
    {{- if $llm.metrics.enabled }}
    - name: METRICS_PROXY_ENDPOINT
      value: {{ include "sre-assistant.proxyEndpoint" (dict "root" . "name" (include "sre-assistant.metricsProxyName" .)) | quote }}
    - name: METRICS_NAMESPACE
      value: {{ $llm.metrics.namespace | quote }}
    {{- end }}
  initContainers:
    - name: stage-sre-cli
      image: {{ $sre.utilityImage | quote }}
      imagePullPolicy: IfNotPresent
      command: ["/usr/local/bin/python3", "-B", "/plugins/sre/stage_sre_cli.py"]
      env:
        - name: OPENSHIFT_CLI_VERSION
          value: {{ $sre.cli.version | quote }}
        - name: OPENSHIFT_CLI_AMD64_URL
          value: {{ $sre.cli.amd64.url | quote }}
        - name: OPENSHIFT_CLI_AMD64_SHA256
          value: {{ $sre.cli.amd64.sha256 | quote }}
        - name: OPENSHIFT_CLI_ARM64_URL
          value: {{ $sre.cli.arm64.url | quote }}
        - name: OPENSHIFT_CLI_ARM64_SHA256
          value: {{ $sre.cli.arm64.sha256 | quote }}
      securityContext:
        runAsNonRoot: true
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      resources:
        requests:
          cpu: 10m
          memory: 64Mi
        limits:
          cpu: 250m
          memory: 512Mi
      volumeMounts:
        - name: plugin-sre
          mountPath: /plugins/sre
          readOnly: true
        - name: cli-staging
          mountPath: /cli-staging
        - name: tmp
          mountPath: /tmp
  volumes:
    - name: skills-bundle
      projected:
        defaultMode: 0444
        sources:
          {{- range $index, $part := $sre.bundle.parts }}
          - configMap:
              name: {{ include "sre-assistant.skillsPartName" (dict "root" $ "index" $index) }}
              items:
                - key: {{ $part }}
                  path: {{ $part }}
          {{- end }}
    - name: cli-staging
      emptyDir: {}
    - name: proxy-auth
      secret:
        secretName: {{ include "sre-assistant.proxyAuthSecretName" . }}
        defaultMode: 0440
        items:
          - key: {{ $sre.proxy.authSecretRef.key | quote }}
            path: token
    - name: proxy-tls-ca
      secret:
        secretName: {{ include "sre-assistant.proxyTlsSecretName" . }}
        defaultMode: 0444
        items:
          - key: {{ $sre.proxy.tlsSecretRef.caKey | quote }}
            path: ca.crt
  volumeMounts:
    - name: skills-bundle
      mountPath: /skills-bundle
      readOnly: true
    - name: cli-staging
      mountPath: /cli-staging
      readOnly: true
    - name: proxy-auth
      mountPath: /proxy-auth
      readOnly: true
    - name: proxy-tls-ca
      mountPath: /proxy-tls-ca
      readOnly: true
{{- end -}}

{{- /* operatorClient.skills: Hermes skills activated for the terminal session. */ -}}
{{- define "sre-assistant.operatorClientSkills" -}}
- kubernetes-sre
{{- if .Values.global.sre.openshiftLlmDeploy.enabled }}
- openshift-llm-deploy
{{- end }}
{{- end -}}
