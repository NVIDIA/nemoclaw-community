# ArgoCD Image Updater - Authentication Guide

Configure authentication for container registries and Git repositories.

## Registry Authentication

### Docker Hub

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: dockerhub-creds
  namespace: argocd
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {
      "auths": {
        "https://index.docker.io/v1/": {
          "auth": "<base64(username:password)>"
        }
      }
    }
```

Generate the auth value (base64 encoded credentials):

```bash
# Generate the auth value (single base64 encoding of username:password)
echo -n 'username:password' | base64
# Example output: dXNlcm5hbWU6cGFzc3dvcmQ=
```

> **Note:** The `auth` field requires base64-encoded `username:password`. Using `stringData` instead of `data` means Kubernetes handles the outer encoding automatically, so you only need to base64-encode the credentials once.

Reference in ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  registries.conf: |
    registries:
      - name: Docker Hub
        prefix: docker.io
        api_url: https://registry-1.docker.io
        credentials: pullsecret:argocd/dockerhub-creds
        default: true
```

### GitHub Container Registry (GHCR)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ghcr-creds
  namespace: argocd
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {
      "auths": {
        "ghcr.io": {
          "auth": "<base64(username:PAT)>"
        }
      }
    }
```

Registry configuration:

```yaml
registries:
  - name: GitHub Container Registry
    prefix: ghcr.io
    api_url: https://ghcr.io
    credentials: pullsecret:argocd/ghcr-creds
```

### Azure Container Registry (ACR)

#### Using Service Principal

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: acr-creds
  namespace: argocd
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {
      "auths": {
        "myregistry.azurecr.io": {
          "auth": "<base64(SP_APP_ID:SP_PASSWORD)>"
        }
      }
    }
```

#### Using Managed Identity (AKS)

If using Azure Workload Identity:

```yaml
registries:
  - name: ACR
    prefix: myregistry.azurecr.io
    api_url: https://myregistry.azurecr.io
    # No credentials needed with Workload Identity
```

### Amazon ECR

ECR requires dynamic credential retrieval since tokens expire every 12 hours. Use the external script method:

**Step 1: Create the credential script Secret**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ecr-creds
  namespace: argocd
type: Opaque
stringData:
  ecr-login.sh: |
    #!/bin/sh
    aws ecr get-login-password --region us-east-1
```

**Step 2: Mount the script into Image Updater deployment**

Patch the argocd-image-updater deployment to mount the script:

```yaml
# Add to deployment spec.template.spec.volumes:
volumes:
  - name: ecr-script
    secret:
      secretName: ecr-creds
      defaultMode: 0755  # Make script executable

# Add to deployment spec.template.spec.containers[0].volumeMounts:
volumeMounts:
  - name: ecr-script
    mountPath: /app/config/ecr
    readOnly: true
```

If using Helm, add to values:

```yaml
config:
  extraVolumes:
    - name: ecr-script
      secret:
        secretName: ecr-creds
        defaultMode: 0755
  extraVolumeMounts:
    - name: ecr-script
      mountPath: /app/config/ecr
      readOnly: true
```

**Step 3: Configure registry to use the script**

```yaml
registries:
  - name: ECR
    prefix: 123456789.dkr.ecr.us-east-1.amazonaws.com
    api_url: https://123456789.dkr.ecr.us-east-1.amazonaws.com
    credentials: ext:/app/config/ecr/ecr-login.sh
```

> **Important:** Ensure AWS credentials are available to the pod via IAM Roles for Service Accounts (IRSA) or environment variables.

### Google Container Registry (GCR)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gcr-creds
  namespace: argocd
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {
      "auths": {
        "gcr.io": {
          "auth": "<base64(_json_key:SERVICE_ACCOUNT_JSON)>"
        }
      }
    }
```

### Quay.io

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: quay-creds
  namespace: argocd
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {
      "auths": {
        "quay.io": {
          "auth": "<base64(username:password)>"
        }
      }
    }
```

## Credential Types

The Image Updater supports multiple credential formats in the ConfigMap `registries.conf`. Choose the appropriate type based on your secret format.

### Pull Secret (Recommended for Docker Registries)

Use this when you have a standard Kubernetes docker-config secret (type `kubernetes.io/dockerconfigjson`). This is the most common approach for registry authentication.

```yaml
credentials: pullsecret:<namespace>/<secret-name>
```

Example:

```yaml
credentials: pullsecret:argocd/dockerhub-creds
```

### Secret Reference

Use this when credentials are stored in a generic Opaque secret with separate keys for username and password, rather than the docker-config JSON format.

```yaml
credentials: secret:<namespace>/<secret-name>#<key>
```

Example - referencing username and password from an Opaque secret:

```yaml
# For a secret with keys 'username' and 'password':
apiVersion: v1
kind: Secret
metadata:
  name: registry-creds
  namespace: argocd
