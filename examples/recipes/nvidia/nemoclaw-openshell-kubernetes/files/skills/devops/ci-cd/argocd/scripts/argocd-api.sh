#!/usr/bin/env bash
#
# ArgoCD API Helper Functions
# Usage: source this file or run directly with commands
#
# Environment variables:
#   ARGOCD_SERVER      - ArgoCD server (required)
#   ARGOCD_AUTH_TOKEN  - Bearer token (required)
#   ARGOCD_INSECURE    - Set to "true" to skip TLS verification
#

set -euo pipefail

# Base configuration
ARGOCD_SERVER="${ARGOCD_SERVER:-}"
ARGOCD_AUTH_TOKEN="${ARGOCD_AUTH_TOKEN:-}"
ARGOCD_INSECURE="${ARGOCD_INSECURE:-false}"

# Validate required environment
_check_env() {
    if [[ -z "$ARGOCD_SERVER" ]]; then
        echo "Error: ARGOCD_SERVER not set" >&2
        return 1
    fi
    if [[ -z "$ARGOCD_AUTH_TOKEN" ]]; then
        echo "Error: ARGOCD_AUTH_TOKEN not set" >&2
        return 1
    fi
}

# Build curl options
_curl_opts() {
    local opts=(-s -H "Authorization: Bearer $ARGOCD_AUTH_TOKEN" -H "Content-Type: application/json")
    if [[ "$ARGOCD_INSECURE" == "true" ]]; then
        opts+=(-k)
    fi
    echo "${opts[@]}"
}

# Base API call
argocd_api() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"

    _check_env

    local url="https://$ARGOCD_SERVER/api/v1$endpoint"
    local opts
    read -ra opts <<< "$(_curl_opts)"

    if [[ -n "$data" ]]; then
        curl "${opts[@]}" -X "$method" "$url" -d "$data"
    else
        curl "${opts[@]}" -X "$method" "$url"
    fi
}

# ============================================================================
# Application Operations
# ============================================================================

# List all applications
# Usage: argocd_app_list [project]
argocd_app_list() {
    local project="${1:-}"
    local endpoint="/applications"
    if [[ -n "$project" ]]; then
        endpoint="/applications?projects=$project"
    fi
    argocd_api GET "$endpoint" | jq -r '.items[]? | "\(.metadata.name)\t\(.status.health.status)\t\(.status.sync.status)"'
}

# Get application details
# Usage: argocd_app_get <name>
argocd_app_get() {
    local name="$1"
    argocd_api GET "/applications/$name"
}

# Get application status summary
# Usage: argocd_app_status <name>
argocd_app_status() {
    local name="$1"
    argocd_api GET "/applications/$name" | jq '{
        name: .metadata.name,
        health: .status.health.status,
        sync: .status.sync.status,
        revision: .status.sync.revision,
        operationState: .status.operationState.phase
    }'
}

# Create application
# Usage: argocd_app_create <name> <repo> <path> <dest_server> <dest_namespace> [project]
argocd_app_create() {
    local name="$1"
    local repo="$2"
    local path="$3"
    local dest_server="$4"
    local dest_namespace="$5"
    local project="${6:-default}"

    local payload
    payload=$(cat <<EOF
{
    "metadata": {"name": "$name", "namespace": "argocd"},
    "spec": {
        "project": "$project",
        "source": {
            "repoURL": "$repo",
            "path": "$path",
            "targetRevision": "HEAD"
        },
        "destination": {
            "server": "$dest_server",
            "namespace": "$dest_namespace"
        }
    }
}
EOF
)
    argocd_api POST "/applications" "$payload"
}

# Create application with auto-sync
# Usage: argocd_app_create_autosync <name> <repo> <path> <dest_server> <dest_namespace> [project]
argocd_app_create_autosync() {
    local name="$1"
    local repo="$2"
    local path="$3"
    local dest_server="$4"
    local dest_namespace="$5"
    local project="${6:-default}"

    local payload
    payload=$(cat <<EOF
{
    "metadata": {"name": "$name", "namespace": "argocd"},
    "spec": {
        "project": "$project",
        "source": {
            "repoURL": "$repo",
            "path": "$path",
            "targetRevision": "HEAD"
        },
        "destination": {
            "server": "$dest_server",
            "namespace": "$dest_namespace"
        },
        "syncPolicy": {
            "automated": {"prune": true, "selfHeal": true},
            "syncOptions": ["CreateNamespace=true"]
        }
    }
}
EOF
)
    argocd_api POST "/applications?upsert=true" "$payload"
}

