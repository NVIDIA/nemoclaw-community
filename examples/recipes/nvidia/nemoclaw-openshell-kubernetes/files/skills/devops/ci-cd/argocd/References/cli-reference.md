# ArgoCD CLI Reference

Complete command reference for the `argocd` CLI.

## Global Flags

| Flag | Description |
|------|-------------|
| `--server string` | ArgoCD server address |
| `--auth-token string` | Bearer token for authentication |
| `--client-crt string` | Client certificate file |
| `--client-crt-key string` | Client certificate key file |
| `--config string` | Path to ArgoCD config (default ~/.argocd/config) |
| `--core` | Use direct Kubernetes API (no argocd-server) |
| `--grpc-web` | Use gRPC-web protocol (for proxies/ingress) |
| `--grpc-web-root-path string` | gRPC-web root path override |
| `--header strings` | Additional headers (can be repeated) |
| `--http-retry-max int` | Max HTTP retries (default 0) |
| `--insecure` | Skip TLS verification |
| `--kube-context string` | Kubernetes context (for --core mode) |
| `--logformat string` | Log format (text, json) |
| `--loglevel string` | Log level (debug, info, warn, error) |
| `--plaintext` | Disable TLS |
| `--port-forward` | Connect via port-forward |
| `--port-forward-namespace string` | Namespace for port-forward |
| `--redis-haproxy-name string` | Redis HA proxy service name |
| `--redis-name string` | Redis service name |
| `--server-crt string` | Server certificate file |

## Authentication Commands

### argocd login

```bash
argocd login SERVER [flags]

# Interactive login
argocd login argocd.example.com

# Non-interactive
argocd login argocd.example.com --username admin --password secret

# With SSO
argocd login argocd.example.com --sso

# Skip TLS
argocd login argocd.example.com --insecure

Flags:
  --grpc-web               Use gRPC-web
  --insecure               Skip TLS verification
  --name string            Context name override
  --password string        Password
  --plaintext              Disable TLS
  --skip-test-tls          Skip TLS test
  --sso                    Perform SSO login
  --sso-port int           Port for SSO callback (default 8085)
  --username string        Username
```

### argocd logout

```bash
argocd logout SERVER [flags]
```

### argocd relogin

```bash
argocd relogin [flags]

# Refresh SSO session
argocd relogin --sso
```

### argocd context

```bash
# List contexts
argocd context

# Switch context
argocd context myserver

# Delete context
argocd context myserver --delete
```

## Application Commands

### argocd app create

```bash
argocd app create NAME [flags]

# From Git repo
argocd app create myapp \
  --repo https://github.com/org/repo.git \
  --path manifests \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default

# With Helm
argocd app create myapp \
  --repo https://charts.example.com \
  --helm-chart mychart \
  --revision 1.0.0 \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default \
  --helm-set image.tag=v1.0.0 \
  --values-literal-file values.yaml

# With Kustomize
argocd app create myapp \
  --repo https://github.com/org/repo.git \
  --path kustomize/overlays/prod \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default \
  --kustomize-image gcr.io/image:v1.0.0

# With auto-sync
argocd app create myapp \
  --repo https://github.com/org/repo.git \
  --path manifests \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default \
  --sync-policy automated \
  --auto-prune \
  --self-heal \
  --sync-option CreateNamespace=true

Flags:
  --allow-empty                    Allow empty resources
  --annotations stringArray        Annotations (key=value)
  --auto-prune                     Enable auto-prune
  --config-management-plugin string Plugin name
  --core                           Use core mode
  --dest-name string               Destination cluster name
  --dest-namespace string          Destination namespace
  --dest-server string             Destination server URL
  --directory-exclude string       Directory exclude pattern
  --directory-include string       Directory include pattern
  --directory-recurse              Recurse directories
  --env string                     Environment
  --file string                    Create from file
  --grpc-web                       Use gRPC-web
  --helm-chart string              Helm chart name
  --helm-pass-credentials          Pass credentials to Helm
  --helm-set stringArray           Helm set values
  --helm-set-file stringArray      Helm set file values
  --helm-set-string stringArray    Helm set string values
  --helm-skip-crds                 Skip CRDs
  --helm-version string            Helm version
  --ignore-missing-value-files     Ignore missing value files
  --jsonnet-ext-var stringArray    Jsonnet ext vars
  --jsonnet-libs stringArray       Jsonnet libs
  --jsonnet-tla-code stringArray   Jsonnet TLA code
  --jsonnet-tla-str stringArray    Jsonnet TLA strings
  --kustomize-common-annotation stringArray Common annotations
  --kustomize-common-label stringArray Common labels
  --kustomize-force-common-annotation Force common annotations
  --kustomize-force-common-label   Force common labels
  --kustomize-image stringArray    Kustomize images
  --kustomize-namespace string     Kustomize namespace
  --kustomize-replica stringArray  Kustomize replicas
  --kustomize-version string       Kustomize version
  --label stringArray              Labels (key=value)
  --name string                    Application name
  --nameprefix string              Kustomize name prefix
  --namesuffix string              Kustomize name suffix
  --path string                    Path within repo
  --plugin-env stringArray         Plugin env vars
  --project string                 Project (default "default")
  --ref string                     Source ref
  --release-name string            Helm release name
  --repo string                    Repository URL
  --revision string                Revision (default "HEAD")
  --revision-history-limit int     Revision history limit
  --self-heal                      Enable self-heal
  --set-finalizer                  Set finalizer
  --sync-option stringArray        Sync options
  --sync-policy string             Sync policy (none, automated)
  --sync-retry-backoff-duration string Retry backoff duration
  --sync-retry-backoff-factor int  Retry backoff factor
  --sync-retry-backoff-max-duration string Max retry duration
  --sync-retry-limit int           Retry limit
  --upsert                         Update if exists
  --validate                       Validate manifests
  --values stringArray             Helm values files
  --values-literal-file string     Values from file
```

