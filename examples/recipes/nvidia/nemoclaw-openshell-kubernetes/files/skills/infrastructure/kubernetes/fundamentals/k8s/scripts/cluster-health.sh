#!/usr/bin/env bash
set -euo pipefail

# Cluster health overview script
# Provides an at-a-glance view of Kubernetes cluster state

VERSION="0.1.0"
CONTEXT=""
WATCH_MODE=false

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") [--context <context>] [--watch]

Produce a cluster health overview: node status, resource utilization,
unhealthy pods, pending PVCs, and recent warning events.

Options:
  --context CTX    Kubernetes context to use (default: current)
  --watch          Continuous monitoring (refresh every 30s)
  -h, --help       Show this help
  -v, --version    Show version

Examples:
  $(basename "$0")
  $(basename "$0") --context production-cluster
  $(basename "$0") --watch
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --context) CONTEXT="$2"; shift 2 ;;
        --watch) WATCH_MODE=true; shift ;;
        -h|--help) usage ;;
        -v|--version) echo "cluster-health.sh v${VERSION}"; exit 0 ;;
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

CTX_FLAG=""
if [[ -n "$CONTEXT" ]]; then
    CTX_FLAG="--context $CONTEXT"
fi

section() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ $1 ━━━${NC}"
}

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }

run_health_check() {
    local current_ctx
    current_ctx=$(kubectl config current-context $CTX_FLAG 2>/dev/null || echo "unknown")

    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║  Cluster Health Report                   ${NC}"
    echo -e "${BOLD}║  Context: ${current_ctx}${NC}"
    echo -e "${BOLD}║  Time:    $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"

    # --- NODES ---
    section "NODES"

    local nodes_json
    nodes_json=$(kubectl get nodes $CTX_FLAG -o json 2>/dev/null) || {
        fail "Cannot connect to cluster"
        return 1
    }

    local node_summary
    node_summary=$(echo "$nodes_json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
nodes = d.get('items', [])
total = len(nodes)
ready = 0
not_ready = []
for n in nodes:
    name = n['metadata']['name']
    conditions = {c['type']: c['status'] for c in n.get('status', {}).get('conditions', [])}
    if conditions.get('Ready') == 'True':
        ready += 1
    else:
        not_ready.append(name)
    pressures = []
    for p in ['MemoryPressure', 'DiskPressure', 'PIDPressure']:
        if conditions.get(p) == 'True':
            pressures.append(p)
    if pressures:
        not_ready.append(f'{name} ({', '.join(pressures)})')

print(f'TOTAL:{total}')
print(f'READY:{ready}')
print(f'NOT_READY:{','.join(not_ready) if not_ready else 'none'}')
" 2>/dev/null)

    local total ready not_ready
    total=$(echo "$node_summary" | grep TOTAL | cut -d: -f2)
    ready=$(echo "$node_summary" | grep READY: | cut -d: -f2)
    not_ready=$(echo "$node_summary" | grep NOT_READY | cut -d: -f2)

    if [[ "$total" == "$ready" ]]; then
        pass "All $total nodes Ready"
    else
        fail "$ready/$total nodes Ready"
        if [[ "$not_ready" != "none" ]]; then
            echo "     Not ready: $not_ready"
        fi
    fi

    # --- RESOURCE UTILIZATION ---
    section "RESOURCE UTILIZATION"

    # Try kubectl top nodes (requires metrics-server)
    if kubectl top nodes $CTX_FLAG &>/dev/null 2>&1; then
        kubectl top nodes $CTX_FLAG 2>/dev/null | while IFS= read -r line; do
            echo "  $line"
        done
    else
        warn "Metrics Server not available — showing requests vs allocatable"
        echo "$nodes_json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
total_cpu_alloc = 0
total_mem_alloc = 0

def parse_cpu(s):
    if s.endswith('m'):
        return int(s[:-1])
    return int(s) * 1000

def parse_mem(s):
    units = {'Ki': 1024, 'Mi': 1024**2, 'Gi': 1024**3, 'Ti': 1024**4}
    for u, m in units.items():
        if s.endswith(u):
            return int(s[:-len(u)]) * m
    return int(s)

for n in d.get('items', []):
    alloc = n.get('status', {}).get('allocatable', {})
    cpu = alloc.get('cpu', '0')
    mem = alloc.get('memory', '0Ki')
    total_cpu_alloc += parse_cpu(cpu)
    total_mem_alloc += parse_mem(mem)

print(f'  Allocatable: {total_cpu_alloc}m CPU, {total_mem_alloc // (1024**3)}Gi memory')
" 2>/dev/null || warn "Could not parse node resources"
    fi

    # --- UNHEALTHY PODS ---
    section "UNHEALTHY PODS"

    local unhealthy
    unhealthy=$(kubectl get pods $CTX_FLAG --all-namespaces \
        --field-selector 'status.phase!=Running,status.phase!=Succeeded' \
        --no-headers 2>/dev/null || echo "")

    if [[ -z "$unhealthy" ]]; then
        pass "No unhealthy pods across all namespaces"
    else
        local count
        count=$(echo "$unhealthy" | wc -l | tr -d ' ')
        fail "$count unhealthy pod(s) found:"
        echo ""

        # Group by status
        echo "$unhealthy" | python3 -c "
import sys
from collections import defaultdict
groups = defaultdict(list)
for line in sys.stdin:
    parts = line.split()
    if len(parts) >= 4:
        ns, name, ready, status = parts[0], parts[1], parts[2], parts[3]
        groups[status].append(f'    {ns}/{name} ({ready})')

for status in sorted(groups):
    print(f'  {status}:')
    for pod in groups[status][:10]:
        print(pod)
    if len(groups[status]) > 10:
        print(f'    ... and {len(groups[status])-10} more')
" 2>/dev/null || echo "$unhealthy" | head -20 | while IFS= read -r line; do echo "  $line"; done
    fi

    # --- PENDING PVCs ---
    section "PENDING PVCs"

    local pending_pvcs
    pending_pvcs=$(kubectl get pvc $CTX_FLAG --all-namespaces \
        --field-selector 'status.phase=Pending' --no-headers 2>/dev/null || echo "")

    if [[ -z "$pending_pvcs" ]]; then
        pass "No pending PVCs"
    else
        local pvc_count
        pvc_count=$(echo "$pending_pvcs" | wc -l | tr -d ' ')
        warn "$pvc_count pending PVC(s):"
        echo "$pending_pvcs" | head -10 | while IFS= read -r line; do
            echo "    $line"
        done
    fi

    # --- RECENT WARNING EVENTS ---
    section "WARNING EVENTS (last 15m)"

    local warnings
    warnings=$(kubectl get events $CTX_FLAG --all-namespaces \
        --field-selector type=Warning \
        --sort-by=.lastTimestamp 2>/dev/null | tail -15 || echo "")

    if [[ -z "$warnings" || "$warnings" == "No resources found"* ]]; then
        pass "No recent warning events"
    else
        echo "$warnings" | while IFS= read -r line; do
            echo "  $line"
        done
    fi

    # --- DEPLOYMENT HEALTH ---
    section "DEPLOYMENT REPLICA MISMATCHES"

    local mismatches
    mismatches=$(kubectl get deployments $CTX_FLAG --all-namespaces --no-headers 2>/dev/null | \
        awk '$3 != $4 || $4 != $5 {print "  "$1"/"$2" ready="$3" up-to-date="$4" available="$5}' || echo "")

    if [[ -z "$mismatches" ]]; then
        pass "All deployments have desired replicas"
    else
        local mismatch_count
        mismatch_count=$(echo "$mismatches" | wc -l | tr -d ' ')
        warn "$mismatch_count deployment(s) with replica mismatch:"
        echo "$mismatches" | head -10
    fi

    echo ""
    echo -e "${BOLD}━━━ Health check complete ━━━${NC}"
    echo ""
}

# Main
if [[ "$WATCH_MODE" == true ]]; then
    while true; do
        clear
        run_health_check
        echo "Refreshing in 30s... (Ctrl+C to stop)"
        sleep 30
    done
else
    run_health_check
fi
