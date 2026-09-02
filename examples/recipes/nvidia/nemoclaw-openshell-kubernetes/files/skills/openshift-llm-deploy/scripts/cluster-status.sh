#!/bin/sh
# Read-only model and capacity inventory for the cluster hosting Hermes.
set -eu

# Hermes tool executions do not inherit the container's chart PATH.
export PATH="/chart-bin:/toolbox:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

usage() {
  cat >&2 <<'EOF'
usage: cluster-status.sh [--namespace NAME]
EOF
  exit 64
}

namespace=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --namespace) namespace=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done

workdir=$(mktemp -d "${TMPDIR:-/tmp}/hermes-cluster-status.XXXXXX") || exit 1
trap 'rm -rf "$workdir"' EXIT HUP INT TERM

oc get nodes -o json >"$workdir/nodes.json"
oc get pods -A -o json >"$workdir/pods.json"
oc get deployments -A -o json >"$workdir/deployments.json"
oc get services -A -o json >"$workdir/services.json"
oc get routes -A -o json >"$workdir/routes.json" 2>/dev/null || printf '{"items": []}\n' >"$workdir/routes.json"
oc get dynamographdeployments.nvidia.com -A -o json >"$workdir/dgd.json" 2>/dev/null || printf '{"items": []}\n' >"$workdir/dgd.json"

python3 - "$workdir/nodes.json" "$workdir/pods.json" "$workdir/deployments.json" "$workdir/services.json" "$workdir/routes.json" "$workdir/dgd.json" "$namespace" <<'PY'
import json
import sys

nodes, pods, deployments, services, routes, dgds = [json.load(open(path, encoding="utf-8")).get("items", []) for path in sys.argv[1:7]]
namespace = sys.argv[7]

