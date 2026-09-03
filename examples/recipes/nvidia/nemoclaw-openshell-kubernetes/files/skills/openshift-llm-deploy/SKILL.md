---
name: openshift-llm-deploy
description: Use when inspecting GPU/model capacity, live GPU utilization, GPU memory, power or temperature telemetry, model serving metrics such as queue depth, KV-cache usage or request latency, Prometheus/Thanos metric queries, model Routes or NodePorts, OpenShell Sandboxes, Kata/confidential pods, Nemoclaw deployments, or deploying, verifying, inventorying, or removing a Hugging Face model on the Kubernetes or OpenShift cluster hosting this Hermes sandbox.
---

# Local Cluster LLM Deployment

Use this skill for model-serving work on the cluster that hosts this Hermes
Sandbox. `oc` and `kubectl` use a chart-generated kubeconfig that reaches
the authenticated SRE proxy. The Hermes Sandbox never receives a Kubernetes
ServiceAccount token, external login command, or user kubeconfig.

The wrappers are already installed at `/chart-bin/oc` and
`/chart-bin/kubectl` and are on `PATH`. Never download, install, or use a
package manager for Kubernetes clients. Before reporting a cluster-access
blocker, run:

```sh
/chart-bin/oc whoami
/chart-bin/oc auth can-i create deployments --all-namespaces
```

The proxy performs verified TLS to the Kubernetes API. Never add
`--insecure-skip-tls-verify`, change `KUBECONFIG`, or bypass the proxy.

This skill is intentionally conservative: it requests Hugging Face access only
through a Kubernetes Secret, validates scheduling and storage first, asks for
one explicit confirmation before cluster changes, and reports a verified Route
or NodePort endpoint after deployment.

## Guardrails

- Never ask the user to paste an HF token into normal chat, save it to a
  workspace file, place it in a ConfigMap, or include it in a command
  transcript. The agent has no Secret-read permission and must never attempt
  to inspect a credential value.
- Read `${HERMES_HOME}/skills/openshift-llm-deploy/hf-token-intake.yaml`
  before handling a Hugging Face model. This standalone chart has no WebUI
  credential intake. Use only the existing namespace-local Secret name and key
  recorded there. If the Secret does not exist, stop and give the human a
  `kubectl create secret` or `oc create secret` command to run outside the
  agent; never ask for or execute a command containing the raw token.
- Default the target namespace to the namespace returned by
  `/chart-bin/oc project -q`. It contains the chart-selected model-runner
  ServiceAccount used by the one-time downloader and standard vLLM fallback.
  Do not target another namespace: the Secret reference and runner identity
  are deliberately namespace-local and configured by Helm.
- First use Dynamo only when `DynamoGraphDeployment` is served at
  `nvidia.com/v1beta1` and the local service account can create it. Never
  install or upgrade Dynamo from this skill.
- The Dynamo vLLM runtime is the default Dynamo backend because it has the
  broadest model coverage. Select TensorRT-LLM only when the exact model has a
  known compatible upstream engine configuration and the full
  `--extra-engine-args <path>` value is available. Do not guess an engine
  configuration from a Hugging Face name or tags.
- Use the chart-rendered, version-pinned fallback images from
  `dynamo-defaults.yaml`. Do not use `latest`. The expected offline defaults
  are:

  ```text
  nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.4.1@sha256:a6bb45ad652f01d08b5a18b54b9fa9e80584ce18ee1ba1e5a760a8f228872fe5
  nvcr.io/nvidia/ai-dynamo/tensorrtllm-runtime:1.4.1@sha256:535640569a28a94a373ffb091d7bea40a84cc7d46cee56b25a487b2472e12668
  docker.io/vllm/vllm-openai:v0.27.1@sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967
  ```