### argocd app get

```bash
argocd app get APPNAME [flags]

# Get app details
argocd app get myapp

# JSON output
argocd app get myapp -o json

# Wide output (shows all resources)
argocd app get myapp -o wide

# YAML output
argocd app get myapp -o yaml

# Show operation info
argocd app get myapp --show-operation

# Show params
argocd app get myapp --show-params

Flags:
  --hard-refresh         Force refresh from source
  -o, --output string    Output format (json, yaml, wide)
  --refresh              Refresh app first
  --show-operation       Show last operation
  --show-params          Show parameters
```

### argocd app list

```bash
argocd app list [flags]

# List all apps
argocd app list

# Filter by project
argocd app list -p myproject

# Filter by label
argocd app list -l app=myapp

# JSON output
argocd app list -o json

# Filter by cluster
argocd app list --cluster production

Flags:
  --app-namespace string    App namespace
  -c, --cluster string      Filter by cluster
  -l, --selector string     Label selector
  -o, --output string       Output format (wide, name, json, yaml)
  -p, --project stringArray Project filter
  -r, --repo string         Repository filter
```

### argocd app sync

```bash
argocd app sync APPNAME [flags]

# Basic sync
argocd app sync myapp

# Sync with prune
argocd app sync myapp --prune

# Force sync (recreate resources)
argocd app sync myapp --force

# Dry run
argocd app sync myapp --dry-run

# Sync specific revision
argocd app sync myapp --revision v1.0.0

# Sync specific resources
argocd app sync myapp --resource apps:Deployment:nginx
argocd app sync myapp --resource :Service:nginx --resource apps:Deployment:nginx

# Async sync (don't wait)
argocd app sync myapp --async

# Sync with retry
argocd app sync myapp --retry-limit 5 --retry-backoff-duration 5s

# Preview sync diff
argocd app sync myapp --preview-changes

Flags:
  --apply-out-of-sync-only     Only sync out-of-sync resources
  --async                       Don't wait for completion
  --assumeYes                   Assume yes on prompts
  --dry-run                     Preview without applying
  --force                       Force resource deletion/recreation
  --info stringArray            Sync info (key=value)
  --label stringArray           Filter resources by label
  --local string                Sync from local path
  --local-repo-root string      Local repo root
  --preview-changes             Preview changes
  --prune                       Delete resources not in Git
  --replace                     Use replace instead of apply
  --resource stringArray        Sync specific resources (group:kind:name)
  --retry-backoff-duration duration Retry duration (default 5s)
  --retry-backoff-factor int    Retry factor (default 2)
  --retry-backoff-max-duration duration Max retry duration (default 3m)
  --retry-limit int             Retry limit
  --revision string             Sync to revision
  --server-side                 Server-side apply
  --strategy string             Sync strategy (apply, hook)
  --timeout uint                Timeout in seconds
```

