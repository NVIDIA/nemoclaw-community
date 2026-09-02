#!/usr/bin/env bash
set -euo pipefail

# Docker image audit script
# Checks image size, layers, base image, security, and suggests optimizations

VERSION="0.1.0"
IMAGE_NAME=""
NO_SCAN=false

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") [options] <image-name>

Audit a Docker image for size, layers, security, and optimization opportunities.

Arguments:
  <image-name>         Name (and optional tag) of the Docker image to audit

Options:
  --no-scan            Skip security vulnerability scan
  -h, --help           Show this help
  -v, --version        Show version

Examples:
  $(basename "$0") myapp:latest
  $(basename "$0") --no-scan nginx:1.25
  $(basename "$0") python:3.12-slim
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-scan) NO_SCAN=true; shift ;;
        -h|--help) usage ;;
        -v|--version) echo "image-audit.sh v${VERSION}"; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; exit 1 ;;
        *) IMAGE_NAME="$1"; shift ;;
    esac
done

if [[ -z "$IMAGE_NAME" ]]; then
    echo "Error: Provide an image name" >&2
    echo "Run with --help for usage" >&2
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

# Verify image exists locally
if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo "Image '$IMAGE_NAME' not found locally. Attempting to pull..."
    if ! docker pull "$IMAGE_NAME" 2>/dev/null; then
        fail "Could not find or pull image: $IMAGE_NAME"
        exit 1
    fi
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Image Audit: ${IMAGE_NAME}${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
SUGGESTIONS=()

# --- IMAGE SIZE ---
section "IMAGE SIZE"

size_bytes=$(docker image inspect "$IMAGE_NAME" --format '{{.Size}}' 2>/dev/null || echo "0")
if [[ "$size_bytes" -gt 0 ]]; then
    if [[ "$size_bytes" -ge 1073741824 ]]; then
        size_human="$(awk "BEGIN {printf \"%.2f\", $size_bytes / 1073741824}") GB"
    elif [[ "$size_bytes" -ge 1048576 ]]; then
        size_human="$(awk "BEGIN {printf \"%.2f\", $size_bytes / 1048576}") MB"
    else
        size_human="$(awk "BEGIN {printf \"%.2f\", $size_bytes / 1024}") KB"
    fi
    echo "  Total size: $size_human ($size_bytes bytes)"

    if [[ "$size_bytes" -gt 524288000 ]]; then
        fail "Image exceeds 500 MB"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        SUGGESTIONS+=("Image > 500MB: Consider multi-stage build or smaller base image (e.g., alpine, distroless)")
    elif [[ "$size_bytes" -gt 209715200 ]]; then
        warn "Image exceeds 200 MB"
        WARN_COUNT=$((WARN_COUNT + 1))
        SUGGESTIONS+=("Image > 200MB: Consider whether a slimmer base image would work")
    else
        pass "Image size is reasonable"
        PASS_COUNT=$((PASS_COUNT + 1))
    fi
else
    warn "Could not determine image size"
    WARN_COUNT=$((WARN_COUNT + 1))
fi

# --- LAYER BREAKDOWN ---
section "LAYER BREAKDOWN"

docker history "$IMAGE_NAME" --format "table {{.CreatedBy}}\t{{.Size}}\t{{.CreatedAt}}" --no-trunc 2>/dev/null | head -40 || warn "Could not retrieve image history"

layer_count=$(docker history "$IMAGE_NAME" --format "{{.Size}}" 2>/dev/null | wc -l | tr -d ' ')
echo ""
echo "  Total layers: $layer_count"

if [[ "$layer_count" -gt 30 ]]; then
    fail "Too many layers ($layer_count) -- consider combining RUN commands"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    SUGGESTIONS+=("Many layers ($layer_count): Combine RUN commands with && to reduce layer count")
elif [[ "$layer_count" -gt 15 ]]; then
    warn "High layer count ($layer_count)"
    WARN_COUNT=$((WARN_COUNT + 1))
    SUGGESTIONS+=("Elevated layer count ($layer_count): Consider combining related RUN commands")
else
    pass "Layer count is reasonable ($layer_count)"
    PASS_COUNT=$((PASS_COUNT + 1))
fi

# --- LARGEST LAYERS ---
section "LARGEST LAYERS (top 5)"

docker history "$IMAGE_NAME" --format "{{.Size}}\t{{.CreatedBy}}" --no-trunc 2>/dev/null | \
    grep -v "^0B" | \
    sort -t$'\t' -k1 -h -r 2>/dev/null | \
    head -5 | \
    while IFS=$'\t' read -r lsize lcmd; do
        lcmd_short=$(echo "$lcmd" | cut -c1-100)
        echo -e "  ${YELLOW}${lsize}${NC}  ${lcmd_short}"
    done || warn "Could not determine largest layers"

# Check for large apt/apk layers
apt_layers=$(docker history "$IMAGE_NAME" --format "{{.CreatedBy}}" --no-trunc 2>/dev/null | grep -c "apt-get install\|apk add" || true)
if [[ "$apt_layers" -gt 0 ]]; then
    # Check if cleanup is present
    has_cleanup=$(docker history "$IMAGE_NAME" --format "{{.CreatedBy}}" --no-trunc 2>/dev/null | grep -c "rm -rf /var/lib/apt\|--no-cache" || true)
    if [[ "$has_cleanup" -eq 0 ]]; then
        SUGGESTIONS+=("Package install layers detected without cleanup: Add --no-install-recommends and rm -rf /var/lib/apt/lists/* (apt) or use --no-cache (apk)")
    fi
fi

# --- BASE IMAGE ---
section "BASE IMAGE"

# Try to extract base image from labels or config
base_image=""

# Check for common labels
for label in "org.opencontainers.image.base.name" "maintainer" "org.label-schema.docker.base-image"; do
    value=$(docker image inspect "$IMAGE_NAME" --format "{{index .Config.Labels \"$label\"}}" 2>/dev/null || echo "")
    if [[ -n "$value" && "$value" != "<no value>" ]]; then
        echo "  Label ($label): $value"
        if [[ "$label" == "org.opencontainers.image.base.name" ]]; then
            base_image="$value"
        fi
    fi
done

# Try to identify base from history
first_layer=$(docker history "$IMAGE_NAME" --format "{{.CreatedBy}}" --no-trunc 2>/dev/null | tail -1 || echo "")
if [[ -n "$first_layer" ]]; then
    echo "  First layer: $(echo "$first_layer" | cut -c1-120)"
fi

if [[ -z "$base_image" ]]; then
    # Try to identify from OS release info in the image
    os_info=$(docker run --rm --entrypoint="" "$IMAGE_NAME" cat /etc/os-release 2>/dev/null | head -5 || echo "")
    if [[ -n "$os_info" ]]; then
        echo "  OS info detected:"
        echo "$os_info" | while read -r line; do echo "    $line"; done
    else
        warn "Could not determine base image"
    fi
fi

# --- IMAGE TAG CHECK ---
section "IMAGE TAG"

tag="${IMAGE_NAME##*:}"
if [[ "$tag" == "$IMAGE_NAME" || "$tag" == "latest" ]]; then
    warn "Image uses :latest or no tag"
    WARN_COUNT=$((WARN_COUNT + 1))
    SUGGESTIONS+=("Using :latest tag: Pin to a specific version for reproducible builds")
else
    pass "Image uses specific tag: $tag"
    PASS_COUNT=$((PASS_COUNT + 1))
fi

# --- SECURITY SCAN ---
section "SECURITY SCAN"

if [[ "$NO_SCAN" == true ]]; then
    echo "  Skipped (--no-scan flag)"
else
    scan_ran=false

    if command -v trivy &>/dev/null; then
        echo "  Running trivy scan..."
        echo ""
        trivy image --severity HIGH,CRITICAL --format table "$IMAGE_NAME" 2>/dev/null || warn "Trivy scan failed"
        scan_ran=true
    elif docker scout version &>/dev/null 2>&1; then
        echo "  Running docker scout scan..."
        echo ""
        docker scout quickview "$IMAGE_NAME" 2>/dev/null || warn "Docker Scout scan failed"
        scan_ran=true
    fi

    if [[ "$scan_ran" == false ]]; then
        warn "No security scanner available"
        echo "  Install one of the following for vulnerability scanning:"
        echo "    - trivy: https://aquasecurity.github.io/trivy/"
        echo "    - docker scout: docker scout --help (included in Docker Desktop)"
    fi
fi

# --- OPTIMIZATION SUGGESTIONS ---
section "OPTIMIZATION SUGGESTIONS"

if [[ ${#SUGGESTIONS[@]} -eq 0 ]]; then
    pass "No optimization issues found"
else
    for suggestion in "${SUGGESTIONS[@]}"; do
        echo -e "  ${YELLOW}→${NC} $suggestion"
    done
fi

# --- SUMMARY ---
section "SUMMARY"

echo -e "  ${GREEN}PASS: ${PASS_COUNT}${NC}  ${YELLOW}WARN: ${WARN_COUNT}${NC}  ${RED}FAIL: ${FAIL_COUNT}${NC}"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    echo ""
    fail "Image has issues that should be addressed"
    exit 1
elif [[ "$WARN_COUNT" -gt 0 ]]; then
    echo ""
    warn "Image has warnings worth reviewing"
    exit 0
else
    echo ""
    pass "Image looks good"
    exit 0
fi