- For each Dynamo deployment, run the chart-provided Dynamo resolver. It
  accepts only an exact full-image model recipe with
  `dynamoRuntimeVersionOverride`, or the latest stable `ai-dynamo/dynamo`
  GitHub release mapped to the official NVIDIA NGC vLLM/TensorRT-LLM runtime
  repository only after its Linux/amd64 index digest is verified. It never
  constructs a tag from a model name. If release metadata or the matching NGC
  artifact cannot be validated, retain the chart image and runtime-version
  defaults.
- For every direct standard-vLLM deployment and Dynamo fallback, run the
  chart-provided resolver. It reads the latest stable release from
  `api.github.com/repos/vllm-project/vllm/releases/latest`; if that shared
  unauthenticated API quota is exhausted, it follows GitHub's public
  `/vllm-project/vllm/releases/latest` redirect instead. It verifies that the
  exact `vllm/vllm-openai:<release-tag>` exists with a Linux/amd64 image index
  on Docker Hub, then pins its index digest. Do not use `latest` or construct a
  tag manually. If the release or digest cannot be validated, use the
  configured `standardVllmImage` unchanged and report `VLLM_IMAGE_REASON`.
- Use the existing `vllm-deployment.yaml` template for an explicitly requested
  direct standard-vLLM deployment, when Dynamo is unavailable, or after an
  explicit Dynamo failure. Do not silently move a pending model download to
  the standard-vLLM path.
- The standard vLLM fallback template is immutable after rendering. Its
  `VLLM_ARGS` value may contain only YAML vLLM argument-list entries. Never add
  `command:`, shell code, `set`, `pipefail`, image substitutions, offline-mode
  environment flags, or a hand-written model-download loop. The launcher
  rejects those changes before `oc apply`.
- Ask for an explicit confirmation immediately before `oc apply`, model deletion,
  or namespace creation. The confirmation must cover the Dynamo attempt and,
  when selected, automatic cleanup of the failed DGD followed by a standard
  vLLM fallback while retaining the model-cache PVC.
- Do not deploy a model during chart installation. This skill runs only in
  response to a user request.
- Never report a generic terminal failure for a model deployment. Run the
  bounded diagnostic helper and report its `DIAGNOSIS_CAUSE`, affected
  resource, and `DIAGNOSIS_ACTION`. The launcher performs at most one safe
  retry for a transient Kubernetes API apply error. Do not repeat an apply
  after a manifest, scheduling, storage, image-pull, or runtime failure until
  the reported cause has changed.
- Never select DCGM GPU metrics by `namespace`, `pod`, or `container`. Those
  labels identify the DCGM exporter's own pod, so such a query returns an empty
  result and looks like "no GPUs in use". The GPU consumer is identified by
  `exported_namespace`, `exported_pod`, and `exported_container`. For the same
  reason the namespace-scoped Thanos tenancy port cannot serve GPU metrics.
- Never present scheduled GPU requests as utilization, or utilization as
  capacity. `cluster-status.sh` answers "what is reserved"; `gpu-metrics.sh`
  answers "what is actually being used". State which one a number came from.

## Status-Only Workflow

When the user asks only for deployed models, model Routes or NodePorts, cluster
status, GPU availability, node capacity, workload placement, **what agents are
running, list agents, agent inventory, agent status, OpenShell Sandboxes**,
Kata/confidential pods, or Nemoclaw deployments, this skill is mandatory. As the
first action, load this skill and execute the following command before answering.
Make no cluster changes and do not ask for an HF token or deployment confirmation:

```sh
SKILL_ROOT="${HERMES_HOME}/skills/openshift-llm-deploy"
"$SKILL_ROOT/scripts/cluster-status.sh"
```

