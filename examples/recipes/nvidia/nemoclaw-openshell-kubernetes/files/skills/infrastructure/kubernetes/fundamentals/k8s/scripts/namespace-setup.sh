#!/usr/bin/env bash
set -euo pipefail

# Namespace setup script for Kubernetes
# Generates production-ready namespace manifests with best practices

VERSION="0.1.0"
NAMESPACE_NAME=""
OUTPUT_DIR=""
APPLY=false
CPU_QUOTA="10"
MEMORY_QUOTA="20Gi"
ADMIN_GROUP="platform-team"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") <namespace-name> [--output <dir>] [--apply]

Generate production-ready Kubernetes namespace manifests with Pod Security
Standards, ResourceQuota, LimitRange, NetworkPolicy, and RBAC.

Arguments:
  <namespace-name>       Name of the namespace to set up (required)

Options:
  --output DIR           Write individual YAML files to directory (default: stdout)
  --apply                Apply manifests directly to cluster (with confirmation)
  --cpu-quota VALUE      Total CPU quota (default: "10")
  --memory-quota VALUE   Total memory quota (default: "20Gi")
  --admin-group GROUP    Group to bind as namespace admin (default: "platform-team")
  -h, --help             Show this help
  -v, --version          Show version

Examples:
  $(basename "$0") my-app
  $(basename "$0") my-app --output ./manifests
  $(basename "$0") my-app --apply --cpu-quota 20 --memory-quota 40Gi
  $(basename "$0") my-app --admin-group dev-team
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --output) OUTPUT_DIR="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --cpu-quota) CPU_QUOTA="$2"; shift 2 ;;
        --memory-quota) MEMORY_QUOTA="$2"; shift 2 ;;
        --admin-group) ADMIN_GROUP="$2"; shift 2 ;;
        -h|--help) usage ;;
        -v|--version) echo "namespace-setup.sh v${VERSION}"; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; exit 1 ;;
        *) NAMESPACE_NAME="$1"; shift ;;
    esac
done

if [[ -z "$NAMESPACE_NAME" ]]; then
    echo "Error: Namespace name is required" >&2
    echo "Run with --help for usage" >&2
    exit 1
fi

if [[ "$APPLY" == true ]] && ! command -v kubectl &>/dev/null; then
    echo "Error: kubectl not found in PATH (required for --apply)" >&2
    exit 1
fi

section() {
    echo -e "${BOLD}${CYAN}--- $1 ---${NC}" >&2
}

pass() { echo -e "  ${GREEN}+${NC} $1" >&2; }
warn() { echo -e "  ${YELLOW}!${NC} $1" >&2; }

# --- Generate manifests ---

generate_namespace() {
    cat <<EOF
# Namespace with Pod Security Standards (restricted enforcement)
# Enforces the most restrictive pod security profile to follow best practices
apiVersion: v1
kind: Namespace
metadata:
  name: ${NAMESPACE_NAME}
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
EOF
}

generate_resource_quota() {
    cat <<EOF
# ResourceQuota: caps total CPU and memory consumed by all pods in the namespace
# Prevents a single namespace from starving other workloads on the cluster
apiVersion: v1
kind: ResourceQuota
metadata:
  name: ${NAMESPACE_NAME}-quota
  namespace: ${NAMESPACE_NAME}
spec:
  hard:
    requests.cpu: "${CPU_QUOTA}"
    requests.memory: "${MEMORY_QUOTA}"
    limits.cpu: "${CPU_QUOTA}"
    limits.memory: "${MEMORY_QUOTA}"
    pods: "50"
    services: "20"
    persistentvolumeclaims: "10"
EOF
}

