#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Shared helpers for nemoclaw-gpu Kubernetes HPA scripts

hpa_common_log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# Print the effective inference Secret name and key as a tab-separated pair.
# Reading Helm's computed values keeps operational scripts aligned with either
# the chart-generated Secret or an operator-managed Secret configured in values.
hpa_common_inference_secret_contract() {
  local ns="${1:?namespace}"
  local release="${2:?release}"
  local default_name="${3:?defaultSecretName}"

  helm get values "${release}" -n "${ns}" --all -o json | python3 -c '
import json
import sys

values = json.load(sys.stdin)
auth = ((values.get("inference") or {}).get("auth") or {})
name = auth.get("existingSecret") or sys.argv[1]
key = auth.get("key") or ""
print(f"{name}\t{key}")
' "${default_name}"
}

# Kubernetes custom metrics use Quantity milli-units (33500m = 33.5). Format as plain % for scripts.
# Style: script (GPU UTIL % column + subtitle) | kubectl (matches kubectl get hpa TARGETS column).
hpa_common_format_hpa() {
  local ns="${1:?namespace}"
  local headers="${2:-1}"
  local style="${3:-script}"
  python3 - "${ns}" "${headers}" "${style}" <<'PY'
import json, subprocess, sys
from datetime import datetime, timezone

ns, headers = sys.argv[1], sys.argv[2] == "1"
style = sys.argv[3] if len(sys.argv) > 3 else "script"

def qty(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s == "<unknown>":
        return None
    if s.endswith("m"):
        return float(s[:-1]) / 1000.0
    return float(s)

def fmt_pct(n):
    if n is None:
        return "<unknown>"
    if abs(n - round(n)) < 1e-6:
        return f"{int(round(n))}%"
    s = f"{n:.2f}".rstrip("0").rstrip(".")
    return f"{s}%"

def age(ts):
    if not ts:
        return "?"
    created = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    secs = int((datetime.now(timezone.utc) - created).total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"

def targets(h):
    spec_metrics = h.get("spec", {}).get("metrics") or []
    current = h.get("status", {}).get("currentMetrics") or []
    parts = []
    for i, sm in enumerate(spec_metrics):
        mtype = sm.get("type")
        cm = current[i] if i < len(current) else {}
        if mtype == "Pods":
            name = sm["pods"]["metric"]["name"]
            target = sm["pods"]["target"]
            tgt_raw = target.get("averageValue") or target.get("value")
            cur_raw = (cm.get("pods") or {}).get("current", {})
            cur_raw = cur_raw.get("averageValue") or cur_raw.get("value")
            if name == "gpu_utilization_percent":
                parts.append(f"{fmt_pct(qty(cur_raw))}/{fmt_pct(qty(tgt_raw))}")
            else:
                cur_v = qty(cur_raw)
                tgt_v = qty(tgt_raw)
                cur_s = "?" if cur_v is None else f"{cur_v:g}"
                tgt_s = "?" if tgt_v is None else f"{tgt_v:g}"
                parts.append(f"{cur_s}/{tgt_s}")
    return " ".join(parts) if parts else "<unknown>"

def print_row(h):
    meta = h["metadata"]
    spec = h["spec"]
    status = h.get("status") or {}
    ref = spec["scaleTargetRef"]
    ref_str = f"{ref['kind']}/{ref['name']}"
    tgt = targets(h)
    if style == "kubectl":
        print(
            f"{meta['name']:<20} "
            f"{ref_str:<31} "
            f"{tgt:<11} "
            f"{spec.get('minReplicas', ''):<9} "
            f"{spec.get('maxReplicas', ''):<9} "
            f"{status.get('currentReplicas', ''):<10} "
            f"{age(meta.get('creationTimestamp'))}"
        )
    else:
        print(
            f"{meta['name']:<22} "
            f"{ref_str:<31} "
            f"{tgt:<18} "
            f"{spec.get('minReplicas', ''):<8} "
            f"{spec.get('maxReplicas', ''):<8} "
            f"{status.get('currentReplicas', ''):<10} "
            f"{age(meta.get('creationTimestamp'))}"
        )

try:
    raw = subprocess.check_output(
        ["kubectl", "get", "hpa", "-n", ns, "-o", "json"],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    items = json.loads(raw).get("items") or []
except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
    sys.exit(1)

if not items:
    sys.exit(1)

if headers:
    if style == "kubectl":
        print(
            f"{'NAME':<20} {'REFERENCE':<31} {'TARGETS':<11} "
            f"{'MINPODS':<9} {'MAXPODS':<9} {'REPLICAS':<10} AGE"
        )
    else:
        print("GPU utilization rate (avg per pod): current / target")
        print(
            f"{'NAME':<22} {'REFERENCE':<31} {'GPU UTIL %':<18} "
            f"{'MINPODS':<8} {'MAXPODS':<8} {'REPLICAS':<10} AGE"
        )

for h in items:
    print_row(h)
PY
}

# Autoscaling-only stdout: GPU utilization as 30.25%/40% (not kubectl milli-units).
hpa_common_print_hpa() {
  local ns="${1:?namespace}"
  if ! hpa_common_format_hpa "${ns}" 1 "script"; then
    kubectl get hpa -n "${ns}" 2>/dev/null || true
  fi
}

# Agent pods + per-pod GPU % (same namespace as HPA).
hpa_common_print_agent_pods() {
  local ns="${1:?namespace}"
  python3 - "${ns}" <<'PY'
import json, subprocess, sys

ns = sys.argv[1]

def qty(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s == "<unknown>":
        return None
    if s.endswith("m"):
        return float(s[:-1]) / 1000.0
    return float(s)

def fmt_pct(n):
    if n is None:
        return "<unknown>"
    if abs(n - round(n)) < 1e-6:
        return f"{int(round(n))}%"
    s = f"{n:.2f}".rstrip("0").rstrip(".")
    return f"{s}%"

def age(ts):
    if not ts:
        return "?"
    from datetime import datetime, timezone
    created = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    secs = int((datetime.now(timezone.utc) - created).total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"

gpu = {}
try:
    raw = subprocess.check_output(
        [
            "kubectl", "get", "--raw",
            f"/apis/custom.metrics.k8s.io/v1beta1/namespaces/{ns}/pods/*/gpu_utilization_percent",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    for item in json.loads(raw).get("items") or []:
        pod = item.get("describedObject", {}).get("name", "")
        gpu[pod] = fmt_pct(qty(item.get("value")))
except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
    pass

try:
    raw = subprocess.check_output(
        [
            "kubectl", "get", "pods", "-n", ns,
            "-l", "app.kubernetes.io/name=nemoclaw-gpu,component=gpu-agent",
            "-o", "json",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    items = json.loads(raw).get("items") or []
except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
    items = []

print()
print("Agent pods (avg GPU util per pod):")
if not items:
    print("  (no gpu-agent pods)")
else:
    print(
        f"{'NAME':<42} {'READY':<7} {'STATUS':<11} {'RESTARTS':<9} "
        f"{'GPU UTIL':<10} AGE"
    )
    for pod in sorted(items, key=lambda p: p["metadata"]["name"]):
        meta = pod["metadata"]
        status = pod.get("status") or {}
        name = meta["name"]
        ready = sum(
            1 for c in (status.get("containerStatuses") or [])
            if c.get("ready")
        )
        total = len(status.get("containerStatuses") or [])
        ready_s = f"{ready}/{total}" if total else "?"
        phase = status.get("phase") or "?"
        restarts = sum(
            (c.get("restartCount") or 0) for c in (status.get("containerStatuses") or [])
        )
        print(
            f"{name:<42} {ready_s:<7} {phase:<11} {restarts:<9} "
            f"{gpu.get(name, '<unknown>'):<10} {age(meta.get('creationTimestamp'))}"
        )

# Load-test job pods (if running)
try:
    raw = subprocess.check_output(
        [
            "kubectl", "get", "pods", "-n", ns,
            "-l", "job-name=nemoclaw-gpu-hpa-load-test",
            "-o", "json",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    load_items = json.loads(raw).get("items") or []
except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
    load_items = []

if load_items:
    print()
    print("Load-test generators:")
    print(f"{'NAME':<42} {'READY':<7} {'STATUS':<11} {'RESTARTS':<9} AGE")
    for pod in sorted(load_items, key=lambda p: p["metadata"]["name"]):
        meta = pod["metadata"]
        status = pod.get("status") or {}
        name = meta["name"]
        ready = sum(
            1 for c in (status.get("containerStatuses") or [])
            if c.get("ready")
        )
        total = len(status.get("containerStatuses") or [])
        ready_s = f"{ready}/{total}" if total else "?"
        phase = status.get("phase") or "?"
        restarts = sum(
            (c.get("restartCount") or 0) for c in (status.get("containerStatuses") or [])
        )
        print(
            f"{name:<42} {ready_s:<7} {phase:<11} {restarts:<9} "
            f"{age(meta.get('creationTimestamp'))}"
        )
PY
}

# Log one HPA row when TARGETS or REPLICAS change (load-test loops).
# Usage: hpa_common_log_hpa_if_changed <namespace> <last_line_var_name>
hpa_common_log_hpa_if_changed() {
  local ns="${1:?namespace}"
  local last_var="${2:?lastLineVar}"
  local line last
  line="$(hpa_common_format_hpa "${ns}" 0 "script" 2>/dev/null | head -1 || true)"
  [[ -z "${line}" ]] && return 0
  last="${!last_var}"
  if [[ "${line}" != "${last}" ]]; then
    hpa_common_log "${line}"
    printf -v "${last_var}" '%s' "${line}"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 1
  }
}

# Match Helm fullname in templates/_helpers.tpl (release name contains chart name → use release only).
# Driven entirely by the RELEASE/CHART_NAME env vars; no caller passes positional args.
hpa_common_release_fullname() {
  local release="${RELEASE:-nemoclaw-gpu}"
  local chart="${CHART_NAME:-nemoclaw-gpu}"
  if [[ "${release}" == *"${chart}"* ]]; then
    echo "${release}"
  else
    echo "${release}-${chart}"
  fi
}

hpa_common_agent_deployment() {
  echo "$(hpa_common_release_fullname)-agent"
}

hpa_common_agent_service() {
  echo "$(hpa_common_release_fullname)-agent"
}

hpa_common_release_selector() {
  local release="${RELEASE:-nemoclaw-gpu}"
  local chart="${CHART_NAME:-nemoclaw-gpu}"
  printf 'app.kubernetes.io/name=%s,app.kubernetes.io/instance=%s' "${chart}" "${release}"
}

# Reject cleartext when Kubernetes reports a node or Envoy Gateway dataplane exposure path.
# The operator must separately restrict access from other hosts on the private network.
hpa_common_verify_insecure_ingress_isolation() {
  local ingress_ns="${INGRESS_NS:-envoy-gateway-system}"
  local app_ns="${NAMESPACE:-nemoclaw-gpu}"
  local service_type="${INGRESS_SERVICE_TYPE:-ClusterIP}"

  require_cmd kubectl
  require_cmd python3
  python3 - "${ingress_ns}" "${app_ns}" "${service_type}" <<'PY'
import ipaddress
import json
import subprocess
import sys

control_plane_ns, app_ns, service_type = sys.argv[1:]


def kubectl_json(*args):
    try:
        raw = subprocess.check_output(
            ["kubectl", *args, "-o", "json"],
            stderr=subprocess.PIPE,
            text=True,
        )
        return json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"cannot verify cleartext ingress isolation: kubectl {' '.join(args)} failed", file=sys.stderr)
        raise SystemExit(1) from exc


private_ranges = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "10.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)

nodes = kubectl_json("get", "nodes").get("items") or []
internal_ips = []
external_ips = []
for node in nodes:
    for address in (node.get("status") or {}).get("addresses") or []:
        if address.get("type") == "InternalIP":
            internal_ips.append(address.get("address", ""))
        elif address.get("type") == "ExternalIP":
            external_ips.append(address.get("address", ""))

if not internal_ips:
    print("cleartext ingress denied: cluster nodes have no verifiable InternalIP", file=sys.stderr)
    raise SystemExit(1)
if external_ips:
    print("cleartext ingress denied: cluster nodes expose ExternalIP addresses", file=sys.stderr)
    raise SystemExit(1)
for raw in internal_ips:
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        print(f"cleartext ingress denied: invalid node InternalIP {raw!r}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not any(address in network for network in private_ranges):
        print(f"cleartext ingress denied: node InternalIP {raw} is not private", file=sys.stderr)
        raise SystemExit(1)

controller_pods = kubectl_json(
    "get", "pods", "-n", control_plane_ns, "-l", "control-plane=envoy-gateway"
).get("items") or []
if not controller_pods:
    print("cleartext ingress denied: Envoy Gateway control-plane pods not found", file=sys.stderr)
    raise SystemExit(1)
for pod in controller_pods:
    name = (pod.get("metadata") or {}).get("name", "<unknown>")
    spec = pod.get("spec") or {}
    if spec.get("hostNetwork"):
        print(f"cleartext ingress denied: pod {name} uses hostNetwork", file=sys.stderr)
        raise SystemExit(1)
    for container in spec.get("containers") or []:
        for port in container.get("ports") or []:
            if port.get("hostPort"):
                print(f"cleartext ingress denied: pod {name} uses hostPort", file=sys.stderr)
                raise SystemExit(1)

# Dataplane Services are created with the chart Gateway. Envoy Gateway deploys them into
# the control-plane namespace by default. Before the first Gateway exists, require the
# configured Service type to remain ClusterIP.
proxy_services = kubectl_json(
    "get",
    "services",
    "-n",
    control_plane_ns,
    "-l",
    "app.kubernetes.io/component=proxy,app.kubernetes.io/managed-by=envoy-gateway",
).get("items") or []
if not proxy_services:
    if service_type != "ClusterIP":
        print(
            "cleartext ingress denied: Envoy dataplane Service type must be ClusterIP "
            "before the Gateway exists",
            file=sys.stderr,
        )
        raise SystemExit(1)
else:
    for service in proxy_services:
        name = (service.get("metadata") or {}).get("name", "<unknown>")
        spec = service.get("spec") or {}
        status = service.get("status") or {}
        if spec.get("type") != "ClusterIP":
            print(f"cleartext ingress denied: Service {name} is not ClusterIP", file=sys.stderr)
            raise SystemExit(1)
        if spec.get("externalIPs"):
            print(f"cleartext ingress denied: Service {name} has externalIPs", file=sys.stderr)
            raise SystemExit(1)
        if ((status.get("loadBalancer") or {}).get("ingress") or []):
            print(f"cleartext ingress denied: Service {name} has a load-balancer address", file=sys.stderr)
            raise SystemExit(1)

    proxy_pods = kubectl_json(
        "get",
        "pods",
        "-n",
        control_plane_ns,
        "-l",
        "app.kubernetes.io/component=proxy,app.kubernetes.io/managed-by=envoy-gateway",
    ).get("items") or []
    for pod in proxy_pods:
        name = (pod.get("metadata") or {}).get("name", "<unknown>")
        spec = pod.get("spec") or {}
        if spec.get("hostNetwork"):
            print(f"cleartext ingress denied: pod {name} uses hostNetwork", file=sys.stderr)
            raise SystemExit(1)
        for container in spec.get("containers") or []:
            for port in container.get("ports") or []:
                if port.get("hostPort"):
                    print(f"cleartext ingress denied: pod {name} uses hostPort", file=sys.stderr)
                    raise SystemExit(1)
PY
}

hpa_common_sha_htpasswd_line() {
  local username="${1:?username}"
  local password="${2:?password}"
  require_cmd python3
  python3 - "${username}" "${password}" <<'PY'
import base64
import hashlib
import sys

username, password = sys.argv[1], sys.argv[2]
digest = hashlib.sha1(password.encode("utf-8")).digest()
print(f"{username}:{{SHA}}{base64.b64encode(digest).decode('ascii')}")
PY
}

# Resolve the Basic auth password/htpasswd pair for Envoy Gateway.
# Prefer an existing generated Secret so credentials stay stable across upgrades.
hpa_common_ingress_basic_auth_credentials() {
  local ns="${1:?namespace}"
  local release="${2:?release}"
  local username="${3:-admin}"
  local secret_name="${4:-${release}-agent-ingress-auth}"

  require_cmd kubectl
  require_cmd python3

  local password=""
  password="$(kubectl get secret "${secret_name}" -n "${ns}" \
    -o jsonpath='{.data.password}' 2>/dev/null | base64 -d || true)"
  if [[ -z "${password}" ]]; then
    password="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(16))
PY
)"
  fi
  local htpasswd
  htpasswd="$(hpa_common_sha_htpasswd_line "${username}" "${password}")"
  printf '%s\t%s\n' "${password}" "${htpasswd}"
}

# ENABLE_ENVOY_LB=1 (default) installs/renders Envoy Gateway LeastRequest.
# ENABLE_ENVOY_LB=0 skips Envoy; clients use the agent Service only.
hpa_common_envoy_lb_enabled() {
  case "${ENABLE_ENVOY_LB:-1}" in
    1) return 0 ;;
    0) return 1 ;;
    *)
      echo "ENABLE_ENVOY_LB must be 0 or 1" >&2
      return 2
      ;;
  esac
}

hpa_common_envoy_lb_helm_value() {
  if hpa_common_envoy_lb_enabled; then
    printf 'true'
  else
    printf 'false'
  fi
}

hpa_common_agent_service_base_url() {
  local ns="${1:-${NAMESPACE:-nemoclaw-gpu}}"
  local service="${2:-}"
  local port="${3:-${SERVICE_PORT:-8081}}"
  if [[ -z "${service}" ]]; then
    service="$(RELEASE="${RELEASE:-nemoclaw-gpu}" hpa_common_agent_deployment)"
  fi
  [[ "${ns}" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] \
    || { echo "invalid namespace for agent Service URL: ${ns}" >&2; return 1; }
  [[ "${service}" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] \
    || { echo "invalid Service name for agent Service URL: ${service}" >&2; return 1; }
  if [[ ! "${port}" =~ ^[0-9]+$ ]] || ((10#${port} < 1 || 10#${port} > 65535)); then
    echo "invalid Service port for agent Service URL: ${port}" >&2
    return 1
  fi
  printf 'http://%s.%s.svc.cluster.local:%s/v1' "${service}" "${ns}" "${port}"
}

# OpenShell / in-cluster inference base URL: Envoy dataplane when LB is on, else agent Service.
# When ENABLE_ENVOY_LB is unset at runtime, auto-detect from an existing Gateway object.
hpa_common_openshell_inference_base_url() {
  local gateway_ns="${1:-${NAMESPACE:-nemoclaw-gpu}}"
  local gateway_name="${2:-}"
  local service="${3:-}"
  local port="${4:-${SERVICE_PORT:-8081}}"
  if [[ -z "${gateway_name}" ]]; then
    gateway_name="$(RELEASE="${RELEASE:-nemoclaw-gpu}" hpa_common_agent_deployment)"
  fi
  if [[ -z "${service}" ]]; then
    service="${gateway_name}"
  fi

  case "${ENABLE_ENVOY_LB:-}" in
    1)
      hpa_common_envoy_dataplane_base_url "${gateway_ns}" "${gateway_name}"
      return
      ;;
    0)
      hpa_common_agent_service_base_url "${gateway_ns}" "${service}" "${port}"
      return
      ;;
    "")
      if kubectl get gateway "${gateway_name}" -n "${gateway_ns}" >/dev/null 2>&1; then
        hpa_common_envoy_dataplane_base_url "${gateway_ns}" "${gateway_name}"
      else
        hpa_common_agent_service_base_url "${gateway_ns}" "${service}" "${port}"
      fi
      return
      ;;
    *)
      echo "ENABLE_ENVOY_LB must be 0, 1, or unset" >&2
      return 1
      ;;
  esac
}

hpa_common_envoy_dataplane_base_url() {
  local control_plane_ns="${INGRESS_NS:-envoy-gateway-system}"
  local gateway_ns="${1:-${NAMESPACE:-nemoclaw-gpu}}"
  local gateway_name="${2:-}"
  require_cmd kubectl
  require_cmd python3
  python3 - "${control_plane_ns}" "${gateway_ns}" "${gateway_name}" <<'PY'
import json
import subprocess
import sys

control_plane_ns, gateway_ns, gateway_name = sys.argv[1:]
selector = "app.kubernetes.io/component=proxy,app.kubernetes.io/managed-by=envoy-gateway"
if gateway_name:
    selector += f",gateway.envoyproxy.io/owning-gateway-name={gateway_name}"
    selector += f",gateway.envoyproxy.io/owning-gateway-namespace={gateway_ns}"

try:
    raw = subprocess.check_output(
        ["kubectl", "get", "services", "-n", control_plane_ns, "-l", selector, "-o", "json"],
        stderr=subprocess.PIPE,
        text=True,
    )
    items = json.loads(raw).get("items") or []
except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
    print(f"cannot resolve Envoy dataplane Service: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc

if not items:
    print(
        "Envoy dataplane Service not found; install/upgrade the GPU chart before creating the sandbox",
        file=sys.stderr,
    )
    raise SystemExit(1)

service = items[0]
name = service["metadata"]["name"]
ports = (service.get("spec") or {}).get("ports") or []
http_port = None
for port in ports:
    if port.get("port") == 80 or port.get("name") in {"http", "http-80"}:
        http_port = port.get("port")
        break
if http_port is None and ports:
    http_port = ports[0].get("port")
if not http_port:
    print("Envoy dataplane Service has no usable port", file=sys.stderr)
    raise SystemExit(1)

print(f"http://{name}.{control_plane_ns}.svc.cluster.local:{http_port}/v1")
PY
}

# Confirm Envoy LeastRequest is configured and concurrent OpenShell-path traffic
# reaches every Ready inference pod. Call after HPA scale-up while replicas remain Ready.
# Set SKIP_ENVOY_LB_TEST=1 to skip. Tunables: LB_TEST_REQUESTS, LB_TEST_CONCURRENCY,
# LB_TEST_MAX_SHARE (max fraction of successes any one pod may receive, default 0.75).
hpa_common_verify_envoy_least_request_distribution() {
  local ns="${1:?namespace}"
  local release="${2:?release}"
  local secret_name="${3:?inferenceSecret}"
  local secret_key="${4:?inferenceSecretKey}"
  local min_ready="${5:?minReadyReplicas}"
  local model="${6:-${INFERENCE_MODEL:-llama3.2:3b}}"
  local gateway_name="${7:-${release}-agent}"
  local probe_pod="${LB_TEST_PROBE_POD:-nemoclaw-gpu-envoy-lb-probe}"
  local requests="${LB_TEST_REQUESTS:-48}"
  local concurrency="${LB_TEST_CONCURRENCY:-12}"
  local max_share="${LB_TEST_MAX_SHARE:-0.75}"
  local api_key=""
  local envoy_base=""
  local pod_ips=""
  local ready_count=0
  local probe_out=""
  local summary=""

  case "${SKIP_ENVOY_LB_TEST:-0}" in
    1)
      hpa_common_log "Skipping Envoy LeastRequest distribution check (SKIP_ENVOY_LB_TEST=1)"
      return 0
      ;;
  esac
  if ! hpa_common_envoy_lb_enabled; then
    hpa_common_log "Skipping Envoy LeastRequest distribution check (ENABLE_ENVOY_LB=0)"
    return 0
  fi

  if [[ "${min_ready}" -lt 2 ]]; then
    hpa_common_log "Skipping Envoy LeastRequest distribution check (need >=2 replicas, have target ${min_ready})"
    return 0
  fi

  require_cmd kubectl
  require_cmd python3

  if ! kubectl get backendtrafficpolicy -n "${ns}" -o json \
    | python3 -c '
import json, sys
docs = json.load(sys.stdin).get("items") or []
types = {
    ((doc.get("spec") or {}).get("loadBalancer") or {}).get("type")
    for doc in docs
}
if not docs:
    raise SystemExit("no BackendTrafficPolicy found")
if types != {"LeastRequest"}:
    raise SystemExit(f"BackendTrafficPolicy loadBalancer types={sorted(types)!r}, expected LeastRequest only")
'; then
    echo "Envoy LeastRequest BackendTrafficPolicy check failed" >&2
    return 1
  fi

  ready_count="$(kubectl get pods -n "${ns}" \
    -l 'app.kubernetes.io/name=nemoclaw-gpu,component=gpu-agent' \
    -o json \
    | python3 -c '
import json, sys
items = json.load(sys.stdin).get("items") or []
ready = 0
for pod in items:
    statuses = (pod.get("status") or {}).get("containerStatuses") or []
    if statuses and all(status.get("ready") for status in statuses):
        ready += 1
print(ready)
')"
  if [[ "${ready_count}" -lt "${min_ready}" ]]; then
    echo "Envoy LB check needs ${min_ready} Ready agent pods; found ${ready_count}" >&2
    return 1
  fi

  api_key="$(
    kubectl get secret "${secret_name}" -n "${ns}" -o json \
      | python3 -c 'import base64,json,sys; print(base64.b64decode(json.load(sys.stdin)["data"][sys.argv[1]]).decode())' \
        "${secret_key}"
  )"
  [[ -n "${api_key}" ]] || {
    echo "inference API key is empty for Envoy LB check" >&2
    return 1
  }

  envoy_base="$(hpa_common_envoy_dataplane_base_url "${ns}" "${gateway_name}")"
  envoy_base="${envoy_base%/v1}"
  pod_ips="$(kubectl get pods -n "${ns}" \
    -l 'app.kubernetes.io/name=nemoclaw-gpu,component=gpu-agent' \
    -o json \
    | python3 -c '
import json, sys
items = json.load(sys.stdin).get("items") or []
ips = []
for pod in items:
    statuses = (pod.get("status") or {}).get("containerStatuses") or []
    ip = (pod.get("status") or {}).get("podIP")
    if ip and statuses and all(status.get("ready") for status in statuses):
        ips.append(ip)
print(" ".join(ips))
')"
  [[ -n "${pod_ips}" ]] || {
    echo "no agent pod IPs for Envoy LB check" >&2
    return 1
  }

  hpa_common_log "Envoy LeastRequest check: ${requests} requests (concurrency ${concurrency}) via ${envoy_base} across pods [${pod_ips}]"

  kubectl delete pod "${probe_pod}" -n "${ns}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl run "${probe_pod}" -n "${ns}" --restart=Never --image=curlimages/curl:8.5.0 \
    --command -- sleep 900 >/dev/null
  if ! kubectl wait --for=condition=Ready "pod/${probe_pod}" -n "${ns}" --timeout=120s >/dev/null 2>&1; then
    echo "Envoy LB probe pod not Ready" >&2
    kubectl delete pod "${probe_pod}" -n "${ns}" --ignore-not-found >/dev/null 2>&1 || true
    return 1
  fi

  # Pass the API key on stdin so it does not appear in process argv.
  if ! probe_out="$(
    printf '%s' "${api_key}" | kubectl exec -i -n "${ns}" "${probe_pod}" -- sh -c "
set -eu
API_KEY=\$(cat)
ENVOY_BASE='${envoy_base}'
POD_IPS='${pod_ips}'
MODEL='${model}'
N='${requests}'
CONCUR='${concurrency}'
rm -f /tmp/codes.txt /tmp/before.txt /tmp/after.txt
snapshot() {
  out=\"\$1\"
  : > \"\$out\"
  for ip in \$POD_IPS; do
    line=\$(wget -qO- \"http://\${ip}:8081/metrics\" 2>/dev/null \
      | grep 'nemoclaw_llm_requests_total{result=\"success\"}' \
      || echo 'nemoclaw_llm_requests_total{result=\"success\"} 0')
    count=\$(printf '%s\n' \"\$line\" | awk '{print \$NF}')
    printf '%s %s\n' \"\$ip\" \"\$count\" >> \"\$out\"
  done
}
snapshot /tmp/before.txt
i=0
while [ \"\$i\" -lt \"\$N\" ]; do
  active=0
  while [ \"\$active\" -lt \"\$CONCUR\" ] && [ \"\$i\" -lt \"\$N\" ]; do
    i=\$((i+1))
    active=\$((active+1))
    (
      code=\$(curl -s -o /dev/null -w '%{http_code}' --max-time 180 \
        -H \"Authorization: Bearer \${API_KEY}\" \
        -H 'Content-Type: application/json' \
        -d \"{\\\"model\\\":\\\"\${MODEL}\\\",\\\"messages\\\":[{\\\"role\\\":\\\"user\\\",\\\"content\\\":\\\"Reply with exactly one word: ping\\\"}],\\\"max_tokens\\\":8,\\\"stream\\\":false}\" \
        \"\${ENVOY_BASE}/v1/chat/completions\" || echo 000)
      echo \"\$code\" >> /tmp/codes.txt
    ) &
  done
  wait
done
snapshot /tmp/after.txt
echo '---CODES---'
cat /tmp/codes.txt
echo '---BEFORE---'
cat /tmp/before.txt
echo '---AFTER---'
cat /tmp/after.txt
"
  )"; then
    echo "Envoy LB probe exec failed" >&2
    kubectl delete pod "${probe_pod}" -n "${ns}" --ignore-not-found >/dev/null 2>&1 || true
    return 1
  fi
  kubectl delete pod "${probe_pod}" -n "${ns}" --ignore-not-found >/dev/null 2>&1 || true

  if ! summary="$(
    PROBE_OUT="${probe_out}" REQUESTS="${requests}" MAX_SHARE="${max_share}" python3 <<'PY'
import os

requests = int(os.environ["REQUESTS"])
max_share = float(os.environ["MAX_SHARE"])
text = os.environ["PROBE_OUT"].splitlines()

def section(name: str) -> list[str]:
    try:
        start = text.index(f"---{name}---") + 1
    except ValueError as exc:
        raise SystemExit(f"missing {name} section in probe output") from exc
    end = start
    while end < len(text) and not text[end].startswith("---"):
        end += 1
    return text[start:end]

codes = section("CODES")
before = {ip: int(count) for ip, count in (line.split() for line in section("BEFORE") if line.strip())}
after = {ip: int(count) for ip, count in (line.split() for line in section("AFTER") if line.strip())}
if set(before) != set(after) or not before:
    raise SystemExit(f"pod IP set mismatch before={sorted(before)} after={sorted(after)}")

ok = sum(1 for code in codes if code.strip() == "200")
if ok < requests:
    raise SystemExit(f"Envoy LB check: only {ok}/{requests} requests returned HTTP 200")

deltas = {ip: after[ip] - before[ip] for ip in before}
total_delta = sum(deltas.values())
if total_delta < max(1, requests // 2):
    raise SystemExit(
        f"Envoy LB check: success-counter delta {total_delta} too low for {requests} requests: {deltas}"
    )

zero = [ip for ip, delta in deltas.items() if delta <= 0]
if zero:
    raise SystemExit(f"Envoy LB check: pods received no Envoy traffic: {zero}; deltas={deltas}")

peak = max(deltas.values())
if peak / total_delta > max_share:
    raise SystemExit(
        f"Envoy LB check: uneven distribution deltas={deltas} "
        f"(peak share {peak / total_delta:.2f} > {max_share})"
    )

print(
    "Envoy LeastRequest OK: "
    + ", ".join(f"{ip}:+{delta}" for ip, delta in sorted(deltas.items()))
)
PY
  )"; then
    echo "Envoy LeastRequest distribution check failed" >&2
    printf '%s\n' "${probe_out}" >&2
    return 1
  fi

  hpa_common_log "${summary}"
  return 0
}

hpa_common_ingress_allow_insecure_value() {
  # Cleartext Gateway exposure only applies when Envoy LB is enabled.
  if ! hpa_common_envoy_lb_enabled; then
    printf 'false'
    return 0
  fi
  case "${ALLOW_INSECURE_HTTP:-0}" in
    0)
      printf 'false'
      ;;
    1)
      if ! hpa_common_verify_insecure_ingress_isolation; then
        echo "Configure ingress.tls instead, or restrict the reported exposure path before retrying cleartext." >&2
        return 1
      fi
      printf 'true'
      ;;
    *)
      echo "ALLOW_INSECURE_HTTP must be 0 or 1" >&2
      return 1
      ;;
  esac
}

# Old releases used component=agent; chart now uses gpu-agent + workload-type (immutable selector).
hpa_common_gpu_stale_workload() {
  local ns="${1:?namespace}"
  local deploy="${2:?deploy}"
  local comp
  comp="$(kubectl get "deployment/${deploy}" -n "${ns}" \
    -o jsonpath='{.spec.selector.matchLabels.component}' 2>/dev/null || true)"
  [[ "${comp}" == "agent" ]]
}

hpa_common_gpu_recreate_stale_workload() {
  local ns="${1:?namespace}"
  local deploy="${2:?deploy}"
  local svc="${3:-${deploy}}"
  if hpa_common_gpu_stale_workload "${ns}" "${deploy}"; then
    kubectl delete "deployment/${deploy}" "service/${svc}" -n "${ns}" \
      --ignore-not-found --wait=false 2>/dev/null || true
    sleep 2
  fi
}

hpa_common_validate_node_name() {
  local node="${1:-}"
  [[ -n "${node}" && ${#node} -le 253 ]] || return 1
  [[ "${node}" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || return 1

  local label
  local labels=()
  IFS='.' read -r -a labels <<<"${node}"
  for label in "${labels[@]}"; do
    [[ -n "${label}" && ${#label} -le 63 ]] || return 1
    [[ "${label}" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || return 1
  done
}

hpa_common_node_inventory() {
  local target_node="${NEMOCLAW_TARGET_NODE:-}"
  if [[ -n "${target_node}" ]]; then
    kubectl get node "${target_node}" \
      -o 'jsonpath={.metadata.name}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\t"}{.status.allocatable.nvidia\.com/gpu}{"\t"}{.metadata.labels.nvidia\.com/gpu\.present}{"\n"}' \
      2>/dev/null
  else
    kubectl get nodes \
      -o 'jsonpath={range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\t"}{.status.allocatable.nvidia\.com/gpu}{"\t"}{.metadata.labels.nvidia\.com/gpu\.present}{"\n"}{end}' \
      2>/dev/null
  fi
}

# Validate the optional scheduling boundary before a script mutates the cluster.
# Pass 0 when the selected workload itself does not require a GPU.
hpa_common_verify_target_node() {
  local require_gpu="${1:-1}"
  local target_node="${NEMOCLAW_TARGET_NODE:-}"
  [[ -n "${target_node}" ]] || return 0

  if ! hpa_common_validate_node_name "${target_node}"; then
    echo "NEMOCLAW_TARGET_NODE must be a valid lowercase Kubernetes node name" >&2
    return 1
  fi

  local inventory node ready gpu_count gpu_present
  if ! inventory="$(hpa_common_node_inventory)" || [[ -z "${inventory}" ]]; then
    echo "NEMOCLAW_TARGET_NODE ${target_node} was not found" >&2
    return 1
  fi
  node="$(awk -F '\t' 'NR == 1 {print $1}' <<<"${inventory}")"
  ready="$(awk -F '\t' 'NR == 1 {print $2}' <<<"${inventory}")"
  gpu_count="$(awk -F '\t' 'NR == 1 {print $3}' <<<"${inventory}")"
  gpu_present="$(awk -F '\t' 'NR == 1 {print $4}' <<<"${inventory}")"
  if [[ "${node}" != "${target_node}" ]]; then
    echo "NEMOCLAW_TARGET_NODE ${target_node} was not found" >&2
    return 1
  fi
  if [[ "${ready}" != "True" ]]; then
    echo "NEMOCLAW_TARGET_NODE ${target_node} is not Ready" >&2
    return 1
  fi
  if [[ "${require_gpu}" == "1" ]] \
    && { [[ ! "${gpu_count}" =~ ^[0-9]+$ ]] || ((10#${gpu_count} < 1)); }; then
    echo "NEMOCLAW_TARGET_NODE ${target_node} has no allocatable nvidia.com/gpu" >&2
    return 1
  fi
  if [[ "${require_gpu}" == "1" && "${gpu_present}" != "true" ]]; then
    echo "NEMOCLAW_TARGET_NODE ${target_node} does not have nvidia.com/gpu.present=true" >&2
    return 1
  fi
}

hpa_common_target_node_helm_value() {
  local target_node="${NEMOCLAW_TARGET_NODE:-}"
  [[ -n "${target_node}" ]] || return 1
  printf 'nodeSelector.kubernetes\\.io/hostname=%s' "${target_node}"
}

# Idle Kubernetes HPA baseline for GPU autoscaling (no --reuse-values — avoids Service port merge bugs).
hpa_common_gpu_helm_upgrade() {
  local release="${1:?release}"
  local chart_dir="${2:?chartDir}"
  local ns="${3:?namespace}"
  local hpa_values="${4:?valuesFile}"
  local min="${5:-1}"
  local max="${6:-4}"
  local gpu_target="${7:-40}"
  local inference_model="${8:-llama3.2:3b}"
  local ingress_host="${9:-}"

  local allow_insecure_http
  allow_insecure_http="$(hpa_common_ingress_allow_insecure_value)"

  local auth_password auth_htpasswd
  IFS=$'\t' read -r auth_password auth_htpasswd < <(
    hpa_common_ingress_basic_auth_credentials "${ns}" "${release}"
  )

  local helm_args=(
    upgrade --install "${release}" "${chart_dir}"
    --namespace "${ns}"
    --create-namespace
    --set namespace.create=false
    -f "${hpa_values}"
    --set inference.model="${inference_model}"
    --set probes.readinessChecksInference=true
    --set autoscaling.enabled=true
    --set autoscaling.minReplicas="${min}"
    --set autoscaling.maxReplicas="${max}"
    --set autoscaling.maxGpus="${max}"
    --set "autoscaling.metric=${HPA_METRIC:-gpu}"
    --set "autoscaling.targetGPUUtilizationPercentage=${gpu_target}"
    --set "autoscaling.targetLatencyMilliseconds=${HPA_TARGET_LATENCY_MS:-5000}"
    --set-string "autoscaling.targetRequestRate=${HPA_TARGET_REQUEST_RATE:-2}"
    --set "ingress.allowInsecureHttp=${allow_insecure_http}"
    --set "ingress.gateway.enabled=$(hpa_common_envoy_lb_helm_value)"
    --set "ingress.gateway.serviceType=${INGRESS_SERVICE_TYPE:-ClusterIP}"
    --set "ingress.gateway.className=${INGRESS_CLASS:-eg}"
    --set "ingress.auth.password=${auth_password}"
    --set-string "ingress.auth.htpasswd=${auth_htpasswd}"
  )
  if [[ -n "${ingress_host}" ]]; then
    helm_args+=(--set "ingress.host=${ingress_host}")
  fi
  if [[ -n "${NEMOCLAW_TARGET_NODE:-}" ]]; then
    helm_args+=(--set-string "$(hpa_common_target_node_helm_value)")
  fi

  helm "${helm_args[@]}" >/dev/null
}

hpa_common_cleanup_load_test_resources() {
  local ns="${1:?namespace}"
  local job_name="${2:?jobName}"

  kubectl delete job "${job_name}" -n "${ns}" --ignore-not-found=true >/dev/null 2>&1 || true
  kubectl delete rolebinding "${job_name}-endpoints-reader" -n "${ns}" --ignore-not-found=true >/dev/null 2>&1 || true
  kubectl delete role "${job_name}-endpoints-reader" -n "${ns}" --ignore-not-found=true >/dev/null 2>&1 || true
  kubectl delete serviceaccount "${job_name}-sa" -n "${ns}" --ignore-not-found=true >/dev/null 2>&1 || true
  kubectl delete configmap "${job_name}-scripts" -n "${ns}" --ignore-not-found=true >/dev/null 2>&1 || true
}

# Recovery touches only pods owned by this Helm release and the named load-test Job.
hpa_common_clear_stuck_pods() {
  local ns="${1:?namespace}"
  local job_name="${2:-nemoclaw-gpu-hpa-load-test}"
  local release_selector
  release_selector="$(hpa_common_release_selector)"
  local pod
  for pod in $(kubectl get pods -n "${ns}" \
    -l "${release_selector}" \
    -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
    [[ -z "${pod}" ]] && continue
    kubectl patch pod "${pod}" -n "${ns}" -p '{"metadata":{"finalizers":null}}' --type=merge \
      >/dev/null 2>&1 || true
  done
  for pod in $(kubectl get pods -n "${ns}" \
    -l "job-name=${job_name}" \
    -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
    [[ -z "${pod}" ]] && continue
    kubectl patch pod "${pod}" -n "${ns}" -p '{"metadata":{"finalizers":null}}' --type=merge \
      >/dev/null 2>&1 || true
  done
  kubectl delete pods -n "${ns}" -l "${release_selector}" \
    --force --grace-period=0 >/dev/null 2>&1 || true
  kubectl delete pods -n "${ns}" -l "job-name=${job_name}" \
    --force --grace-period=0 >/dev/null 2>&1 || true
}

hpa_common_ensure_agent_ready() {
  local ns="${1:?namespace}"
  local release="${2:?release}"
  local chart_dir="${3:?chartDir}"
  local values_file="${4:-}"
  local rollout_timeout="${5:-600}"
  local deploy
  deploy="$(RELEASE="${release}" hpa_common_agent_deployment)"

  local allow_insecure_http
  allow_insecure_http="$(hpa_common_ingress_allow_insecure_value)"

  local auth_password auth_htpasswd
  IFS=$'\t' read -r auth_password auth_htpasswd < <(
    hpa_common_ingress_basic_auth_credentials "${ns}" "${release}"
  )

  local helm_args=(
    upgrade --install "${release}" "${chart_dir}" -n "${ns}"
    --set "namespace.create=false"
    --set "autoscaling.enabled=false"
    --set "gpuScaling.count=1"
    --set "ingress.allowInsecureHttp=${allow_insecure_http}"
    --set "ingress.gateway.enabled=$(hpa_common_envoy_lb_helm_value)"
    --set "ingress.gateway.serviceType=${INGRESS_SERVICE_TYPE:-ClusterIP}"
    --set "ingress.gateway.className=${INGRESS_CLASS:-eg}"
    --set "ingress.auth.password=${auth_password}"
    --set-string "ingress.auth.htpasswd=${auth_htpasswd}"
  )
  if [[ -n "${values_file}" && -f "${values_file}" ]]; then
    helm_args+=(-f "${values_file}")
  fi
  if [[ -n "${NEMOCLAW_TARGET_NODE:-}" ]]; then
    helm_args+=(--set-string "$(hpa_common_target_node_helm_value)")
  fi
  helm "${helm_args[@]}" >/dev/null

  hpa_common_kick_deployment "${ns}" "${deploy}" || helm "${helm_args[@]}" >/dev/null

  if ! kubectl rollout status "deployment/${deploy}" -n "${ns}" --timeout="${rollout_timeout}s" >/dev/null; then
    hpa_common_diagnose_rollout "${ns}" "${deploy}"
    return 1
  fi

  local ready
  ready="$(kubectl get "deployment/${deploy}" -n "${ns}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)"
  if [[ "${ready}" != "1" ]]; then
    hpa_common_diagnose_rollout "${ns}" "${deploy}"
    return 1
  fi
  return 0
}

hpa_common_wait_rollout() {
  local deploy="${1:?deploy}"
  local ns="${2:?namespace}"
  local timeout="${3:-600}"
  kubectl rollout status "deployment/${deploy}" -n "${ns}" --timeout="${timeout}s" >/dev/null
}

hpa_common_kick_deployment() {
  local ns="${1:?namespace}"
  local deploy="${2:?deploy}"
  local rs
  rs="$(kubectl get rs -n "${ns}" -l "app.kubernetes.io/name=nemoclaw-gpu,component=gpu-agent" \
    -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)"
  if [[ -n "${rs}" ]]; then
    return 0
  fi
  kubectl rollout restart "deployment/${deploy}" -n "${ns}" >/dev/null 2>&1 || true
  sleep 8
  rs="$(kubectl get rs -n "${ns}" -l "app.kubernetes.io/name=nemoclaw-gpu,component=gpu-agent" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  [[ -n "${rs}" ]] && return 0
  kubectl delete "deployment/${deploy}" -n "${ns}" --ignore-not-found --wait=false 2>/dev/null || true
  sleep 3
  return 1
}

hpa_common_diagnose_rollout() {
  local ns="${1:?namespace}"
  hpa_common_print_hpa "${ns}"
  kubectl describe hpa -n "${ns}" 2>/dev/null | tail -20 || true
}

hpa_common_enforce_replica_floor() {
  local ns="${1:?namespace}"
  local deploy="${2:?deploy}"
  local min="${3:-1}"
  local spec
  spec="$(kubectl get "deployment/${deploy}" -n "${ns}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "")"
  if [[ ! "${spec}" =~ ^[0-9]+$ ]] || [[ "${spec}" -lt "${min}" ]]; then
    kubectl patch "deployment/${deploy}" -n "${ns}" \
      --type=merge -p "{\"spec\":{\"replicas\":${min}}}"
  fi
}

hpa_common_verify_hpa_bounds() {
  local ns="${1:?namespace}"
  local deploy="${2:?deploy}"
  local hpa_name="${3:-${deploy}}"
  local min="${4:-1}"
  local max="${5:-4}"

  if ! kubectl get "horizontalpodautoscaler/${hpa_name}" -n "${ns}" >/dev/null 2>&1; then
    echo "HPA ${hpa_name} not found" >&2
    return 1
  fi

  local desired
  desired="$(kubectl get "horizontalpodautoscaler/${hpa_name}" -n "${ns}" -o jsonpath='{.status.desiredReplicas}' 2>/dev/null || echo "")"

  hpa_common_enforce_replica_floor "${ns}" "${deploy}" "${min}"

  if [[ -n "${desired}" && "${desired}" =~ ^[0-9]+$ && "${desired}" -lt "${min}" ]]; then
    kubectl patch "deployment/${deploy}" -n "${ns}" \
      --type=merge -p "{\"spec\":{\"replicas\":${min}}}"
    sleep 5
  fi

  return 0
}

hpa_common_verify_gpu_nodes() {
  hpa_common_verify_target_node 1 || return 1
  local gpu_count
  gpu_count="$(hpa_common_allocatable_gpus)"
  if [[ "${gpu_count}" -lt 1 ]]; then
    echo "No allocatable nvidia.com/gpu — HPA cannot scale GPU pods" >&2
    return 1
  fi
  return 0
}

hpa_common_allocatable_gpus() {
  local inventory
  inventory="$(hpa_common_node_inventory 2>/dev/null || true)"
  awk -F '\t' '$2 == "True" && $3 ~ /^[0-9]+$/ && $4 == "true" {s += $3} END {print s+0}' <<<"${inventory}"
}

hpa_common_verify_gpu_capacity() {
  local requested="${1:?requested GPU replicas}"
  if [[ ! "${requested}" =~ ^[1-9][0-9]*$ ]]; then
    echo "GPU replica count must be a positive integer" >&2
    return 1
  fi

  local allocatable
  allocatable="$(hpa_common_allocatable_gpus)"
  if ((10#${requested} > 10#${allocatable})); then
    if [[ -n "${NEMOCLAW_TARGET_NODE:-}" ]]; then
      echo "Requested ${requested} GPU replicas, but NEMOCLAW_TARGET_NODE ${NEMOCLAW_TARGET_NODE} reports ${allocatable} allocatable GPUs" >&2
    else
      echo "Requested ${requested} GPU replicas, but Ready nodes report ${allocatable} allocatable GPUs" >&2
    fi
    return 1
  fi
}

hpa_common_verify_gpu_hpa_metric() {
  local ns="${1:-${NAMESPACE:-nemoclaw-gpu}}"
  local metric_name
  metric_name="$(hpa_common_gpu_hpa_metric_name)" || return 1
  if kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/${ns}/pods/*/${metric_name}" 2>/dev/null \
    | grep -q "\"metricName\":\"${metric_name}\""; then
    return 0
  fi
  echo "${metric_name} not available — HPA cannot scale on autoscaling.metric=${HPA_METRIC:-gpu}" >&2
  return 1
}

# Human-readable HPA metric (optional; VERBOSE=1 for full legend).
hpa_common_hpa_metric_display() {
  local ns="${1:?namespace}"
  local hpa_name="${2:-}"
  if [[ "${VERBOSE:-0}" != "1" ]]; then
    return 0
  fi
  if [[ -z "${hpa_name}" ]]; then
    hpa_name="$(kubectl get hpa -n "${ns}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  fi
  [[ -n "${hpa_name}" ]] || return 0

  local metric spec_target spec_type
  spec_type="$(kubectl get "horizontalpodautoscaler/${hpa_name}" -n "${ns}" \
    -o jsonpath='{.spec.metrics[0].type}' 2>/dev/null || true)"
  if [[ "${spec_type}" == "Pods" ]]; then
    metric="$(kubectl get "horizontalpodautoscaler/${hpa_name}" -n "${ns}" \
      -o jsonpath='{.spec.metrics[0].pods.metric.name}' 2>/dev/null || true)"
    spec_target="$(kubectl get "horizontalpodautoscaler/${hpa_name}" -n "${ns}" \
      -o jsonpath='{.spec.metrics[0].pods.target.averageValue}' 2>/dev/null || true)"
  elif [[ "${spec_type}" == "Resource" ]]; then
    metric="$(kubectl get "horizontalpodautoscaler/${hpa_name}" -n "${ns}" \
      -o jsonpath='{.spec.metrics[0].resource.name}' 2>/dev/null || true)"
    spec_target="$(kubectl get "horizontalpodautoscaler/${hpa_name}" -n "${ns}" \
      -o jsonpath='{.spec.metrics[0].resource.target.averageUtilization}' 2>/dev/null || true)"
  fi
  echo "HPA metric: ${metric:-unknown} target=${spec_target:-?}"
}

# Default HPA custom metric name for the selected autoscaling.metric / HPA_METRIC.
hpa_common_gpu_hpa_metric_name() {
  case "${HPA_METRIC:-gpu}" in
    gpu) echo "gpu_utilization_percent" ;;
    latency_p50) echo "nemoclaw_llm_latency_p50_milliseconds" ;;
    latency_p95) echo "nemoclaw_llm_latency_p95_milliseconds" ;;
    latency_avg) echo "nemoclaw_llm_latency_avg_milliseconds" ;;
    request_rate) echo "nemoclaw_llm_request_rate" ;;
    *)
      echo "unsupported HPA_METRIC=${HPA_METRIC:-}" >&2
      return 1
      ;;
  esac
}

hpa_common_print_hpa_status() {
  hpa_common_print_hpa "${1:?namespace}"
}