### argocd app wait

```bash
argocd app wait APPNAME [flags]

# Wait for sync and health
argocd app wait myapp

# Wait for health only
argocd app wait myapp --health

# Wait for sync only
argocd app wait myapp --sync

# Wait for operation
argocd app wait myapp --operation

# With timeout
argocd app wait myapp --health --timeout 300

# Wait for suspended
argocd app wait myapp --suspended

Flags:
  --degraded           Wait for degraded
  --health             Wait for healthy
  --operation          Wait for operation
  --resource stringArray Wait for specific resources
  --suspended          Wait for suspended
  --sync               Wait for synced
  --timeout uint       Timeout in seconds
```

### argocd app delete

```bash
argocd app delete APPNAME [flags]

# Delete app and resources
argocd app delete myapp

# Delete without confirmation
argocd app delete myapp -y

# Keep resources (orphan)
argocd app delete myapp --cascade=false

# Force delete
argocd app delete myapp --cascade --propagation-policy foreground

Flags:
  --cascade                Delete resources (default true)
  --propagation-policy string Propagation policy (foreground, background, orphan)
  -y, --yes                 Skip confirmation
```

### argocd app history

```bash
argocd app history APPNAME [flags]

# Show deployment history
argocd app history myapp

# JSON output
argocd app history myapp -o json

Flags:
  -o, --output string   Output format (wide, id, json)
```

### argocd app rollback

```bash
argocd app rollback APPNAME ID [flags]

# Rollback to history ID
argocd app rollback myapp 2

# Dry run
argocd app rollback myapp 2 --dry-run

# Prune on rollback
argocd app rollback myapp 2 --prune

Flags:
  --dry-run   Preview without applying
  --prune     Delete extra resources
  --timeout uint Timeout in seconds
```

### argocd app diff

```bash
argocd app diff APPNAME [flags]

# Show diff
argocd app diff myapp

# Diff against revision
argocd app diff myapp --revision v1.0.0

# Local diff
argocd app diff myapp --local ./manifests

# Quiet (exit code only)
argocd app diff myapp --exit-code

Flags:
  --exit-code           Use exit code for result
  --hard-refresh        Force refresh
  --local string        Local manifests path
  --local-repo-root string Local repo root
  --refresh             Refresh first
  --revision string     Compare revision
  --server-side-generate Server-side manifest generation
```

### argocd app logs

```bash
argocd app logs APPNAME [flags]

# Get logs
argocd app logs myapp

# Follow logs
argocd app logs myapp -f

# Specific container
argocd app logs myapp --container nginx

# Specific pod
argocd app logs myapp --name nginx-xxx

# Filter by group/kind
argocd app logs myapp --group apps --kind Deployment

# Tail lines
argocd app logs myapp --tail 100

# Since time
argocd app logs myapp --since-time 2023-01-01T00:00:00Z
argocd app logs myapp --since 1h

Flags:
  --container string    Container name
  -f, --follow          Follow logs
  --group string        Resource group
  --kind string         Resource kind
  --name string         Pod name
  --namespace string    Resource namespace
  --previous            Previous container instance
  --since duration      Since duration (e.g., 1h)
  --since-time string   Since time (RFC3339)
  --tail int            Tail lines (default -1, all)
  --timestamps          Show timestamps
```

### argocd app set

```bash
argocd app set APPNAME [flags]

# Change target revision
argocd app set myapp --revision v1.0.0

# Change sync policy
argocd app set myapp --sync-policy automated

# Set Helm values
argocd app set myapp --helm-set image.tag=v2.0.0

# Add sync option
argocd app set myapp --sync-option Prune=true

Flags:
  # Same as app create, allows updating any setting
```

### argocd app unset

