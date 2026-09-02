#!/usr/bin/env bash
set -euo pipefail

# Docker Compose validation and best-practices check script
# Validates syntax, checks services, health checks, resources, networking, and volumes

VERSION="0.1.0"
COMPOSE_FILE=""

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") [options] [compose-file]

Validate a Docker Compose file and check for best practices.

Arguments:
  [compose-file]       Path to compose file (default: docker-compose.yml or compose.yaml)

Options:
  -f, --file PATH      Explicit path to compose file
  -h, --help           Show this help
  -v, --version        Show version

Examples:
  $(basename "$0")
  $(basename "$0") docker-compose.prod.yml
  $(basename "$0") -f /path/to/compose.yaml
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--file) COMPOSE_FILE="$2"; shift 2 ;;
        -h|--help) usage ;;
        -v|--version) echo "compose-check.sh v${VERSION}"; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; exit 1 ;;
        *) COMPOSE_FILE="$1"; shift ;;
    esac
done

# Auto-detect compose file if not specified
if [[ -z "$COMPOSE_FILE" ]]; then
    if [[ -f "docker-compose.yml" ]]; then
        COMPOSE_FILE="docker-compose.yml"
    elif [[ -f "docker-compose.yaml" ]]; then
        COMPOSE_FILE="docker-compose.yaml"
    elif [[ -f "compose.yml" ]]; then
        COMPOSE_FILE="compose.yml"
    elif [[ -f "compose.yaml" ]]; then
        COMPOSE_FILE="compose.yaml"
    else
        echo "Error: No compose file found in current directory" >&2
        echo "Provide a path with -f or run from a directory containing docker-compose.yml / compose.yaml" >&2
        exit 1
    fi
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "Error: File not found: $COMPOSE_FILE" >&2
    exit 1
fi

# Check dependencies
if ! command -v docker &>/dev/null; then
    echo "Error: docker not found in PATH" >&2
    exit 1
fi

section() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ $1 ━━━${NC}"
}

