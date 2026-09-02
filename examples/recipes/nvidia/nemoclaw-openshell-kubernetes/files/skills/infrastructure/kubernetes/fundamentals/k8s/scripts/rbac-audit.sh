#!/usr/bin/env bash
set -euo pipefail

# RBAC audit script for Kubernetes
# Finds security issues in roles, bindings, and service account usage

VERSION="0.1.0"
NAMESPACE=""
WIDE=false

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") [--namespace <ns>] [--wide]

Audit RBAC permissions across the cluster to find security issues such as
overly broad roles, cluster-admin bindings, and default service account usage.

Options:
  --namespace NS   Scope audit to a single namespace (default: all namespaces)
  --wide           Show full resource details instead of summary
  -h, --help       Show this help
  -v, --version    Show version

Examples:
  $(basename "$0")
  $(basename "$0") --namespace production
  $(basename "$0") --wide
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --wide) WIDE=true; shift ;;
        -h|--help) usage ;;
        -v|--version) echo "rbac-audit.sh v${VERSION}"; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; exit 1 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if ! command -v kubectl &>/dev/null; then
    echo "Error: kubectl not found in PATH" >&2
    exit 1
fi
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found in PATH (required for JSON parsing)" >&2
    exit 1
fi

NS_FLAG=""
NS_LABEL=""
if [[ -n "$NAMESPACE" ]]; then
    NS_FLAG="-n $NAMESPACE"
    NS_LABEL="namespace $NAMESPACE"
else
    NS_LABEL="all namespaces"
fi

section() {
    echo ""
    echo -e "${BOLD}${CYAN}--- $1 ---${NC}"
}

pass() { echo -e "  ${GREEN}+${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}x${NC} $1"; }

TOTAL_PASS=0
TOTAL_WARN=0
TOTAL_FAIL=0

count_pass() { ((TOTAL_PASS++)) || true; pass "$1"; }
count_warn() { ((TOTAL_WARN++)) || true; warn "$1"; }
count_fail() { ((TOTAL_FAIL++)) || true; fail "$1"; }

echo ""
echo -e "${BOLD}======================================${NC}"
echo -e "${BOLD}  RBAC Audit Report${NC}"
echo -e "${BOLD}  Scope: ${NS_LABEL}${NC}"
echo -e "${BOLD}  Time:  $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${BOLD}======================================${NC}"

# --- CLUSTER-ADMIN BINDINGS ---
section "CLUSTER-ADMIN BINDINGS"