Use `--namespace "$NAMESPACE"` only when the user explicitly asks to narrow
the inventory to one namespace. The default command queries every namespace.
Report the `GPU_NODES` and `GPU_WORKLOADS` tables as scheduled **GPU request**
capacity, not GPU-memory telemetry. The inventory covers direct
DynamoGraphDeployments and vLLM/Hermes Deployments, then reports GPU model-server
candidates discovered from running pods and a model argument or environment hint
when the pod exposes one. It also reports only model-serving `MODEL_ROUTE` and
`MODEL_NODEPORT` exposure; do not present the Hermes WebUI Route as a model
endpoint. Additionally, the output includes `SANDBOXES` (namespace, name, phase,
runtime class, uptime), `KATA_PODS` (namespace, name, runtime class, phase, node,
uptime), and `NEMOCLAW` (namespace, name, ready/replicas, uptime) tables for
Agent Sandbox, Kata confidential-container, and Nemoclaw/Hermes deployment
inventory. Do not claim a model is healthy from this status view alone; health
is verified only through the endpoint workflow below.

## Metrics Workflow

When the user asks how *busy* a GPU, pod, model, or namespace is — utilization,
GPU memory in use, power draw, temperature, queue depth, KV-cache usage, or
request latency — answer from the cluster's built-in monitoring stack, not from
`cluster-status.sh`. Those are different questions: `cluster-status.sh` reports
**scheduled GPU requests** (what a pod reserved), while this workflow reports
**measured telemetry** (what it is actually using). A pod can hold 8 GPUs at 0%
utilization; only this view distinguishes the two.

```sh
SKILL_ROOT="${HERMES_HOME}/skills/openshift-llm-deploy"
"$SKILL_ROOT/scripts/gpu-metrics.sh" --namespace "$NAMESPACE"
```

Use `--all-namespaces` for a cluster-wide view and `--pod-prefix` to narrow to
one model. The output has three tables: per-GPU telemetry, a per-pod rollup, and
a serving-side table when Dynamo metrics are being scraped.

For any other metric, run a PromQL query directly and consolidate the JSON
yourself:

```sh
"$SKILL_ROOT/scripts/query-metrics.sh" --query 'PROMQL'
```

Both scripts call the chart's exact-target metrics proxy using only a direct
Prometheus query path. The proxy owns the fixed Thanos/Prometheus Service
identity; the scripts do not open a port-forward, accept a monitoring token,
query the monitoring Route, or disable certificate verification.

Read `references/metrics.md` for the PromQL recipe table and label reference
before composing a non-obvious query.

### Enabling serving metrics

DCGM GPU telemetry works with no setup. Dynamo serving metrics (queue depth,
KV-cache usage, time-to-first-token, tokens/sec) are only collected once a
PodMonitor exists in the model namespace. If the serving table reports that
nothing is being scraped, offer to apply it:

```sh
python3 "$SKILL_ROOT/scripts/render-template.py" \
  --template "$SKILL_ROOT/templates/dynamo-podmonitor.yaml" \
  --output "$WORKDIR/podmonitor.yaml" \
  --set NAMESPACE="$NAMESPACE"
oc apply -f "$WORKDIR/podmonitor.yaml"
```

Scraped series take one to two scrape intervals (30s each) to appear. This
requires user-workload monitoring, which is a cluster-level setting; if the
PodMonitor is accepted but no series appear, report that
`enableUserWorkload: true` may be missing rather than retrying in a loop.

## Dynamo-First Deploy Workflow

Use the assets below; they avoid long, repetitive tool loops:

```text
${HERMES_HOME}/skills/openshift-llm-deploy/dynamo-defaults.yaml
${HERMES_HOME}/skills/openshift-llm-deploy/templates/dynamo-vllm-graph-deployment.yaml
${HERMES_HOME}/skills/openshift-llm-deploy/templates/dynamo-tensorrtllm-graph-deployment.yaml
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/render-template.py
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/list-storage-classes.sh
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/dynamo-first-deploy.sh
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/resolve-vllm-image.sh
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/resolve-dynamo-image.sh
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/classify-dynamo-failure.py
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/deploy-model.sh
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/diagnose-deployment.sh
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/verify-openai-endpoint.sh
${HERMES_HOME}/skills/openshift-llm-deploy/scripts/remove-model.sh
```

### 1. Establish the target and Dynamo capability