```bash
argocd app unset APPNAME [flags]

# Remove Helm parameter
argocd app unset myapp --parameter image.tag

# Remove values file
argocd app unset myapp --values values-override.yaml

Flags:
  --ignore-missing-value-files
  --jsonnet-ext-var-code stringArray
  --jsonnet-ext-var stringArray
  --jsonnet-tla-code stringArray
  --jsonnet-tla-str stringArray
  --kustomize-image stringArray
  --name-prefix
  --name-suffix
  --parameter stringArray
  --pass-credentials
  --plugin-env stringArray
  --values stringArray
```

### argocd app resources

```bash
argocd app resources APPNAME [flags]

# List resources
argocd app resources myapp

Flags:
  --orphaned            Show orphaned resources only
  -o, --output string   Output format (wide, tree, json)
```

### argocd app manifests

```bash
argocd app manifests APPNAME [flags]

# Get live manifests
argocd app manifests myapp

# Get source manifests
argocd app manifests myapp --source live

# Get specific revision
argocd app manifests myapp --revision v1.0.0

Flags:
  --local string        Local path
  --local-repo-root string Local repo root
  --revision string     Revision
  --source string       Source (live, git)
```

### argocd app patch

```bash
argocd app patch APPNAME [flags]

# Patch application
argocd app patch myapp --patch '{"spec":{"source":{"targetRevision":"v1.0.0"}}}'

# Patch from file
argocd app patch myapp --patch-file patch.json

Flags:
  --patch string        JSON/YAML patch
  --patch-file string   Patch file
  --type string         Patch type (json, merge, strategic)
```

### argocd app terminate-op

```bash
argocd app terminate-op APPNAME [flags]

# Terminate running operation
argocd app terminate-op myapp
```

### argocd app actions

```bash
# List available actions
argocd app actions list myapp --kind Deployment

# Run action
argocd app actions run myapp restart \
  --kind Deployment --resource-name nginx --namespace default

# Disable action
argocd app actions run myapp disable --kind Rollout --resource-name canary
```

## ApplicationSet Commands

### argocd appset create

```bash
argocd appset create FILE [flags]

# Create from file
argocd appset create appset.yaml

# Upsert
argocd appset create appset.yaml --upsert

Flags:
  --upsert   Update if exists
```

### argocd appset get

```bash
argocd appset get NAME [flags]

# Get details
argocd appset get myappset

# YAML output
argocd appset get myappset -o yaml

Flags:
  -o, --output string   Output format (json, yaml)
```

### argocd appset list

```bash
argocd appset list [flags]

# List all
argocd appset list

# Filter by project
argocd appset list -p myproject

Flags:
  -o, --output string   Output format (wide, json, yaml)
  -p, --project stringArray Project filter
  -l, --selector string Label selector
```

### argocd appset delete

```bash
argocd appset delete NAME [flags]

# Delete
argocd appset delete myappset

# Without confirmation
argocd appset delete myappset -y

Flags:
  -y, --yes   Skip confirmation
```

## Project Commands

### argocd proj create

```bash
argocd proj create NAME [flags]

# Create project
argocd proj create myproject \
  -d https://kubernetes.default.svc,default \
  -s https://github.com/org/*

Flags:
  --allow-cluster-resource stringArray Allow cluster resources
  --allow-namespaced-resource stringArray Allow namespaced resources
  --deny-cluster-resource stringArray Deny cluster resources
  --deny-namespaced-resource stringArray Deny namespaced resources
  --description string    Description
  -d, --dest stringArray  Destinations (server,namespace)
  --orphaned-resources-warn Warn on orphaned resources
  --signature-keys stringArray GPG signature keys
  --source-namespaces stringArray Source namespaces
  -s, --src stringArray   Source repos
  --upsert                Update if exists
```

### argocd proj list

```bash
argocd proj list [flags]

# List projects
argocd proj list

# JSON output
argocd proj list -o json

Flags:
  -o, --output string   Output format (wide, json, yaml, name)
```

### argocd proj get

```bash
argocd proj get NAME [flags]

# Get project
argocd proj get myproject

Flags:
  -o, --output string   Output format (json, yaml)
```

### argocd proj edit

```bash
# Open in editor
argocd proj edit myproject
```

### argocd proj delete

```bash
argocd proj delete NAME [flags]

# Delete project
argocd proj delete myproject
```

### argocd proj add-destination

```bash
argocd proj add-destination PROJECT SERVER NAMESPACE [flags]

# Add destination
argocd proj add-destination myproject https://kubernetes.default.svc 'team-*'

# Add by cluster name
argocd proj add-destination myproject production default --name
```