cluster_admin_bindings=$(kubectl get clusterrolebindings -o json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
results = []
for item in d.get('items', []):
    ref = item.get('roleRef', {})
    if ref.get('name') == 'cluster-admin':
        name = item['metadata']['name']
        subjects = item.get('subjects', [])
        for s in subjects:
            kind = s.get('kind', '?')
            sname = s.get('name', '?')
            sns = s.get('namespace', '')
            is_system = sname.startswith('system:') or name.startswith('system:')
            tag = 'SYSTEM' if is_system else 'CUSTOM'
            ns_part = f' (ns={sns})' if sns else ''
            results.append(f'{tag}|{name}|{kind}:{sname}{ns_part}')
print('\n'.join(results))
" 2>/dev/null) || cluster_admin_bindings=""

if [[ -z "$cluster_admin_bindings" ]]; then
    count_pass "No cluster-admin bindings found"
else
    custom_count=0
    system_count=0
    while IFS= read -r line; do
        tag=$(echo "$line" | cut -d'|' -f1)
        binding=$(echo "$line" | cut -d'|' -f2)
        subject=$(echo "$line" | cut -d'|' -f3)
        if [[ "$tag" == "CUSTOM" ]]; then
            count_fail "cluster-admin binding: $binding -> $subject"
            ((custom_count++)) || true
        else
            ((system_count++)) || true
            if [[ "$WIDE" == true ]]; then
                count_pass "system cluster-admin binding: $binding -> $subject"
            fi
        fi
    done <<< "$cluster_admin_bindings"
    if [[ "$custom_count" -eq 0 ]]; then
        count_pass "No non-system cluster-admin bindings ($system_count system bindings present)"
    fi
fi

# --- WILDCARD PERMISSIONS ---
section "WILDCARD PERMISSIONS"

find_wildcard_roles() {
    local kind="$1"
    local flag="$2"
    kubectl get "$kind" $flag -o json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
for item in d.get('items', []):
    name = item['metadata']['name']
    ns = item['metadata'].get('namespace', '')
    if name.startswith('system:'):
        continue
    for rule in item.get('rules', []):
        verbs = rule.get('verbs', [])
        resources = rule.get('resources', [])
        if '*' in verbs or '*' in resources:
            ns_part = f' (ns={ns})' if ns else ''
            v = ','.join(verbs)
            r = ','.join(resources)
            print(f'{name}{ns_part}|verbs=[{v}] resources=[{r}]')
" 2>/dev/null || echo ""
}

wildcard_cluster=$(find_wildcard_roles "clusterroles" "")
wildcard_roles=""
if [[ -n "$NAMESPACE" ]]; then
    wildcard_roles=$(find_wildcard_roles "roles" "-n $NAMESPACE")
else
    wildcard_roles=$(find_wildcard_roles "roles" "--all-namespaces")
fi

wildcard_all="${wildcard_cluster}${wildcard_cluster:+$'\n'}${wildcard_roles}"
wildcard_all=$(echo "$wildcard_all" | sed '/^$/d')

if [[ -z "$wildcard_all" ]]; then
    count_pass "No non-system roles with wildcard permissions"
else
    while IFS= read -r line; do
        role_name=$(echo "$line" | cut -d'|' -f1)
        detail=$(echo "$line" | cut -d'|' -f2)
        if [[ "$WIDE" == true ]]; then
            count_warn "Wildcard role: $role_name -> $detail"
        else
            count_warn "Wildcard role: $role_name"
        fi
    done <<< "$wildcard_all"
fi

# --- DEFAULT SERVICE ACCOUNT USAGE ---
section "DEFAULT SERVICE ACCOUNT USAGE"

if [[ -n "$NAMESPACE" ]]; then
    default_sa_pods=$(kubectl get pods -n "$NAMESPACE" -o json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
for pod in d.get('items', []):
    sa = pod['spec'].get('serviceAccountName', 'default')
    if sa == 'default':
        name = pod['metadata']['name']
        ns = pod['metadata'].get('namespace', '')
        print(f'{ns}/{name}')
" 2>/dev/null) || default_sa_pods=""
else
    default_sa_pods=$(kubectl get pods --all-namespaces -o json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
for pod in d.get('items', []):
    sa = pod['spec'].get('serviceAccountName', 'default')
    ns = pod['metadata'].get('namespace', '')
    if sa == 'default' and ns not in ('kube-system', 'kube-public', 'kube-node-lease'):
        name = pod['metadata']['name']
        print(f'{ns}/{name}')
" 2>/dev/null) || default_sa_pods=""
fi

if [[ -z "$default_sa_pods" ]]; then
    count_pass "No pods using the default service account"
else
    pod_count=$(echo "$default_sa_pods" | wc -l | tr -d ' ')
    if [[ "$WIDE" == true ]]; then
        while IFS= read -r line; do
            count_warn "Pod using default SA: $line"
        done <<< "$default_sa_pods"
    else
        count_warn "$pod_count pod(s) using the default service account"
        echo "$default_sa_pods" | head -5 | while IFS= read -r line; do
            echo "       $line"
        done
        if [[ "$pod_count" -gt 5 ]]; then
            echo "       ... and $((pod_count - 5)) more"
        fi
    fi
fi

# --- SECRETS ACCESS ---
section "SECRETS ACCESS"

find_secrets_access() {
    local kind="$1"
    local flag="$2"
    kubectl get "$kind" $flag -o json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
for item in d.get('items', []):
    name = item['metadata']['name']
    ns = item['metadata'].get('namespace', '')
    if name.startswith('system:'):
        continue
    for rule in item.get('rules', []):
        resources = rule.get('resources', [])
        verbs = rule.get('verbs', [])
        if 'secrets' in resources or '*' in resources:
            sensitive_verbs = [v for v in verbs if v in ('get', 'list', 'watch', '*')]
            if sensitive_verbs:
                ns_part = f' (ns={ns})' if ns else ''
                print(f'{name}{ns_part}|verbs=[{\",\".join(sensitive_verbs)}]')
" 2>/dev/null || echo ""
}

secrets_cluster=$(find_secrets_access "clusterroles" "")
secrets_roles=""
if [[ -n "$NAMESPACE" ]]; then
    secrets_roles=$(find_secrets_access "roles" "-n $NAMESPACE")
else
    secrets_roles=$(find_secrets_access "roles" "--all-namespaces")
fi

secrets_all="${secrets_cluster}${secrets_cluster:+$'\n'}${secrets_roles}"
secrets_all=$(echo "$secrets_all" | sed '/^$/d')

if [[ -z "$secrets_all" ]]; then
    count_pass "No non-system roles grant access to secrets"
else
    while IFS= read -r line; do
        role_name=$(echo "$line" | cut -d'|' -f1)
        detail=$(echo "$line" | cut -d'|' -f2)
        if [[ "$WIDE" == true ]]; then
            count_warn "Secrets access: $role_name -> $detail"
        else
            count_warn "Secrets access: $role_name"
        fi
    done <<< "$secrets_all"
fi

# --- UNUSED SERVICE ACCOUNTS ---
section "UNUSED SERVICE ACCOUNTS"

if [[ -n "$NAMESPACE" ]]; then
    unused_sas=$(python3 -c "
import subprocess, json

sa_out = subprocess.run(
    ['kubectl', 'get', 'serviceaccounts', '-n', '$NAMESPACE', '-o', 'json'],
    capture_output=True, text=True
)
pod_out = subprocess.run(
    ['kubectl', 'get', 'pods', '-n', '$NAMESPACE', '-o', 'json'],
    capture_output=True, text=True
)

sas = json.loads(sa_out.stdout)
pods = json.loads(pod_out.stdout)

sa_names = set()
for sa in sas.get('items', []):
    name = sa['metadata']['name']
    if name != 'default':
        sa_names.add(name)

used = set()
for pod in pods.get('items', []):
    sa = pod['spec'].get('serviceAccountName', 'default')
    used.add(sa)

unused = sa_names - used
for name in sorted(unused):
    print(f'$NAMESPACE/{name}')
" 2>/dev/null) || unused_sas=""
else
    unused_sas=$(python3 -c "
import subprocess, json

ns_out = subprocess.run(
    ['kubectl', 'get', 'namespaces', '-o', 'jsonpath={.items[*].metadata.name}'],
    capture_output=True, text=True
)
namespaces = ns_out.stdout.split()

for ns in namespaces:
    if ns in ('kube-system', 'kube-public', 'kube-node-lease'):
        continue
    sa_out = subprocess.run(
        ['kubectl', 'get', 'serviceaccounts', '-n', ns, '-o', 'json'],
        capture_output=True, text=True
    )
    pod_out = subprocess.run(
        ['kubectl', 'get', 'pods', '-n', ns, '-o', 'json'],
        capture_output=True, text=True
    )
    sas = json.loads(sa_out.stdout)
    pods = json.loads(pod_out.stdout)

    sa_names = set()
    for sa in sas.get('items', []):
        name = sa['metadata']['name']
        if name != 'default':
            sa_names.add(name)

    used = set()
    for pod in pods.get('items', []):
        sa_pod = pod['spec'].get('serviceAccountName', 'default')
        used.add(sa_pod)

    unused = sa_names - used
    for name in sorted(unused):
        print(f'{ns}/{name}')
" 2>/dev/null) || unused_sas=""
fi

if [[ -z "$unused_sas" ]]; then
    count_pass "No unused service accounts found"
else
    unused_count=$(echo "$unused_sas" | wc -l | tr -d ' ')
    if [[ "$WIDE" == true ]]; then
        while IFS= read -r line; do
            count_warn "Unused SA: $line"
        done <<< "$unused_sas"
    else
        count_warn "$unused_count unused service account(s)"
        echo "$unused_sas" | head -5 | while IFS= read -r line; do
            echo "       $line"
        done
        if [[ "$unused_count" -gt 5 ]]; then
            echo "       ... and $((unused_count - 5)) more"
        fi
    fi
fi

# --- SUMMARY ---
section "SUMMARY"

echo ""
echo -e "  ${GREEN}+${NC} Pass: $TOTAL_PASS"
echo -e "  ${YELLOW}!${NC} Warn: $TOTAL_WARN"
echo -e "  ${RED}x${NC} Fail: $TOTAL_FAIL"
echo ""

total_findings=$((TOTAL_WARN + TOTAL_FAIL))
if [[ "$total_findings" -eq 0 ]]; then
    echo -e "  ${GREEN}No RBAC issues found.${NC}"
elif [[ "$TOTAL_FAIL" -gt 0 ]]; then
    echo -e "  ${RED}$total_findings finding(s) require attention ($TOTAL_FAIL critical).${NC}"
else
    echo -e "  ${YELLOW}$total_findings finding(s) require attention.${NC}"
fi

echo ""
echo -e "${BOLD}--- RBAC audit complete ---${NC}"
echo ""