```sh
NAMESPACE=$(/chart-bin/oc project -q)
SKILL_ROOT="${HERMES_HOME}/skills/openshift-llm-deploy"
OBSERVATION_TIMEOUT_SECONDS=$(awk -F ': ' '/^observationTimeoutSeconds:/ {print $2; exit}' "$SKILL_ROOT/dynamo-defaults.yaml")
VERIFICATION_TIMEOUT_SECONDS=$(awk -F ': ' '/^verificationTimeoutSeconds:/ {print $2; exit}' "$SKILL_ROOT/dynamo-defaults.yaml")
/chart-bin/oc api-resources --api-group=nvidia.com -o wide
/chart-bin/oc auth can-i create dynamographdeployments.nvidia.com -n "$NAMESPACE"
"$SKILL_ROOT/scripts/check-gpus.sh"
"$SKILL_ROOT/scripts/list-storage-classes.sh"
```

Treat Dynamo as available only when the API discovery output shows
`dynamographdeployments` with API version `v1beta1` and `can-i` returns `yes`.
If either check fails, state that Dynamo cannot be used on this cluster and
prepare the standard vLLM path instead. Do not attempt a legacy v1alpha1 DGD:
its schema differs from these templates.

Select one GPU node with enough allocatable GPUs and keep both the Dynamo
frontend and worker on that node. This avoids an RWO model-cache PVC attaching
to different nodes. Do not guess a storage class or a node name.

Set `STORAGE_CLASS` only from the inventory helper output. It returns every
class as `STORAGE_CLASS_OPTION`, marks the cluster default with
`DEFAULT=true`, and reports it separately as `STORAGE_CLASS_DEFAULT`.

When `STORAGE_CLASS_COUNT` is greater than one, do not select a class
automatically. Ask the user which listed storage class to use before showing a
deployment plan or asking for deployment confirmation. Present the reported
cluster default as the first option, explicitly labeled **cluster default**.
If there is exactly one reported default, the user may reply `default`; resolve
that reply to its class name and still pass the class explicitly to the
wrapper. If the inventory reports no default or multiple defaults, state that
clearly and require a class-name choice. Do not treat a past deployment's class
or a general storage recommendation as the user's choice.

When exactly one storage class exists, select that class and state it in the
plan. Always pass the chosen class explicitly; never omit
`--storage-class` and rely on implicit provisioning.

After the user chooses a class, validate it against the chosen node. For
example, `lvms-nvme` uses the `topolvm.io` node-local provisioner and
`WaitForFirstConsumer`, so it requires enough advertised
`CSIStorageCapacity` for the requested PVC size. A class with RWX semantics
must be chosen only when the workload needs shared filesystem access.

Before asking for deployment confirmation, inspect the proposed GPU node and
storage placement:

```sh
/chart-bin/oc get node "$NODE_NAME" \
  -o jsonpath='{range .spec.taints[*]}{.key}{"="}{.value}{":"}{.effect}{"\n"}{end}'
/chart-bin/oc get csistoragecapacity -A \
  -o custom-columns=NAMESPACE:.metadata.namespace,SC:.storageClassName,CAPACITY:.capacity,NODE:.nodeTopology.matchLabels.topology\.topolvm\.io/node
```

Never schedule model workloads on a node tainted
`node.ocs.openshift.io/storage=true:NoSchedule`; this chart deliberately does
not add that toleration. If the chosen node-local class has no capacity object
for the selected node, return to storage-class and node selection rather than
substituting another class without the user's approval. The deployment wrapper
enforces these checks again before it creates a PVC or downloader Job.

### 2. Secure Hugging Face access, inspect the model, and choose a backend

If the secure-token gate is enabled, complete it first. Then inspect permitted
Hugging Face metadata, model configuration, checkpoint size,
precision, and minimum GPU count. Explain the selected node, GPU count, PVC
size, expected context window, runtime image, and exposure before applying.

Use this selection order:

1. If the user explicitly requests a non-Dynamo or direct vLLM deployment,
   choose `standard-vllm`. The wrapper resolves the latest stable GitHub vLLM
   release and uses `docker.io/vllm/vllm-openai:<release-tag>` only if Docker
   Hub confirms that exact tag. Otherwise it uses the chart default and emits
   the fallback reason.
2. If Dynamo is available and the model has no known TensorRT-LLM engine
   configuration, choose the Dynamo vLLM template. Resolve an exact
   `modelRuntimeOverrides.<model-id>.dynamoVllmRuntimeImage` plus
   `dynamoRuntimeVersionOverride` first, then resolve the latest stable official
   Dynamo vLLM runtime, and finally retain the chart defaults if metadata is
   unavailable.
3. Choose the Dynamo TensorRT-LLM template only when an upstream, matching
   `--extra-engine-args` path is known. That path must be present in the exact
   override or default `tensorrtllmRuntimeImage`. Include it exactly as
   `TRTLLM_ENGINE_ARGS`.
4. Automatically use standard vLLM only when the Dynamo CRD is unavailable or
   DGD/runtime evidence proves a model/backend incompatibility. Registry,
   credentials, RBAC, storage, scheduling, generic crashes, and endpoint or
   transport failures are terminal diagnoses without automatic fallback. A
   `pending` result means the model is still downloading or initializing.

Read `dynamo-defaults.yaml` for the chart-selected runtime images, Dynamo
runtime compatibility versions, standard-vLLM default, and observation
timeout. Do not replace these defaults with `latest`. The resolvers may replace
them only with validated stable upstream releases. A model-specific Dynamo
image may be selected only as an exact full-image override paired with
`dynamoRuntimeVersionOverride`; this is required for digest/custom-tag images
on Dynamo 1.4+. If an image pull
credential is required, ask for the name of an existing namespace-local
image-pull Secret, not its value. Do not create registry credentials in chat
or a workspace file.
Render `DYNAMO_IMAGE_PULL_SECRETS` as `[]` when no pull Secret is required, or
as `[ {"name": "<existing-pull-secret>"} ]` when one is approved.

On OpenShift, Dynamo may require the generated
`${RELEASE}-k8s-service-discovery` ServiceAccount to use the `anyuid` SCC.
The SRE proxy intentionally lacks `bind` and `use`, so it cannot grant that
privilege. If admission reports this requirement, stop and provide this
human-run command:

```sh
oc adm policy add-scc-to-user anyuid -z "${RELEASE}-k8s-service-discovery" -n "$NAMESPACE"
```

Do not run that `oc adm` command through the agent. After the operator applies
it, ask for confirmation before retrying the deployment once.

### 3. Download once from the existing Secret reference

The wrapper renders a node-pinned model-download Job that is the **only**
model-serving workload with an `HF_TOKEN` Secret reference. It writes the
checkpoint under `/models/model` on the release PVC. The serving manifests
receive only `/models/model`, never an HF token or Secret reference.

The Secret is externally managed and is not deleted or read by Hermes. If the
Job is still running when the bounded observation window ends, report it as
pending and do not start a serving workload. Never use `oc get secret`,
`oc extract`, `--from-literal`, or `envFrom` for credentials.

### 4. Use the chart-managed deployment wrapper

Do not construct YAML, invoke `render-template.py`, or call `oc apply` from
the model run. `deploy-model.sh` does all rendering, validation, immutable
image selection, secure Secret reference construction, SCC handling, endpoint
verification, and cleanup from its fixed implementation. It is the only
allowed deploy command.

The wrapper defaults to Dynamo vLLM. Use `--deployment-mode standard-vllm` for
an explicit direct standard-vLLM request; otherwise use
`--deployment-mode dynamo`. It uses a model-specific Dynamo runtime override
from `dynamo-defaults.yaml` when present. Select `--dynamo-backend trtllm`
only with a known `--trtllm-engine-args` value. A conservative default
`--max-model-len` is `32768`.

