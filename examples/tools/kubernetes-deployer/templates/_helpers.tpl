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

{{- define "nemoclaw-openshell.nemoclawHomeClaimName" -}}
{{- printf "%s-nemoclaw-home" (include "nemoclaw-openshell.fullname" . | trunc 49 | trimSuffix "-") -}}
{{- end -}}

{{- define "nemoclaw-openshell.nemoclawHomePrepareName" -}}
{{- printf "%s-nemoclaw-home-prepare" (include "nemoclaw-openshell.fullname" . | trunc 41 | trimSuffix "-") -}}
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

{{- /*
NemoClaw access surfaces: the dashboard and OpenAI-compatible API relay.
"true" when the relay Deployment must exist for this release.
*/ -}}
{{- define "nemoclaw-openshell.accessEnabled" -}}
{{- if and .Values.access.enabled (or .Values.access.dashboard.enabled .Values.access.api.enabled) -}}true{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.accessName" -}}
{{- printf "%s-access" (include "nemoclaw-openshell.fullname" . | trunc 56 | trimSuffix "-") -}}
{{- end -}}

{{- define "nemoclaw-openshell.accessServiceAccountName" -}}
{{- include "nemoclaw-openshell.accessName" . -}}
{{- end -}}

{{- define "nemoclaw-openshell.accessSubject" -}}
{{- printf "system:serviceaccount:%s:%s" .Release.Namespace (include "nemoclaw-openshell.accessServiceAccountName" .) -}}
{{- end -}}

{{- define "nemoclaw-openshell.accessEdgeConfigName" -}}
{{- printf "%s-edge" (include "nemoclaw-openshell.accessName" .) -}}
{{- end -}}

{{- define "nemoclaw-openshell.accessExternalServiceName" -}}
{{- printf "%s-external" (include "nemoclaw-openshell.accessName" .) -}}
{{- end -}}

{{- define "nemoclaw-openshell.accessServingCertSecretName" -}}
{{- printf "%s-serving-cert" (include "nemoclaw-openshell.accessName" .) -}}
{{- end -}}

{{- define "nemoclaw-openshell.dashboardOAuthCookieSecretName" -}}
{{- default (printf "%s-dashboard-oauth-cookie" (include "nemoclaw-openshell.fullname" . | trunc 39 | trimSuffix "-")) .Values.access.exposure.route.oauthProxy.cookieSecretRef.name -}}
{{- end -}}

{{- define "nemoclaw-openshell.dashboardRouteName" -}}
{{- printf "%s-dashboard" (include "nemoclaw-openshell.fullname" . | trunc 53 | trimSuffix "-") -}}
{{- end -}}

{{- define "nemoclaw-openshell.apiRouteName" -}}
{{- printf "%s-api" (include "nemoclaw-openshell.fullname" . | trunc 59 | trimSuffix "-") -}}
{{- end -}}

{{- /* Route hosts: explicit host, else <fullname>-dashboard.<appsDomain>. */ -}}
{{- define "nemoclaw-openshell.dashboardRouteHost" -}}
{{- $route := .Values.access.exposure.route -}}
{{- if $route.dashboard.host -}}
{{- $route.dashboard.host -}}
{{- else if $route.appsDomain -}}
{{- printf "%s-dashboard.%s" (include "nemoclaw-openshell.fullname" . | trunc 52 | trimSuffix "-") $route.appsDomain -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.apiRouteHost" -}}
{{- $route := .Values.access.exposure.route -}}
{{- if $route.api.host -}}
{{- $route.api.host -}}
{{- else if $route.appsDomain -}}
{{- printf "%s-api.%s" (include "nemoclaw-openshell.fullname" . | trunc 58 | trimSuffix "-") $route.appsDomain -}}
{{- end -}}
{{- end -}}

{{- /* Browser-facing dashboard origin recorded for NemoClaw as CHAT_UI_URL. */ -}}
{{- define "nemoclaw-openshell.dashboardPublicUrl" -}}
{{- $access := .Values.access -}}
{{- if $access.dashboard.externalUrl -}}
{{- $access.dashboard.externalUrl | trimSuffix "/" -}}
{{- else if and (eq $access.exposure.type "route") $access.exposure.route.dashboard.enabled -}}
{{- with include "nemoclaw-openshell.dashboardRouteHost" . -}}https://{{ . }}{{- end -}}
{{- else if and (eq $access.exposure.type "ingress") $access.exposure.ingress.dashboard.host -}}
{{- printf "%s://%s" (ternary "https" "http" (gt (len $access.exposure.ingress.tls) 0)) $access.exposure.ingress.dashboard.host -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.apiPublicUrl" -}}
{{- $access := .Values.access -}}
{{- if and (eq $access.exposure.type "route") $access.exposure.route.api.enabled -}}
{{- with include "nemoclaw-openshell.apiRouteHost" . -}}https://{{ . }}/v1{{- end -}}
{{- else if and (eq $access.exposure.type "ingress") $access.exposure.ingress.api.host -}}
{{- printf "%s://%s/v1" (ternary "https" "http" (gt (len $access.exposure.ingress.tls) 0)) $access.exposure.ingress.api.host -}}
{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.dashboardOAuthEnabled" -}}
{{- $exposure := .Values.access.exposure -}}
{{- if and (eq $exposure.type "route") .Values.access.dashboard.enabled $exposure.route.dashboard.enabled $exposure.route.oauthProxy.enabled -}}true{{- end -}}
{{- end -}}

{{- define "nemoclaw-openshell.dashboardOAuthSubjectAccessReview" -}}
{{- $oauth := .Values.access.exposure.route.oauthProxy -}}
{{- if $oauth.subjectAccessReview -}}
{{- $oauth.subjectAccessReview -}}
{{- else -}}
{{- dict "namespace" .Release.Namespace "resource" "services" "resourceName" (include "nemoclaw-openshell.accessName" .) "verb" "get" | toJson -}}
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

{{- /*
Seed plugins declared under lifecycle.seed.plugins. The whole list is rendered
through tpl so a consuming umbrella chart can reference release facts and this
chart's own values (for example {{ .Values.artifacts.utilityImage }}) from
static values.
*/ -}}
{{- /*
Render one extension value. Structured values (maps, lists) are serialized and
rendered through tpl so string fields may reference release facts and this
chart's values. A string value is template text that must itself produce the
expected YAML shape; that form lets an umbrella chart emit conditional entries
(for example a mount that exists only when one of its own features is on).
`empty` is the YAML literal returned for nil or empty input.
*/ -}}
{{- define "nemoclaw-openshell.tplValue" -}}
{{- $rendered := "" -}}
{{- if kindIs "string" .value -}}
{{- $rendered = tpl .value .context | trim -}}
{{- else if .value -}}
{{- $rendered = tpl (toYaml .value) .context | trim -}}
{{- end -}}
{{- default .empty $rendered -}}
{{- end -}}

{{- define "nemoclaw-openshell.seedPlugins" -}}
{{- include "nemoclaw-openshell.tplValue" (dict "value" .Values.lifecycle.seed.plugins "context" . "empty" "[]") -}}
{{- end -}}

{{- define "nemoclaw-openshell.extraStateMounts" -}}
{{- include "nemoclaw-openshell.tplValue" (dict "value" .Values.agent.extraStateMounts "context" . "empty" "[]") -}}
{{- end -}}

{{- /*
Map-valued extension points keep a structured default (Helm refuses to replace
a map default with a string), so each has a *Template twin: template text that
renders to the same map shape and is merged over the structured value.
*/ -}}
{{- define "nemoclaw-openshell.agentEnvValues" -}}
{{- $structured := include "nemoclaw-openshell.tplValue" (dict "value" .Values.agent.env "context" . "empty" "{}") | fromYaml -}}
{{- $templated := include "nemoclaw-openshell.tplValue" (dict "value" .Values.agent.envTemplate "context" . "empty" "{}") | fromYaml -}}
{{- toYaml (merge (dict) $templated $structured) -}}
{{- end -}}

{{- define "nemoclaw-openshell.operatorClientSkills" -}}
{{- include "nemoclaw-openshell.tplValue" (dict "value" .Values.operatorClient.skills "context" . "empty" "[]") -}}
{{- end -}}

{{- define "nemoclaw-openshell.policyReadOnlyPaths" -}}
{{- include "nemoclaw-openshell.tplValue" (dict "value" .Values.policy.readOnlyPaths "context" . "empty" "[]") -}}
{{- end -}}

{{- define "nemoclaw-openshell.policyNetworkPolicies" -}}
{{- $structured := include "nemoclaw-openshell.tplValue" (dict "value" .Values.policy.networkPolicies "context" . "empty" "{}") | fromYaml -}}
{{- $templated := include "nemoclaw-openshell.tplValue" (dict "value" .Values.policy.networkPoliciesTemplate "context" . "empty" "{}") | fromYaml -}}
{{- range $name, $_ := $templated -}}
  {{- if hasKey $structured $name -}}
    {{- fail (printf "policy.networkPolicies.%s is declared both structurally and in policy.networkPoliciesTemplate" $name) -}}
  {{- end -}}
{{- end -}}
{{- toYaml (merge (dict) $templated $structured) -}}
{{- end -}}

{{- define "nemoclaw-openshell.seedPluginManifest" -}}
{{- $manifest := list -}}
{{- range $plugin := include "nemoclaw-openshell.seedPlugins" . | fromYamlArray -}}
  {{- $manifest = append $manifest (dict "name" $plugin.name "entrypoint" $plugin.entrypoint) -}}
{{- end -}}
{{- toJson $manifest -}}
{{- end -}}

{{- define "nemoclaw-openshell.seedPluginIdentity" -}}
{{- $identity := list -}}
{{- range $plugin := include "nemoclaw-openshell.seedPlugins" . | fromYamlArray -}}
  {{- $identity = append $identity (dict "name" $plugin.name "identity" (toString (default "" $plugin.identity))) -}}
{{- end -}}
{{- toJson $identity -}}
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

{{- /*
Sandbox policy: files/policy.yaml merged structurally with policy.readOnlyPaths
and policy.networkPolicies. Values are rendered through tpl so a consuming
umbrella chart can reference {{ .Release.Namespace }} in proxy host names.
*/ -}}
{{- define "nemoclaw-openshell.policy" -}}
{{- $policy := .Files.Get "files/policy.yaml" | fromYaml -}}
{{- $filesystem := index $policy "filesystem_policy" -}}
{{- $readOnly := list -}}
{{- range $path := (index $filesystem "read_only") -}}
  {{- $readOnly = append $readOnly $path -}}
{{- end -}}
{{- range $path := include "nemoclaw-openshell.policyReadOnlyPaths" . | fromYamlArray -}}
  {{- if not (has (toString $path) $readOnly) -}}
    {{- $readOnly = append $readOnly (toString $path) -}}
  {{- end -}}
{{- end -}}
{{- $_ := set $filesystem "read_only" $readOnly -}}
{{- $networkPolicies := index $policy "network_policies" -}}
{{- range $name, $definition := include "nemoclaw-openshell.policyNetworkPolicies" . | fromYaml -}}
  {{- if hasKey $networkPolicies $name -}}
    {{- fail (printf "policy.networkPolicies.%s collides with a base sandbox policy entry" $name) -}}
  {{- end -}}
  {{- if not (kindIs "map" $definition) -}}
    {{- fail (printf "policy.networkPolicies.%s must render to an OpenShell network policy object" $name) -}}
  {{- end -}}
  {{- if not (hasKey $definition "name") -}}
    {{- $_ := set $definition "name" $name -}}
  {{- end -}}
  {{- $_ := set $networkPolicies $name $definition -}}
{{- end -}}
{{- $_ := set $policy "network_policies" $networkPolicies -}}
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Sandbox policy for the Hermes Agent, synchronized from NemoClaw v0.0.117 and
# extended with this release's policy.readOnlyPaths and policy.networkPolicies.
{{ toYaml $policy }}
{{- end -}}