### argocd proj remove-destination

```bash
argocd proj remove-destination PROJECT SERVER NAMESPACE
```

### argocd proj add-source

```bash
argocd proj add-source PROJECT URL

# Add source repo
argocd proj add-source myproject 'https://github.com/org/*'
```

### argocd proj remove-source

```bash
argocd proj remove-source PROJECT URL
```

### argocd proj role create

```bash
argocd proj role create PROJECT ROLE

# Create role
argocd proj role create myproject developer
```

### argocd proj role delete

```bash
argocd proj role delete PROJECT ROLE
```

### argocd proj role add-policy

```bash
argocd proj role add-policy PROJECT ROLE [flags]

# Add policy
argocd proj role add-policy myproject developer \
  -a sync -p allow -o '*'

# Add get permission
argocd proj role add-policy myproject developer \
  -a get -p allow -o '*'

Flags:
  -a, --action string     Action (get, sync, override, delete)
  -o, --object string     Object pattern
  -p, --permission string Permission (allow, deny)
```

### argocd proj role remove-policy

```bash
argocd proj role remove-policy PROJECT ROLE [flags]
```

### argocd proj role add-group

```bash
argocd proj role add-group PROJECT ROLE GROUP

# Add SSO group
argocd proj role add-group myproject developer team-developers
```

### argocd proj role remove-group

```bash
argocd proj role remove-group PROJECT ROLE GROUP
```

### argocd proj role create-token

```bash
argocd proj role create-token PROJECT ROLE [flags]

# Create token
argocd proj role create-token myproject developer --expires-in 24h

Flags:
  --expires-in duration   Token expiration
  --id string            Token ID
```

### argocd proj role delete-token

```bash
argocd proj role delete-token PROJECT ROLE IAT
```

### argocd proj windows add

```bash
argocd proj windows add PROJECT [flags]

# Add sync window
argocd proj windows add myproject \
  --kind allow \
  --schedule "0 22 * * *" \
  --duration 2h \
  --applications '*'

Flags:
  --applications stringArray Apps to match
  --clusters stringArray     Clusters to match
  --duration string          Window duration
  --kind string              Kind (allow, deny)
  --manual-sync              Allow manual sync
  --namespaces stringArray   Namespaces to match
  --schedule string          Cron schedule
  --time-zone string         Timezone
```

### argocd proj windows delete

```bash
argocd proj windows delete PROJECT ID
```

### argocd proj windows list

```bash
argocd proj windows list PROJECT
```

### argocd proj windows update

```bash
argocd proj windows update PROJECT ID [flags]
```

## Repository Commands

### argocd repo add

```bash
argocd repo add REPOURL [flags]

# HTTPS with token
argocd repo add https://github.com/org/repo --username git --password $TOKEN

# SSH with key
argocd repo add git@github.com:org/repo.git --ssh-private-key-path ~/.ssh/id_rsa

# GitHub App
argocd repo add https://github.com/org/repo \
  --github-app-id 12345 \
  --github-app-installation-id 67890 \
  --github-app-private-key-path key.pem

# Helm repo
argocd repo add https://charts.example.com --type helm --name stable

# OCI registry
argocd repo add registry.example.com --type helm --enable-oci

Flags:
  --enable-lfs               Enable Git LFS
  --enable-oci               Enable OCI
  --force-http-basic-auth    Force HTTP basic auth
  --github-app-enterprise-base-url string GHE URL
  --github-app-id int        GitHub App ID
  --github-app-installation-id int GitHub App Installation ID
  --github-app-private-key-path string GitHub App key path
  --insecure-skip-server-verification Skip TLS verify
  --name string              Repository name
  --password string          Password/token
  --project string           Project
  --proxy string             Proxy URL
  --ssh-private-key-path string SSH key path
  --tls-client-cert-data string TLS cert
  --tls-client-cert-key string TLS key
  --type string              Type (git, helm)
  --upsert                   Update if exists
  --username string          Username
```

### argocd repo list

```bash
argocd repo list [flags]

Flags:
  -o, --output string   Output format (url, json, yaml)
  --refresh             Refresh repos
```

### argocd repo get

```bash
argocd repo get REPOURL [flags]
```