# Sync application
# Usage: argocd_app_sync <name> [revision] [prune] [dry_run]
argocd_app_sync() {
    local name="$1"
    local revision="${2:-HEAD}"
    local prune="${3:-true}"
    local dry_run="${4:-false}"

    local payload
    payload=$(cat <<EOF
{
    "revision": "$revision",
    "prune": $prune,
    "dryRun": $dry_run,
    "strategy": {"hook": {}}
}
EOF
)
    argocd_api POST "/applications/$name/sync" "$payload"
}

# Sync application and wait for health
# Usage: argocd_app_sync_wait <name> [timeout_seconds]
argocd_app_sync_wait() {
    local name="$1"
    local timeout="${2:-300}"
    local start_time end_time

    echo "Syncing application: $name"
    argocd_app_sync "$name" >/dev/null

    echo "Waiting for health (timeout: ${timeout}s)..."
    start_time=$(date +%s)
    end_time=$((start_time + timeout))

    while true; do
        local status
        status=$(argocd_app_status "$name")
        local health sync
        health=$(echo "$status" | jq -r '.health')
        sync=$(echo "$status" | jq -r '.sync')

        echo "  Health: $health, Sync: $sync"

        if [[ "$health" == "Healthy" && "$sync" == "Synced" ]]; then
            echo "Application is healthy and synced!"
            return 0
        fi

        if [[ "$health" == "Degraded" ]]; then
            echo "Application is degraded!" >&2
            return 1
        fi

        if [[ $(date +%s) -gt $end_time ]]; then
            echo "Timeout waiting for application health" >&2
            return 1
        fi

        sleep 5
    done
}

# Rollback application
# Usage: argocd_app_rollback <name> <history_id>
argocd_app_rollback() {
    local name="$1"
    local history_id="$2"

    local payload='{"id": '"$history_id"', "prune": true}'
    argocd_api POST "/applications/$name/rollback" "$payload"
}

# Delete application
# Usage: argocd_app_delete <name> [cascade]
argocd_app_delete() {
    local name="$1"
    local cascade="${2:-true}"
    argocd_api DELETE "/applications/$name?cascade=$cascade"
}

# Terminate running operation
# Usage: argocd_app_terminate <name>
argocd_app_terminate() {
    local name="$1"
    argocd_api DELETE "/applications/$name/operation"
}

# Get application resource tree
# Usage: argocd_app_resources <name>
argocd_app_resources() {
    local name="$1"
    argocd_api GET "/applications/$name/resource-tree" | jq '.nodes[]? | {kind: .kind, name: .name, namespace: .namespace, health: .health.status}'
}

# ============================================================================
# Repository Operations
# ============================================================================

# List repositories
argocd_repo_list() {
    argocd_api GET "/repositories" | jq -r '.items[]? | "\(.repo)\t\(.type)\t\(.connectionState.status)"'
}

# Add repository
# Usage: argocd_repo_add <url> <username> <password> [type]
argocd_repo_add() {
    local url="$1"
    local username="$2"
    local password="$3"
    local type="${4:-git}"

    local payload
    payload=$(cat <<EOF
{
    "repo": "$url",
    "type": "$type",
    "username": "$username",
    "password": "$password"
}
EOF
)
    argocd_api POST "/repositories?upsert=true" "$payload"
}

# Delete repository
# Usage: argocd_repo_delete <url>
argocd_repo_delete() {
    local url="$1"
    local encoded
    encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$url', safe=''))")
    argocd_api DELETE "/repositories/$encoded"
}

# ============================================================================
# Cluster Operations
# ============================================================================

# List clusters
argocd_cluster_list() {
    argocd_api GET "/clusters" | jq -r '.items[]? | "\(.name)\t\(.server)\t\(.connectionState.status)"'
}

# Get cluster
# Usage: argocd_cluster_get <name_or_server>
argocd_cluster_get() {
    local id="$1"
    local encoded
    encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$id', safe=''))")
    argocd_api GET "/clusters/$encoded"
}

# ============================================================================
# Project Operations
# ============================================================================

# List projects
argocd_proj_list() {
    argocd_api GET "/projects" | jq -r '.items[]? | .metadata.name'
}

# Get project
# Usage: argocd_proj_get <name>
argocd_proj_get() {
    local name="$1"
    argocd_api GET "/projects/$name"
}

# ============================================================================
# Account Operations
# ============================================================================

# Get current user info
argocd_whoami() {
    argocd_api GET "/session/userinfo"
}

# Check permission
# Usage: argocd_can_i <action> <resource> [subresource]
argocd_can_i() {
    local action="$1"
    local resource="$2"
    local subresource="${3:-*}"
    argocd_api GET "/account/can-i/$resource/$action/$subresource"
}

# ============================================================================
# Utility Functions
# ============================================================================