warn() { echo -e "${YELLOW}⚠  $1${NC}"; }
fail() { echo -e "${RED}✗  $1${NC}"; }
pass() { echo -e "${GREEN}✓  $1${NC}"; }

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Compose Check: ${COMPOSE_FILE}${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"

# --- FILE VALIDATION ---
section "FILE VALIDATION"

config_output=""
if config_output=$(docker compose -f "$COMPOSE_FILE" config 2>&1); then
    pass "Compose file syntax is valid"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    fail "Compose file has syntax errors:"
    echo "$config_output" | head -20
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo ""
    fail "Cannot proceed with further checks until syntax is fixed"
    exit 1
fi

# --- SERVICE SUMMARY ---
section "SERVICE SUMMARY"

services=$(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null || echo "")
service_count=$(echo "$services" | grep -c . || echo "0")
echo "  Services found: $service_count"
echo ""

if [[ -z "$services" ]]; then
    warn "No services defined"
    WARN_COUNT=$((WARN_COUNT + 1))
else
    for svc in $services; do
        echo -e "  ${BOLD}$svc${NC}"

        # Image or build
        svc_image=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
            python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('services',{}).get('$svc',{}); print(s.get('image',''))" 2>/dev/null || echo "")
        svc_build=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
            python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('services',{}).get('$svc',{}); b=s.get('build',{}); print(b.get('context','') if isinstance(b,dict) else b if b else '')" 2>/dev/null || echo "")

        if [[ -n "$svc_image" ]]; then
            echo "    Image: $svc_image"
        fi
        if [[ -n "$svc_build" ]]; then
            echo "    Build: $svc_build"
        fi

        # Ports
        svc_ports=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
            python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d.get('services',{}).get('$svc',{})
ports=s.get('ports',[])
for p in ports:
    if isinstance(p, dict):
        published=p.get('published','')
        target=p.get('target','')
        print(f'{published}:{target}')
    else:
        print(p)
" 2>/dev/null || echo "")

        if [[ -n "$svc_ports" ]]; then
            echo "    Ports: $(echo "$svc_ports" | tr '\n' ', ' | sed 's/,$//')"
        fi

        # Volumes
        svc_volumes=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
            python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d.get('services',{}).get('$svc',{})
vols=s.get('volumes',[])
for v in vols:
    if isinstance(v, dict):
        src=v.get('source','')
        tgt=v.get('target','')
        vtype=v.get('type','')
        print(f'{vtype}: {src} -> {tgt}')
    else:
        print(v)
" 2>/dev/null || echo "")

        if [[ -n "$svc_volumes" ]]; then
            echo "    Volumes:"
            echo "$svc_volumes" | while read -r vol; do echo "      $vol"; done
        fi

        echo ""
    done
fi

# --- HEALTH CHECKS ---
section "HEALTH CHECKS"

has_healthcheck_issue=false
for svc in $services; do
    healthcheck=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
        python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d.get('services',{}).get('$svc',{})
hc=s.get('healthcheck',{})
if hc and hc.get('test'):
    print('defined')
else:
    print('missing')
" 2>/dev/null || echo "missing")

    if [[ "$healthcheck" == "missing" ]]; then
        warn "Service '$svc' has no healthcheck defined"
        has_healthcheck_issue=true
    else
        pass "Service '$svc' has a healthcheck"
    fi
done

if [[ "$has_healthcheck_issue" == true ]]; then
    WARN_COUNT=$((WARN_COUNT + 1))
    echo ""
    echo "  Tip: Add healthcheck to services for better orchestration and depends_on conditions"
else
    PASS_COUNT=$((PASS_COUNT + 1))
fi

# --- RESOURCE LIMITS ---
section "RESOURCE LIMITS"

has_resource_issue=false
for svc in $services; do
    resources=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
        python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d.get('services',{}).get('$svc',{})
deploy=s.get('deploy',{})
res=deploy.get('resources',{})
limits=res.get('limits',{})
if limits:
    cpus=limits.get('cpus','')
    mem=limits.get('memory','')
    print(f'limits: cpus={cpus}, memory={mem}')
else:
    # Also check top-level mem_limit / cpus (legacy format)
    mem_limit=s.get('mem_limit','')
    cpus_val=s.get('cpus','')
    if mem_limit or cpus_val:
        print(f'legacy: cpus={cpus_val}, mem_limit={mem_limit}')
    else:
        print('missing')
" 2>/dev/null || echo "missing")

    if [[ "$resources" == "missing" ]]; then
        warn "Service '$svc' has no resource limits (deploy.resources.limits)"
        has_resource_issue=true
    else
        pass "Service '$svc' has resource limits ($resources)"
    fi
done

if [[ "$has_resource_issue" == true ]]; then
    WARN_COUNT=$((WARN_COUNT + 1))
    echo ""
    echo "  Tip: Set deploy.resources.limits to prevent runaway containers from consuming all host resources"
else
    PASS_COUNT=$((PASS_COUNT + 1))
fi

# --- IMAGE TAGS ---
section "IMAGE TAGS"

has_tag_issue=false
for svc in $services; do
    svc_image=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('services',{}).get('$svc',{}); print(s.get('image',''))" 2>/dev/null || echo "")

    if [[ -n "$svc_image" ]]; then
        tag="${svc_image##*:}"
        if [[ "$tag" == "$svc_image" ]]; then
            warn "Service '$svc' uses untagged image: $svc_image"
            has_tag_issue=true
        elif [[ "$tag" == "latest" ]]; then
            warn "Service '$svc' uses :latest tag: $svc_image"
            has_tag_issue=true
        else
            pass "Service '$svc' uses pinned image: $svc_image"
        fi
    fi
done

if [[ "$has_tag_issue" == true ]]; then
    WARN_COUNT=$((WARN_COUNT + 1))
    echo ""
    echo "  Tip: Pin images to specific versions for reproducible deployments"
else
    PASS_COUNT=$((PASS_COUNT + 1))
fi

# --- NETWORKING ---
section "NETWORKING"

networks=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
    python3 -c "
import sys,json
d=json.load(sys.stdin)
nets=d.get('networks',{})
for name, cfg in nets.items():
    driver=''
    if isinstance(cfg, dict):
        driver=cfg.get('driver','default')
    print(f'{name} (driver: {driver})')
" 2>/dev/null || echo "")

if [[ -n "$networks" ]]; then
    echo "  Custom networks:"
    echo "$networks" | while read -r net; do echo "    $net"; done
    pass "Custom networks defined"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo "  No custom networks (using default bridge)"
fi

# Check for host networking
has_host_network=false
for svc in $services; do
    net_mode=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('services',{}).get('$svc',{}); print(s.get('network_mode',''))" 2>/dev/null || echo "")

    if [[ "$net_mode" == "host" ]]; then
        warn "Service '$svc' uses host networking"
        has_host_network=true
    fi
done

if [[ "$has_host_network" == true ]]; then
    WARN_COUNT=$((WARN_COUNT + 1))
    echo ""
    echo "  Tip: Host networking bypasses Docker network isolation -- use only when necessary"
fi

# --- VOLUMES ---
section "VOLUMES"

named_volumes=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
    python3 -c "
import sys,json
d=json.load(sys.stdin)
vols=d.get('volumes',{})
for name, cfg in vols.items():
    driver=''
    if isinstance(cfg, dict) and cfg:
        driver=cfg.get('driver','local')
    else:
        driver='local'
    print(f'{name} (driver: {driver})')
" 2>/dev/null || echo "")

if [[ -n "$named_volumes" ]]; then
    echo "  Named volumes:"
    echo "$named_volumes" | while read -r vol; do echo "    $vol"; done
else
    echo "  No named volumes defined"
fi

# List bind mounts across services
echo ""
echo "  Bind mounts:"
has_bind_mounts=false
for svc in $services; do
    binds=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
        python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d.get('services',{}).get('$svc',{})
vols=s.get('volumes',[])
for v in vols:
    if isinstance(v, dict) and v.get('type') == 'bind':
        src=v.get('source','')
        tgt=v.get('target','')
        print(f'{src} -> {tgt}')
" 2>/dev/null || echo "")

    if [[ -n "$binds" ]]; then
        has_bind_mounts=true
        echo "$binds" | while read -r bm; do echo "    $svc: $bm"; done
    fi
done

if [[ "$has_bind_mounts" == false ]]; then
    echo "    None"
fi

# --- SUMMARY ---
section "SUMMARY"

echo -e "  ${GREEN}PASS: ${PASS_COUNT}${NC}  ${YELLOW}WARN: ${WARN_COUNT}${NC}  ${RED}FAIL: ${FAIL_COUNT}${NC}"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    echo ""
    fail "Compose file has issues that must be fixed"
    exit 1
elif [[ "$WARN_COUNT" -gt 0 ]]; then
    echo ""
    warn "Compose file has warnings worth reviewing"
    exit 0
else
    echo ""
    pass "Compose file looks good"
    exit 0
fi