generate_limit_range() {
    cat <<EOF
# LimitRange: sets default CPU/memory requests and limits for containers
# Ensures every container has resource bounds even if the author omits them
apiVersion: v1
kind: LimitRange
metadata:
  name: ${NAMESPACE_NAME}-limits
  namespace: ${NAMESPACE_NAME}
spec:
  limits:
    - type: Container
      default:
        cpu: "500m"
        memory: "512Mi"
      defaultRequest:
        cpu: "100m"
        memory: "128Mi"
      max:
        cpu: "2"
        memory: "4Gi"
      min:
        cpu: "50m"
        memory: "64Mi"
EOF
}

generate_network_policy() {
    cat <<EOF
# NetworkPolicy: default deny all ingress and egress traffic
# Start locked down, then add allow rules for specific communication paths
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: ${NAMESPACE_NAME}
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
# NetworkPolicy: allow DNS egress so pods can resolve service names
# Without this, pods cannot look up any Kubernetes service or external hostname
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: ${NAMESPACE_NAME}
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
EOF
}

generate_service_account() {
    cat <<EOF
# ServiceAccount: dedicated identity for application pods
# Avoids using the default SA, which may accumulate unintended permissions
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${NAMESPACE_NAME}-app
  namespace: ${NAMESPACE_NAME}
  labels:
    app.kubernetes.io/managed-by: namespace-setup
automountServiceAccountToken: false
EOF
}

generate_rbac() {
    cat <<EOF
# RoleBinding: grants namespace-admin privileges to the specified group
# Allows the team to manage resources within this namespace without cluster-wide access
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ${NAMESPACE_NAME}-admin
  namespace: ${NAMESPACE_NAME}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: admin
subjects:
  - kind: Group
    name: ${ADMIN_GROUP}
    apiGroup: rbac.authorization.k8s.io
EOF
}

# --- Output handling ---

all_manifests() {
    generate_namespace
    echo "---"
    generate_resource_quota
    echo "---"
    generate_limit_range
    echo "---"
    generate_network_policy
    echo "---"
    generate_service_account
    echo "---"
    generate_rbac
}

if [[ -n "$OUTPUT_DIR" ]]; then
    mkdir -p "$OUTPUT_DIR"
    section "Writing manifests to $OUTPUT_DIR"

    generate_namespace > "$OUTPUT_DIR/namespace.yaml"
    pass "namespace.yaml"

    generate_resource_quota > "$OUTPUT_DIR/resource-quota.yaml"
    pass "resource-quota.yaml"

    generate_limit_range > "$OUTPUT_DIR/limit-range.yaml"
    pass "limit-range.yaml"

    generate_network_policy > "$OUTPUT_DIR/network-policy.yaml"
    pass "network-policy.yaml"

    generate_service_account > "$OUTPUT_DIR/service-account.yaml"
    pass "service-account.yaml"

    generate_rbac > "$OUTPUT_DIR/rbac.yaml"
    pass "rbac.yaml"

    echo "" >&2
    echo -e "${BOLD}Wrote 6 manifests to ${OUTPUT_DIR}/${NC}" >&2
elif [[ "$APPLY" == true ]]; then
    echo -e "${BOLD}The following resources will be created:${NC}" >&2
    echo "  - Namespace: ${NAMESPACE_NAME}" >&2
    echo "  - ResourceQuota: ${NAMESPACE_NAME}-quota" >&2
    echo "  - LimitRange: ${NAMESPACE_NAME}-limits" >&2
    echo "  - NetworkPolicy: default-deny-all, allow-dns-egress" >&2
    echo "  - ServiceAccount: ${NAMESPACE_NAME}-app" >&2
    echo "  - RoleBinding: ${NAMESPACE_NAME}-admin -> group:${ADMIN_GROUP}" >&2
    echo "" >&2
    read -r -p "Apply to cluster? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        all_manifests | kubectl apply -f -
        echo "" >&2
        pass "All resources applied successfully"
    else
        warn "Aborted — no changes made"
        exit 0
    fi
else
    all_manifests
fi

echo "" >&2
echo -e "${BOLD}--- Namespace setup complete ---${NC}" >&2
echo "" >&2