The chart's Dynamo frontend receives only the served model name. Both Dynamo
workers and standard vLLM use the local `/models/model` path only after the
isolated authenticated download has completed.

### 5. Confirm one controlled deployment attempt

Before changing the cluster, show a concise summary that includes:

- target namespace and selected node;
- user-selected storage class (and whether it was the cluster-default option)
  and, for node-local storage, the verified
  `CSIStorageCapacity` on that node;
- deployment mode, Dynamo backend when applicable, and the exact selected
  standard-vLLM image plus `VLLM_IMAGE_SOURCE`/`VLLM_RELEASE_TAG` or
  `VLLM_IMAGE_REASON`;
- GPU, memory, cache-PVC, and context-window values;
- whether a gated-model Secret is referenced by name;
- whether an external Route/NodePort will be created; and
- that a proven Dynamo model/runtime incompatibility can fall back only when
  the separate model-delete proxy authorizes that exact DGD name; otherwise it
  stops for human cleanup. The PVC is retained, and infrastructure or endpoint
  failures are reported without backend replacement.

Require confirmation. On confirmation, run this wrapper exactly once. Add
`--expose` only when the user approved an external endpoint:

```sh
sh "$SKILL_ROOT/scripts/deploy-model.sh" \
  --namespace "$NAMESPACE" \
  --release "$RELEASE" \
  --model "$MODEL_ID" \
  --platform "$PLATFORM" \
  --node "$NODE_NAME" \
  --gpus "$GPU_COUNT" \
  --storage-class "$STORAGE_CLASS" \
  --pvc-size "$PVC_SIZE" \
  --memory-request "$MEMORY_REQUEST" \
  --memory-limit "$MEMORY_LIMIT" \
  --hf-secret "$HF_SECRET_NAME" \
  --max-model-len "$MAX_MODEL_LEN" \
  --deployment-mode "$DEPLOYMENT_MODE" \
  --allow-fallback \
  --expose
```

Never call `./scripts/deploy.sh`, `/scripts/deploy.sh`, a guessed wrapper
path, `render-template.py`, `dynamo-first-deploy.sh`, or `oc apply` after this
command. If the output lacks `DEPLOYMENT_RESULT`, run exactly one read-only
diagnosis:

```sh
sh "$SKILL_ROOT/scripts/diagnose-deployment.sh" \
  --namespace "$NAMESPACE" --release "$RELEASE"
```

Then report the diagnosis and stop. Do not retry or claim deployment progress.

The launcher deliberately observes for a short, chart-configured period so a
large model download cannot exhaust the terminal tool budget. It reports one
of these markers:

```text
DYNAMO_RESULT=ready
DYNAMO_RESULT=pending
DYNAMO_RESULT=failed
FALLBACK_RESULT=ready
FALLBACK_RESULT=pending
FALLBACK_RESULT=failed
STANDARD_VLLM_RESULT=ready|pending|failed
VLLM_IMAGE=docker.io/vllm/vllm-openai:<release-tag>@sha256:<digest>|<model-override>|<chart-default>
VLLM_IMAGE_SOURCE=model-override|github-latest-release|chart-default
VLLM_IMAGE_REASON=...
DYNAMO_IMAGE=nvcr.io/nvidia/ai-dynamo/<backend>-runtime:<version>@sha256:<digest>|<model-override>|<chart-default>
DYNAMO_RUNTIME_VERSION=X.Y.Z
DYNAMO_IMAGE_SOURCE=model-override|github-latest-release|chart-default
DYNAMO_IMAGE_REASON=...
DEPLOYMENT_RETRY=one-safe-api-retry-after-transient-apply-error
DIAGNOSIS_CAUSE=...
DIAGNOSIS_ACTION=...
VERIFY_SIMPLE_COMPLETION=passed
VERIFY_TOOL_CALL=passed|not-observed|not-supported-or-rejected
ENDPOINT=https://...
SERVICE_ENDPOINT=http://...svc.cluster.local:8000
DEPLOYMENT_PHASE=...
DEPLOYMENT_OBSERVATION=...
MODEL_DOWNLOAD_RESULT=ready|pending|failed
HF_TOKEN_SECRET=external-reference-not-read-or-deleted
DEPLOYMENT_RESULT=ready|pending|failed
```