def quantity(value):
    if value is None or value == "":
        return 0.0
    text = str(value)
    factors = {"m": 0.001, "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4}
    for suffix, factor in factors.items():
        if text.endswith(suffix):
            try:
                return float(text[:-len(suffix)]) * factor
            except ValueError:
                return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0

def pod_gpu_request(pod):
    spec = pod.get("spec", {}) or {}
    regular = sum(quantity((container.get("resources", {}).get("requests", {}) or {}).get("nvidia.com/gpu")) for container in spec.get("containers", []))
    init = max([quantity((container.get("resources", {}).get("requests", {}) or {}).get("nvidia.com/gpu")) for container in spec.get("initContainers", [])] or [0])
    return max(regular, init)

def model_hint(pod):
    for container in (pod.get("spec", {}) or {}).get("containers", []):
        args = container.get("args", []) or []
        for flag in ("--served-model-name", "--model", "--model-path"):
            if flag in args:
                index = args.index(flag)
                if index + 1 < len(args):
                    return str(args[index + 1])
        for env in container.get("env", []) or []:
            if env.get("name") in {"SERVED_MODEL_NAME", "MODEL_ID", "MODEL_NAME", "MODEL_PATH"} and env.get("value"):
                return str(env["value"])
    return ""

def model_server_candidate(pod):
    metadata = pod.get("metadata", {}) or {}
    labels = metadata.get("labels", {}) or {}
    images = [container.get("image", "") for container in (pod.get("spec", {}) or {}).get("containers", [])]
    haystack = " ".join([metadata.get("name", ""), *images, *[str(value) for value in labels.values()]]).lower()
    return any(token in haystack for token in ("vllm", "dynamo", "tensorrtllm", "triton", "nim", "inference", "model", "nemotron", "glm", "llm", "sglang", "deepseek", "qwen", "kimi", "minimax", "embed"))

def modelish(value):
    text = str(value or "").lower()
    return any(token in text for token in ("vllm", "dynamo", "tensorrtllm", "triton", "nim", "nemotron", "glm", "llm", "litellm", "sglang", "deepseek", "qwen", "kimi", "minimax", "llama", "mistral", "gemma", "granite", "phi", "embed", "whisper"))

def labels_match(selector, labels):
    return bool(selector) and all(labels.get(key) == value for key, value in selector.items())

requests = {}
gpu_pods = []
for pod in pods:
    phase = (pod.get("status", {}) or {}).get("phase", "")
    node = (pod.get("spec", {}) or {}).get("nodeName", "")
    gpu = pod_gpu_request(pod)
    if node and phase not in {"Succeeded", "Failed"} and gpu:
        requests[node] = requests.get(node, 0) + gpu
        gpu_pods.append(
            {
                "node": node,
                "namespace": pod.get("metadata", {}).get("namespace", ""),
                "name": pod.get("metadata", {}).get("name", ""),
                "gpu": gpu,
                "phase": phase,
                "model": model_hint(pod),
                "candidate": model_server_candidate(pod),
            }
        )

print("STATUS_RESULT=ok")
print("GPU_CAPACITY_NOTE=FREE is allocatable GPUs minus scheduled GPU requests; it is not GPU-memory telemetry.")
print("GPU_NODES:")
print("NODE\tREADY\tGPU_CAPACITY\tGPU_ALLOCATABLE\tGPU_REQUESTED\tGPU_FREE\tCPU_ALLOCATABLE\tMEMORY_ALLOCATABLE")
gpu_node_count = 0
for node in sorted(nodes, key=lambda item: item.get("metadata", {}).get("name", "")):
    metadata = node.get("metadata", {}) or {}
    status = node.get("status", {}) or {}
    capacity = status.get("capacity", {}) or {}
    allocatable = status.get("allocatable", {}) or {}
    gpu = quantity(allocatable.get("nvidia.com/gpu"))
    if not gpu:
        continue
    gpu_node_count += 1
    ready = next((condition.get("status", "Unknown") for condition in status.get("conditions", []) if condition.get("type") == "Ready"), "Unknown")
    used = float(requests.get(metadata.get("name", ""), 0))
    free = max(gpu - used, 0.0)
    print("{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}".format(
        metadata.get("name", ""),
        ready,
        capacity.get("nvidia.com/gpu", "0"),
        allocatable.get("nvidia.com/gpu", "0"),
        int(used) if used.is_integer() else used,
        int(free) if free.is_integer() else free,
        allocatable.get("cpu", "0"),
        allocatable.get("memory", "0"),
    ))
if not gpu_node_count:
    print("No allocatable nvidia.com/gpu nodes were returned.")

print("GPU_WORKLOADS:")
print("NODE\tNAMESPACE\tPOD\tGPU_REQUEST\tPHASE")
for row in sorted(gpu_pods, key=lambda item: (item["node"], item["namespace"], item["name"])):
    gpu = int(row["gpu"]) if row["gpu"].is_integer() else row["gpu"]
    print("{}\t{}\t{}\t{}\t{}".format(row["node"], row["namespace"], row["name"], gpu, row["phase"]))

print("DEPLOYED_MODELS:")
dgd_count = 0
for dgd in sorted(dgds, key=lambda item: (item.get("metadata", {}).get("namespace", ""), item.get("metadata", {}).get("name", ""))):
    metadata = dgd.get("metadata", {}) or {}
    if namespace and metadata.get("namespace") != namespace:
        continue
    conditions = (dgd.get("status", {}) or {}).get("conditions", []) or []
    summary = ";".join("{}={}:{}".format(c.get("type", ""), c.get("status", ""), c.get("reason", "")) for c in conditions) or "status-pending"
    print("DYNAMO\t{}/{}\t{}".format(metadata.get("namespace", ""), metadata.get("name", ""), summary))
    dgd_count += 1

vllm_count = 0
for deployment in sorted(deployments, key=lambda item: (item.get("metadata", {}).get("namespace", ""), item.get("metadata", {}).get("name", ""))):
    metadata = deployment.get("metadata", {}) or {}
    labels = metadata.get("labels", {}) or {}
    if namespace and metadata.get("namespace") != namespace:
        continue
    if labels.get("app.kubernetes.io/name") != "vllm" and labels.get("app.kubernetes.io/managed-by") != "hermes":
        continue
    containers = (((deployment.get("spec", {}) or {}).get("template", {}) or {}).get("spec", {}) or {}).get("containers", [])
    args = (containers[0].get("args", []) if containers else [])
    model = "unknown"
    for index, arg in enumerate(args):
        if arg == "--model" and index + 1 < len(args):
            model = args[index + 1]
            break
    ready = "{}/{}".format((deployment.get("status", {}) or {}).get("readyReplicas", 0), (deployment.get("spec", {}) or {}).get("replicas", 0))
    print("VLLM\t{}/{}\tmodel={}\tready={}".format(metadata.get("namespace", ""), metadata.get("name", ""), model, ready))
    vllm_count += 1
if not dgd_count and not vllm_count:
    print("No direct DynamoGraphDeployment or Hermes/vLLM Deployment resources found.")

candidate_count = 0
for row in sorted(gpu_pods, key=lambda item: (item["namespace"], item["name"])):
    if namespace and row["namespace"] != namespace:
        continue
    if not row["candidate"]:
        continue
    gpu = int(row["gpu"]) if row["gpu"].is_integer() else row["gpu"]
    model = row["model"] or "not-exposed-by-pod-spec"
    print("DISCOVERED_GPU_MODEL\t{}/{}\tmodel={}\tgpus={}\tphase={}".format(row["namespace"], row["name"], model, gpu, row["phase"]))
    candidate_count += 1
if not candidate_count and not dgd_count and not vllm_count:
    print("No GPU model-server candidates were discovered from running pods.")

candidate_pods = [pod for pod in pods if pod_gpu_request(pod) and model_server_candidate(pod)]
known_model_prefixes = set()
for dgd in dgds:
    metadata = dgd.get("metadata", {}) or {}
    if metadata.get("namespace") and metadata.get("name"):
        known_model_prefixes.add((metadata["namespace"], metadata["name"]))
for deployment in deployments:
    metadata = deployment.get("metadata", {}) or {}
    labels = metadata.get("labels", {}) or {}
    if labels.get("app.kubernetes.io/name") == "vllm" or labels.get("app.kubernetes.io/managed-by") == "hermes":
        if metadata.get("namespace") and metadata.get("name"):
            known_model_prefixes.add((metadata["namespace"], metadata["name"]))

def service_is_model_server(service):
    metadata = service.get("metadata", {}) or {}
    labels = metadata.get("labels", {}) or {}
    spec = service.get("spec", {}) or {}
    haystack = " ".join([metadata.get("name", ""), *["{}={}".format(key, value) for key, value in labels.items()]])
    if modelish(haystack):
        return True
    for model_namespace, model_name in known_model_prefixes:
        if metadata.get("namespace", "") == model_namespace and (metadata.get("name", "") == model_name or metadata.get("name", "").startswith(model_name + "-")):
            return True
    selector = spec.get("selector", {}) or {}
    for pod in candidate_pods:
        pod_metadata = pod.get("metadata", {}) or {}
        if pod_metadata.get("namespace", "") != metadata.get("namespace", ""):
            continue
        if labels_match(selector, pod_metadata.get("labels", {}) or {}):
            return True
    return False

model_services = {}
for service in services:
    metadata = service.get("metadata", {}) or {}
    if service_is_model_server(service):
        model_services[(metadata.get("namespace", ""), metadata.get("name", ""))] = service

print("MODEL_ROUTES:")
print("KIND\tNAMESPACE/NAME\tBACKEND\tURL")
route_count = 0
for route in sorted(routes, key=lambda item: (item.get("metadata", {}).get("namespace", ""), item.get("metadata", {}).get("name", ""))):
    metadata = route.get("metadata", {}) or {}
    if namespace and metadata.get("namespace") != namespace:
        continue
    spec = route.get("spec", {}) or {}
    target = (spec.get("to", {}) or {}).get("name", "")
    route_labels = metadata.get("labels", {}) or {}
    route_text = " ".join([metadata.get("name", ""), target, *["{}={}".format(key, value) for key, value in route_labels.items()]])
    if not modelish(route_text) and (metadata.get("namespace", ""), target) not in model_services:
        continue
    host = spec.get("host", "")
    if not host:
        continue
    scheme = "https" if spec.get("tls") else "http"
    print("MODEL_ROUTE\t{}/{}\t{}\t{}://{}".format(metadata.get("namespace", ""), metadata.get("name", ""), target or "unknown", scheme, host))
    route_count += 1
if not route_count:
    print("No model-serving OpenShift Routes found.")

print("MODEL_NODEPORTS:")
print("KIND\tNAMESPACE/NAME\tPORTS")
node_port_count = 0
for service in sorted(services, key=lambda item: (item.get("metadata", {}).get("namespace", ""), item.get("metadata", {}).get("name", ""))):
    metadata = service.get("metadata", {}) or {}
    if namespace and metadata.get("namespace") != namespace:
        continue
    if (metadata.get("namespace", ""), metadata.get("name", "")) not in model_services:
        continue
    node_ports = []
    for port in (service.get("spec", {}) or {}).get("ports", []):
        if port.get("nodePort"):
            node_ports.append("{}:{}".format(port.get("name") or port.get("port", "port"), port["nodePort"]))
    if not node_ports:
        continue
    print("MODEL_NODEPORT\t{}/{}\t{}".format(metadata.get("namespace", ""), metadata.get("name", ""), ",".join(node_ports)))
    node_port_count += 1
if not node_port_count:
    print("No model-serving NodePort Services found.")
PY
