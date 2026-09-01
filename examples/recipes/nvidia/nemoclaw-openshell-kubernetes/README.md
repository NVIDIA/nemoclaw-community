# NemoClaw OpenShell Kubernetes

A buildless Helm recipe that runs the official NemoClaw-managed Hermes image through the official OpenShell gateway on Kubernetes or OpenShift. It does not include Hermes WebUI, SkillSpector, or NemoClaw recipe delivery.

## Pinned release inputs

- NemoClaw/Hermes managed image: NemoClaw `v0.0.117`, Hermes `0.19.0`, immutable multi-architecture index digest in `values.yaml`
- OpenShell chart and CLI: `v0.0.116`; the dependency is vendored with narrow
  OpenShift dual-CA and UID-isolation template fixes, while gateway and
  supervisor images remain official immutable multi-architecture index digests
- Helper image: immutable multi-architecture Python digest; the chart builds no proxy or bootstrap image

No Dockerfile or image build is part of installation.

Hermes `0.21.0` is the newer standalone upstream release, but the latest
published NemoClaw-managed Hermes image remains `v0.0.117` with Hermes `0.19.0`.
The chart intentionally chooses that latest compatible managed image rather
than creating an unverified custom image or substituting a generic Hermes
container that lacks the NemoClaw/OpenShell runtime contract.

## Prerequisites

- Kubernetes 1.33+ or OpenShift 4.20+ with a `ReadWriteOnce` StorageClass; set `persistence.storageClass` when the cluster has no default
- Agent Sandbox CRD/controller serving `agents.x-k8s.io/v1alpha1` or `v1beta1`
- Helm 3.14+
- A model API key in a pre-created Secret; the key must not be placed in values or Helm command history
- Admission policy that permits the OpenShell combined-supervisor Sandbox. On
  standard Kubernetes this commonly requires an operator-prepared namespace
  with an appropriate privileged Pod Security Admission or equivalent policy;
  the chart deliberately does not create or relabel namespaces.

```bash
kubectl create namespace nemoclaw-hermes
kubectl -n nemoclaw-hermes create secret generic model-api-key \
  --from-literal=api-key='<model-api-key>'
helm upgrade --install nemoclaw-hermes . \
  --namespace nemoclaw-hermes \
  --set agent.model.name='<model-name>' \
  --set agent.model.baseUrl='https://model-endpoint.example/v1' \
  --wait --timeout 20m
```

The bootstrap Job registers the credential with OpenShell, configures `inference.local`, and asks OpenShell to create the Sandbox. The real key remains in the Kubernetes Secret/OpenShell credential path; Hermes receives only the managed inference sentinel.

HTTPS model endpoints are required by default. A plain HTTP endpoint is accepted
only when `agent.model.allowInsecureHttp=true` and
`agent.model.insecureHttpAcknowledgement=I_ACKNOWLEDGE_PLAINTEXT_MODEL_CREDENTIALS`;
that mode can expose the model credential on the network.

## Platform selection

Kubernetes is the default. It pins UID/GID `1000` for the gateway and chart Jobs and renders no OpenShift SCC references.

Kubernetes user namespaces remain an operator opt-in through
`openshell.server.enableUserNamespaces=true`; use it only when Kubernetes
1.33+, the container runtime, kernel, storage driver, and GPU/runtime choices
all support that mode. The portable default is `false`.

OpenShift is explicit and deterministic. The supplied profile is the atomic
platform switch: it sets `platform.openshift.enabled=true` and all required
OpenShift overrides together.

```bash
helm upgrade --install nemoclaw-hermes . \
  --namespace nemoclaw-hermes \
  -f values-openshift.yaml \
  --wait --timeout 20m
```

`values-openshift.yaml` sets `platform.openshift.enabled=true`, removes the
portable UID/GID `1000`, and explicitly acknowledges a RoleBinding from only
the generated sandbox ServiceAccount to `system:openshift:scc:privileged`. The
chart never grants `cluster-admin`. Set `createPrivilegedSccBinding=false` only
when an operator has pre-provisioned the equivalent SCC grant. Rendering fails
if the OpenShift profile is selected but `security.openshift.io/v1` is
unavailable.

The OpenShift profile keeps user namespaces disabled and uses OpenShell's SCC
range resolution instead. Combining two UID-mapping mechanisms with retained
CSI subpath mounts is rejected at render time.

For a managed OpenShift gateway, the chart deliberately uses three IDs from the
release Namespace's SCC range: range start for short-lived lifecycle/proxy
workloads, start plus one for the gateway, and start plus two for the seed Job
and Hermes Sandbox. The official NemoClaw entrypoint retains its
`RLIMIT_NPROC=512` boundary, while Linux process accounting cannot combine the
gateway's threads with Hermes under one host UID. Helm reads the range from the
pre-created Namespace's `openshift.io/sa.scc.uid-range` annotation; therefore,
create the Namespace before installation and leave both
`openshell.server.openshift.gatewayUid.value=null` and
`openshell.server.openshift.sandboxUid.value=null` for live installs. The explicit
values exist only for deterministic offline rendering and must be set together
to distinct, namespace-valid IDs. Existing-gateway mode does not inject a local
UID into the external gateway's driver configuration. Kubernetes keeps UID/GID
`1000` and performs no OpenShift lookup. The OpenShift seed Job leaves
`fsGroup` unset so `restricted-v2` can inject the namespace-approved volume
group; its explicit `runAsUser` and `runAsGroup` remain start plus two.