type: Opaque
stringData:
  username: myuser
  password: mytoken

# Reference in registries.conf:
registries:
  - name: My Registry
    prefix: registry.example.com
    api_url: https://registry.example.com
    credentials: secret:argocd/registry-creds#username
    credsexpire: 5m  # Optional: credential cache expiration
```

> **Note:** The `secret:` format references a single key. For username/password pairs, you may need to structure your secret appropriately or use the `pullsecret:` format with a docker-config secret instead.

### Environment Variable

Reference credentials from environment variables set on the Image Updater pod:

```yaml
credentials: env:REGISTRY_PASSWORD
```

### External Script

For dynamic credentials that require runtime generation (like ECR tokens that expire):

```yaml
credentials: ext:/path/to/script
```

The script must output the password/token to stdout. See the ECR section above for a complete example.

## ImageUpdater CRD Authentication

### Per-Image Credentials

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: my-updater
  namespace: argocd
spec:
  registries:
    - name: myregistry
      prefix: myregistry.example.com
      apiUrl: https://myregistry.example.com
      credentials:
        pullSecretRef:
          name: registry-creds
          namespace: argocd
  applicationRefs:
    - namePattern: "my-app"
      images:
        - alias: "app"
          imageName: "myregistry.example.com/app"
```

### Multiple Registries

```yaml
spec:
  registries:
    - name: production
      prefix: prod.registry.io
      credentials:
        pullSecretRef:
          name: prod-creds
    - name: development
      prefix: dev.registry.io
      credentials:
        pullSecretRef:
          name: dev-creds
```

## Git Authentication

### SSH Key

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: git-ssh-key
  namespace: argocd
type: Opaque
stringData:
  sshPrivateKey: |
    <SSH_PRIVATE_KEY_CONTENT>
    # Generate with: ssh-keygen -t ed25519 -C "argocd-image-updater"
```

### Deploy Key (GitHub)

1. Generate SSH key:

```bash
ssh-keygen -t ed25519 -C "argocd-image-updater" -f deploy_key -N ""
```

2. Add public key as deploy key in GitHub repo settings

3. Create secret with private key:

```bash
kubectl create secret generic git-ssh-key \
  --from-file=sshPrivateKey=deploy_key \
  -n argocd
```

### Personal Access Token (GitHub)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: github-token
  namespace: argocd
type: Opaque
stringData:
  username: git
  password: ghp_xxxxxxxxxxxxxxxxxxxx
```

Required token scopes:

- `repo` (for private repos)
- `read:packages` (for GHCR)

### Azure DevOps

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: azure-devops-creds
  namespace: argocd
type: Opaque
stringData:
  username: ""  # Leave empty for PAT
  password: <your-PAT>
```

## Testing Authentication

### Test Registry Access

```bash
# From Image Updater pod
kubectl exec -n argocd deployment/argocd-image-updater -- \
  argocd-image-updater test myregistry.example.com/myimage
```

### Test Git Access

```bash
# SSH
kubectl exec -n argocd deployment/argocd-image-updater -- \
  ssh -T git@github.com

# HTTPS
kubectl exec -n argocd deployment/argocd-image-updater -- \
  git ls-remote https://github.com/myorg/myrepo.git
```

## Troubleshooting Authentication

### Registry Authentication Failed

```bash
# Check secret exists and is correctly formatted
kubectl get secret dockerhub-creds -n argocd -o yaml

# Decode and verify
kubectl get secret dockerhub-creds -n argocd -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .
```

### Git Authentication Failed

```bash
# Check SSH key permissions
kubectl exec -n argocd deployment/argocd-image-updater -- \
  ls -la /app/config/ssh/

# Test SSH connection
kubectl exec -n argocd deployment/argocd-image-updater -- \
  ssh -vT git@github.com 2>&1 | head -50
```

### ECR Token Expired

ECR tokens expire after 12 hours. Use the external script method:

```bash
#!/bin/sh
aws ecr get-login-password --region $AWS_REGION
```

Ensure AWS credentials are available (via IAM role or environment variables).