# Get API version
argocd_version() {
    _check_env
    local opts
    read -ra opts <<< "$(_curl_opts)"
    curl "${opts[@]}" "https://$ARGOCD_SERVER/api/version"
}

# Health check
argocd_health() {
    _check_env
    local opts
    read -ra opts <<< "$(_curl_opts)"
    if curl "${opts[@]}" -o /dev/null -w "%{http_code}" "https://$ARGOCD_SERVER/api/version" 2>/dev/null | grep -q "200"; then
        echo "ArgoCD API is healthy"
        return 0
    else
        echo "ArgoCD API is not responding" >&2
        return 1
    fi
}

# Login and get token (for initial setup)
# Usage: argocd_login <username> <password>
argocd_login() {
    local username="$1"
    local password="$2"

    if [[ -z "$ARGOCD_SERVER" ]]; then
        echo "Error: ARGOCD_SERVER not set" >&2
        return 1
    fi

    local opts=(-s -H "Content-Type: application/json")
    if [[ "$ARGOCD_INSECURE" == "true" ]]; then
        opts+=(-k)
    fi

    local payload='{"username": "'"$username"'", "password": "'"$password"'"}'
    local response
    response=$(curl "${opts[@]}" -X POST "https://$ARGOCD_SERVER/api/v1/session" -d "$payload")

    local token
    token=$(echo "$response" | jq -r '.token // empty')

    if [[ -n "$token" ]]; then
        echo "$token"
    else
        echo "Login failed: $(echo "$response" | jq -r '.message // .error // "Unknown error"')" >&2
        return 1
    fi
}

# ============================================================================
# CLI Entry Point
# ============================================================================

# If run directly (not sourced), execute command
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ $# -lt 1 ]]; then
        cat <<EOF
ArgoCD API Helper Script

Usage: $0 <command> [args...]

Environment:
  ARGOCD_SERVER       ArgoCD server address (required)
  ARGOCD_AUTH_TOKEN   Bearer token (required for most commands)
  ARGOCD_INSECURE     Set to "true" to skip TLS verification

Commands:
  # Application commands
  app-list [project]                           List applications
  app-get <name>                               Get application details
  app-status <name>                            Get application status
  app-create <name> <repo> <path> <server> <ns> [project]  Create application
  app-create-autosync <name> <repo> <path> <server> <ns> [project]  Create with auto-sync
  app-sync <name> [revision] [prune] [dry_run] Sync application
  app-sync-wait <name> [timeout]               Sync and wait for health
  app-rollback <name> <history_id>             Rollback application
  app-delete <name> [cascade]                  Delete application
  app-terminate <name>                         Terminate operation
  app-resources <name>                         List application resources

  # Repository commands
  repo-list                                    List repositories
  repo-add <url> <username> <password> [type]  Add repository
  repo-delete <url>                            Delete repository

  # Cluster commands
  cluster-list                                 List clusters
  cluster-get <name_or_server>                 Get cluster

  # Project commands
  proj-list                                    List projects
  proj-get <name>                              Get project

  # Account commands
  whoami                                       Get current user info
  can-i <action> <resource> [subresource]      Check permission

  # Utility commands
  version                                      Get API version
  health                                       Check API health
  login <username> <password>                  Login and print token

Examples:
  $0 health
  $0 app-list
  $0 app-sync myapp
  $0 app-sync-wait myapp 300
  $0 login admin secret
EOF
        exit 0
    fi

    command="$1"
    shift

    case "$command" in
        app-list)        argocd_app_list "$@" ;;
        app-get)         argocd_app_get "$@" ;;
        app-status)      argocd_app_status "$@" ;;
        app-create)      argocd_app_create "$@" ;;
        app-create-autosync) argocd_app_create_autosync "$@" ;;
        app-sync)        argocd_app_sync "$@" ;;
        app-sync-wait)   argocd_app_sync_wait "$@" ;;
        app-rollback)    argocd_app_rollback "$@" ;;
        app-delete)      argocd_app_delete "$@" ;;
        app-terminate)   argocd_app_terminate "$@" ;;
        app-resources)   argocd_app_resources "$@" ;;
        repo-list)       argocd_repo_list ;;
        repo-add)        argocd_repo_add "$@" ;;
        repo-delete)     argocd_repo_delete "$@" ;;
        cluster-list)    argocd_cluster_list ;;
        cluster-get)     argocd_cluster_get "$@" ;;
        proj-list)       argocd_proj_list ;;
        proj-get)        argocd_proj_get "$@" ;;
        whoami)          argocd_whoami ;;
        can-i)           argocd_can_i "$@" ;;
        version)         argocd_version ;;
        health)          argocd_health ;;
        login)           argocd_login "$@" ;;
        *)
            echo "Unknown command: $command" >&2
            exit 1
            ;;
    esac
fi