The OpenShell supervisor changes the immutable image's `/sandbox` ownership to
that injected UID but preserves its set-id mode bits. Before starting Hermes,
the chart's fixed command refuses symbolic-link replacements, normalizes
`/sandbox` to `0770` and `/sandbox/.hermes` to `0700`, then uses `exec` to make
the official `/usr/local/bin/nemoclaw-start` the supervisor's direct child.
This is a runtime compatibility step only; it does not build or replace the
official image and does not weaken NemoClaw's own startup attestation.

The profile does not expose the OpenShell gateway with an OpenShift Route: the
bootstrap path is cluster-internal and mTLS-protected. Operators can configure
the upstream chart's Route separately only when external gateway access is
required and the certificate SANs have been prepared.

The chart does not auto-detect OpenShift: an auto-detected render can differ between CI, GitOps, and the target cluster.

`persistence.storageClass` is also the default for the chart-owned OpenShell
SQLite claim and `openshell.server.workspaceStorageClass` should be set to the
same or another RWO class for Sandbox workspaces when the cluster has no default
StorageClass. `gatewayPersistence.storageClass` can override only the gateway
database claim. The pre-created claim uses the exact name expected by the
upstream StatefulSet and is retained by default.

## Existing OpenShell gateway

Use `values-existing-gateway.yaml`, set the real HTTPS endpoint/name, and pre-create the referenced client mTLS Secret (`ca.crt`, `tls.crt`, `tls.key`) in the release namespace. Managed and existing modes are mutually exclusive. The default sandbox and model-provider names include a namespace/release identity hash so multiple namespaces can safely share one gateway. Any explicit `agent.sandbox.name` or `agent.model.providerName` override must remain globally unique within that gateway; bootstrap verifies sandbox ownership before mutating provider configuration.

## Optional SRE skill

The default has no SRE skill, Kubernetes API proxy, or SRE RBAC. Enable the safe profile with `-f values-sre-safe.yaml`.

Enabled chart-managed skills and the proxy credential are mounted as narrow,
read-only subpaths below the official image's existing `.hermes` directory. The
chart never replaces that protected directory or its NemoClaw configuration.

Safe mode can read common non-secret cluster resources and patch/update only
the `/scale` subresource of Deployments and StatefulSets. It cannot replace pod
templates, read Secrets, mutate RBAC, exec/attach, or delete. Hermes
authenticates to a dedicated chart proxy with a random chart-managed bearer
token stored in retained state; the SRE proxy's Kubernetes ServiceAccount token
is mounted only in the proxy pod. The OpenShell supervisor separately uses its
own short-lived projected identity token for gateway authentication. Set
`sre.proxy.authSecretRef.name` to use an operator-provided Secret instead.

`sre.rbac.mode=broad-no-delete` is a high-risk opt-in and requires `I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE`. It grants create/update/patch across API resources but still excludes all direct delete verbs and proxy DELETE requests. This mode can cause outages or indirect privilege escalation even without DELETE; it is not recommended for production.

Namespace-scoped model deletion is a separate opt-in under
`sre.openshiftLlmDeploy.deletion`. It requires an exact namespace,
`I_ACKNOWLEDGE_NAMESPACE_MODEL_DELETE`, and at least one exact
`apiGroup`/plural `resource`/`name` tuple in `allowedResources`. Every delete
RBAC rule uses Kubernetes `resourceNames`; namespace scope or skill prose is
never treated as ownership. PVCs and Secrets additionally require their
separate flags, and Secret contents are not granted read access. No
cluster-scoped delete is granted.

```yaml
sre:
  enabled: true
  openshiftLlmDeploy:
    enabled: true
    deletion:
      enabled: true
      namespace: models-eval
      dangerousAcknowledgement: I_ACKNOWLEDGE_NAMESPACE_MODEL_DELETE
      allowedResources:
        - apiGroup: serving.kserve.io
          resource: inferenceservices
          name: my-model
```

## Lifecycle and verification

The Hermes state PVC is retained by default. A sandbox created through the
OpenShell API is intentionally not a Helm-owned manifest, so `helm uninstall`
does not delete it. The chart labels the Sandbox with a digest of its effective
policy, driver configuration, model settings, environment, resources, and SRE
mode. An upgrade fails closed when an existing Sandbox has a different image or
configuration identity; inspect persisted state and explicitly recreate that
Sandbox through OpenShell before retrying.

Offline checks:

```bash
helm lint . --set openshell.agentSandbox.preflight.enabled=false
helm lint . -f values-openshift.yaml \
  --set platform.openshift.verifyApi=false \
  --set openshell.server.openshift.gatewayUid.value=1001200001 \
  --set openshell.server.openshift.sandboxUid.value=1001200002 \
  --set openshell.agentSandbox.preflight.enabled=false
python3 -m unittest tests/test_chart.py
helm template test . --api-versions agents.x-k8s.io/v1alpha1 >/tmp/rendered.yaml
helm template test . -f values-openshift.yaml \
  --set openshell.server.openshift.gatewayUid.value=1001200001 \
  --set openshell.server.openshift.sandboxUid.value=1001200002 \
  --api-versions agents.x-k8s.io/v1alpha1 \
  --api-versions security.openshift.io/v1 >/tmp/rendered-openshift.yaml
```