### argocd repo rm

```bash
argocd repo rm REPOURL [flags]
```

### argocd repocreds add

```bash
argocd repocreds add URLPREFIX [flags]

# Add credential template
argocd repocreds add https://github.com/myorg/ --username git --password $TOKEN

# SSH credentials
argocd repocreds add git@github.com:myorg/ --ssh-private-key-path ~/.ssh/id_rsa
```

### argocd repocreds list

```bash
argocd repocreds list
```

### argocd repocreds rm

```bash
argocd repocreds rm URLPREFIX
```

## Cluster Commands

### argocd cluster add

```bash
argocd cluster add CONTEXT [flags]

# Add from kubeconfig context
argocd cluster add my-context

# With custom name
argocd cluster add my-context --name production

# To specific project
argocd cluster add my-context --project myproject

# With namespace restrictions
argocd cluster add my-context --namespace default --namespace app

# With labels
argocd cluster add my-context --label environment=production

Flags:
  --annotation stringArray Annotations
  --aws-cluster-name string AWS EKS cluster name
  --aws-role-arn string  AWS role ARN
  --cluster-endpoint string Cluster endpoint override
  --in-cluster          In-cluster service account
  --kubeconfig string   Kubeconfig path
  --label stringArray   Labels
  --name string         Cluster name
  --namespace stringArray Namespaces
  --project string      Project
  --shard int           Shard number
  --system-namespace string System namespace
  --upsert              Update if exists
```

### argocd cluster list

```bash
argocd cluster list [flags]

Flags:
  -o, --output string   Output format (wide, server, json, yaml)
```

### argocd cluster get

```bash
argocd cluster get SERVER [flags]

Flags:
  -o, --output string   Output format (json, yaml)
```

### argocd cluster rm

```bash
argocd cluster rm SERVER [flags]

Flags:
  -y, --yes   Skip confirmation
```

### argocd cluster rotate-auth

```bash
argocd cluster rotate-auth SERVER [flags]

# Rotate credentials
argocd cluster rotate-auth https://production.example.com
```

## Account Commands

### argocd account list

```bash
argocd account list [flags]

Flags:
  -o, --output string   Output format (wide, json)
```

### argocd account get

```bash
argocd account get [USERNAME] [flags]

# Get current user
argocd account get

# Get specific user
argocd account get admin

Flags:
  -o, --output string   Output format (json, yaml)
```

### argocd account generate-token

```bash
argocd account generate-token [flags]

# Generate for current account
argocd account generate-token

# For specific account
argocd account generate-token --account cibot

# With expiration
argocd account generate-token --account cibot --expires-in 7d

# With ID
argocd account generate-token --account cibot --id deploy-token

Flags:
  --account string      Account name
  --expires-in duration Token expiration
  --id string           Token ID
```

### argocd account update-password

```bash
argocd account update-password [flags]

# Update current password
argocd account update-password

# Update specific account
argocd account update-password --account admin

Flags:
  --account string      Account name
  --current-password string Current password
  --new-password string New password
```

### argocd account can-i

```bash
argocd account can-i ACTION RESOURCE SUBRESOURCE [flags]

# Check sync permission
argocd account can-i sync applications '*'

# Check specific app
argocd account can-i get applications 'myproject/myapp'

# Check cluster resource
argocd account can-i update clusters '*'
```

### argocd account get-user-info

```bash
argocd account get-user-info [flags]

Flags:
  -o, --output string   Output format (json, yaml)
```

### argocd account bcrypt

```bash
argocd account bcrypt --password PASSWORD

# Generate bcrypt hash
argocd account bcrypt --password mysecret
```

## Certificate Commands

### argocd cert add-ssh

```bash
# Add SSH known hosts
ssh-keyscan github.com | argocd cert add-ssh --batch

# Add single host
argocd cert add-ssh --from /path/to/known_hosts
```

### argocd cert add-tls

```bash
# Add TLS cert
argocd cert add-tls cd.example.com --from /path/to/cert.pem
```

### argocd cert list

```bash
argocd cert list [flags]

Flags:
  --cert-type string    Type (ssh, https)
  --hostname-pattern string Pattern
  -o, --output string   Output format (wide, json)
```

### argocd cert rm