If it returns `pending`, report the live resource names and continue with a
single later status observation. Do not create a second DGD, deploy vLLM, or
claim that Dynamo failed merely because it was not immediately ready.
If `DYNAMO_RESULT=failed`, `FALLBACK_RESULT=failed`, or
`STANDARD_VLLM_RESULT=failed`, report the bounded diagnosis before proposing
another change. A Dynamo request automatically applies standard vLLM only
after an unavailable Dynamo CRD or a proven model/runtime incompatibility. It
is never used to hide RBAC, manifest, storage, scheduling, registry, generic
crash, endpoint, or transport errors.

## Interactive Deployment Result Contract

Do not narrate internal edits, claim background progress, or issue extra
`oc apply`/patch commands after confirmation. `deploy-model.sh` is the only
deployment command. It emits bounded phase and observation markers while it
works, then returns exactly one final `DEPLOYMENT_RESULT`.

Translate that result into one clear response:

- **Ready:** backend, selected node, verified completion/tool-call outcome, and
  Route or NodePort URL.
- **Pending:** current resource observation, why it is pending, and one later
  read-only status check. Do not redeploy.
- **Failed:** backend, affected resource, `DIAGNOSIS_CAUSE`, and
  `DIAGNOSIS_ACTION`. Do not attempt a new manifest or runtime image without a
  new user confirmation.

### 6. Verify and report the endpoint

The launcher uses the Kubernetes API's namespace-scoped Service proxy only for
the selected model service and waits up to the configured verification window
after readiness. It checks `/health`, `/v1/models`, an
OpenAI-compatible sample completion, and a forced tool-call request before it
emits `DYNAMO_RESULT=ready`, `FALLBACK_RESULT=ready`, or
`STANDARD_VLLM_RESULT=ready`. A model may not support
tool calling; report `VERIFY_TOOL_CALL=not-observed` or
`VERIFY_TOOL_CALL=not-supported-or-rejected` without calling an otherwise
healthy endpoint failed. On OpenShift, report the live Route in
`ENDPOINT`. On Kubernetes, report the NodePort only after the service patch and
a schedulable node address are both present. Include the selected backend,
advertised model ID, completion result, tool-call result, and endpoint in the
final report.

## Remove Workflow

For delete or uninstall requests, inventory both possible serving paths before
asking for confirmation:

```sh
SKILL_ROOT="${HERMES_HOME}/skills/openshift-llm-deploy"
"$SKILL_ROOT/scripts/remove-model.sh" \
  --namespace "$NAMESPACE" \
  --release "$RELEASE" \
  --platform "$PLATFORM" \
  --action inventory
```

State exactly what the inventory found. Deletion is possible only when Helm
enabled the separate namespace-scoped model-delete proxy and the operator
listed each exact API-group/resource/name tuple in
`deletion.allowedResources`. Label-selector collection deletion is forbidden.
The external HF token Secret is never read, recreated, or removed.

Require a final confirmation. For cache removal, require a separate explicit
confirmation that the model weights may be permanently removed. Then execute:

```sh
"$SKILL_ROOT/scripts/remove-model.sh" \
  --namespace "$NAMESPACE" \
  --release "$RELEASE" \
  --platform "$PLATFORM" \
  --action delete \
  --confirm
```

Add `--purge-storage` only after the user explicitly approved PVC deletion.
Report `REMOVE_RESULT`, `REMOVE_STORAGE`, and
`REMOVE_HF_TOKEN_SECRET=external-reference-not-read-or-deleted`.
Never remove an entire namespace unless the user explicitly confirms namespace
deletion.