```bash
argocd cert rm HOSTNAME [flags]

Flags:
  --cert-type string    Type (ssh, https)
  --cert-sub-type string Sub-type
```

## GPG Commands

### argocd gpg add

```bash
argocd gpg add --from /path/to/key.asc
```

### argocd gpg list

```bash
argocd gpg list [flags]

Flags:
  -o, --output string   Output format (json, yaml)
```

### argocd gpg get

```bash
argocd gpg get KEYID [flags]

Flags:
  -o, --output string   Output format (json, yaml)
```

### argocd gpg rm

```bash
argocd gpg rm KEYID
```

## Version Command

```bash
# Show client version
argocd version

# Show client only
argocd version --client

# JSON output
argocd version -o json
```

## Admin Commands

### argocd admin initial-password

```bash
# Get initial admin password
argocd admin initial-password -n argocd

# Reset the password
argocd admin initial-password reset -n argocd
```

### argocd admin dashboard

```bash
# Start local web UI (no server required)
argocd admin dashboard

# With custom port
argocd admin dashboard --port 8080

# With namespace
argocd admin dashboard -n argocd
```

### argocd admin export/import

```bash
# Export all ArgoCD resources
argocd admin export > backup.yaml

# Export specific resource types
argocd admin export --applications --projects > backup.yaml

# Import from file
argocd admin import < backup.yaml

# Import with merge
argocd admin import --merge < backup.yaml
```

### argocd admin settings

```bash
# Validate settings
argocd admin settings validate -n argocd

# Validate RBAC policy
argocd admin settings rbac validate --policy-file policy.csv

# Test RBAC permission
argocd admin settings rbac can role:developer get applications '*/*'
argocd admin settings rbac can role:developer sync applications 'myproject/*'

# Get resource overrides
argocd admin settings resource-overrides health Rollout

# List all settings
argocd admin settings -n argocd
```

### argocd admin cluster

```bash
# Generate cluster config
argocd admin cluster generate-spec CONTEXT

# Get cluster kubeconfig
argocd admin cluster kubeconfig CONTEXT

# Get cluster namespaces
argocd admin cluster namespaces CONTEXT

# Shards management
argocd admin cluster shards
```

### argocd admin app

```bash
# Get app resources
argocd admin app get-recurse myapp

# Diff app manifests
argocd admin app diff-reconcile-results myapp
```

### argocd admin repo

```bash
# Generate repo credentials
argocd admin repo generate-spec

# Update repo credentials
argocd admin repo update-credentials
```

### argocd admin proj

```bash
# Generate project spec
argocd admin proj generate-spec

# Update project destinations
argocd admin proj update-destinations
```

### argocd admin notifications

```bash
# List templates
argocd admin notifications template list

# Get template
argocd admin notifications template get app-deployed

# List triggers
argocd admin notifications trigger list

# Get trigger
argocd admin notifications trigger get on-deployed

# Test notification
argocd admin notifications template notify app-deployed myapp
```

### argocd admin redis-initial-password

```bash
# Ensure Redis password exists
argocd admin redis-initial-password -n argocd
```

## Completion Command

```bash
# Generate bash completion
argocd completion bash > /etc/bash_completion.d/argocd

# Generate zsh completion
argocd completion zsh > "${fpath[1]}/_argocd"

# Generate fish completion
argocd completion fish > ~/.config/fish/completions/argocd.fish

# Generate PowerShell completion
argocd completion powershell > argocd.ps1
```

## Configure Command

```bash
# Configure local settings
argocd configure set server argocd.example.com
argocd configure set insecure true

# View configuration
argocd configure get

# Unset configuration
argocd configure unset insecure
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ARGOCD_SERVER` | ArgoCD server address |
| `ARGOCD_AUTH_TOKEN` | Bearer token for authentication |
| `ARGOCD_OPTS` | Default CLI options |
| `ARGOCD_GRPC_WEB` | Use gRPC-web (true/false) |
| `ARGOCD_INSECURE` | Skip TLS verification |
| `ARGOCD_PLAINTEXT` | Disable TLS |
| `ARGOCD_CONFIG_DIR` | Config directory path |

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Invalid argument |
| `3` | Not found |
| `4` | Permission denied |
| `5` | Timeout |
| `20` | Sync failed |
| `21` | Health check failed |
