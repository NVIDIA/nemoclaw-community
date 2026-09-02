# Registry Reference

Image tagging strategies, pushing to registries (ECR, GCR, GHCR, Docker Hub), authentication, multi-architecture builds, vulnerability scanning, and image signing.

---

## Image Tagging Strategies

### Recommended Tags

| Strategy | Example | When to Use |
|----------|---------|-------------|
| Semver | `myapp:1.2.3` | Production releases, clear versioning |
| Git SHA (short) | `myapp:abc1234` | CI/CD builds, traceability to exact commit |
| Git SHA + branch | `myapp:main-abc1234` | Multi-branch CI, distinguish branches |
| Timestamp | `myapp:20240115-143022` | When semver is overkill, sorted by time |
| Semver + SHA | `myapp:1.2.3-abc1234` | Best of both: version clarity + commit traceability |

### Why :latest Is Dangerous

- **Not a version** — `:latest` is just a tag name. It does not mean "most recent."
- **Unpredictable deploys** — Two hosts pulling `:latest` at different times get different images.
- **No rollback path** — When `:latest` is overwritten, the previous image is gone.
- **Cache confusion** — Docker may use a cached `:latest` that is stale.

**Rule:** Never use `:latest` in production. Always use immutable, specific tags.

```bash
# Bad
docker build -t myapp .
docker build -t myapp:latest .

# Good
docker build -t myapp:1.2.3 -t myapp:abc1234 .
```

### Tagging in CI

```bash
# Tag with git SHA and semver (if tagged)
GIT_SHA=$(git rev-parse --short HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)

docker build -t myapp:${GIT_SHA} -t myapp:${BRANCH}-${GIT_SHA} .

# If this is a semver release tag
if [[ "${GITHUB_REF}" == refs/tags/v* ]]; then
  VERSION=${GITHUB_REF#refs/tags/v}
  docker tag myapp:${GIT_SHA} myapp:${VERSION}
fi
```

---

## Push to Registries

### Docker Hub

```bash
# Login
docker login -u <username>

# Tag and push
docker tag myapp:1.2.3 <username>/myapp:1.2.3
docker push <username>/myapp:1.2.3
```

### Amazon ECR

```bash
# Authenticate (valid for 12 hours)
aws ecr get-login-password --region <region> | \
  docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com

# Create repository (first time)
aws ecr create-repository --repository-name myapp

# Tag and push
docker tag myapp:1.2.3 <account-id>.dkr.ecr.<region>.amazonaws.com/myapp:1.2.3
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/myapp:1.2.3
```

### Google Container Registry (GCR) / Artifact Registry

```bash
# Authenticate with gcloud
gcloud auth configure-docker <region>-docker.pkg.dev

# Tag and push (Artifact Registry)
docker tag myapp:1.2.3 <region>-docker.pkg.dev/<project-id>/<repo>/myapp:1.2.3
docker push <region>-docker.pkg.dev/<project-id>/<repo>/myapp:1.2.3
```

### GitHub Container Registry (GHCR)

```bash
# Authenticate with GitHub token
echo $GITHUB_TOKEN | docker login ghcr.io -u <username> --password-stdin

# Tag and push
docker tag myapp:1.2.3 ghcr.io/<owner>/myapp:1.2.3
docker push ghcr.io/<owner>/myapp:1.2.3
```

---

## Authentication

### Docker Login

```bash
# Interactive (prompts for password)
docker login <registry>

# Non-interactive (CI/CD)
echo $PASSWORD | docker login <registry> -u <username> --password-stdin
```

### Credential Helpers

Credential helpers store credentials securely instead of in `~/.docker/config.json`:

```json
// ~/.docker/config.json
{
  "credHelpers": {
    "123456789.dkr.ecr.us-east-1.amazonaws.com": "ecr-login",
    "us-docker.pkg.dev": "gcloud",
    "ghcr.io": "gh"
  }
}
```

| Registry | Helper | Install |
|----------|--------|---------|
| ECR | `docker-credential-ecr-login` | `go install github.com/awslabs/amazon-ecr-credential-helper/...` |
| GCR/AR | `docker-credential-gcloud` | Bundled with `gcloud` CLI |
| GHCR | `docker-credential-gh` | Bundled with `gh` CLI (via `gh auth setup-docker`) |

### Storing Credentials Safely

- **Never** put registry passwords in Dockerfiles, scripts, or environment files committed to git.
- Use CI/CD secrets (GitHub Actions secrets, GitLab CI variables) for automated pipelines.
- Use credential helpers for local development.
- Rotate tokens and passwords regularly.

---

## Multi-Architecture Builds

Build images that run on both AMD64 (Intel/AMD) and ARM64 (Apple Silicon, Graviton):

### Setup

```bash
# Create a builder with multi-platform support
docker buildx create --name multiarch --driver docker-container --use

# Verify platforms
docker buildx inspect --bootstrap
```

### Build and Push

```bash
# Build for multiple platforms and push directly
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t myapp:1.2.3 \
  --push \
  .
```

**Note:** Multi-platform builds with `--push` push a manifest list. You cannot `--load` multi-platform images into the local daemon.

### Platform-Specific Builds

```bash
# Build only for ARM64 and load locally
docker buildx build --platform linux/arm64 -t myapp:1.2.3 --load .

# Build for AMD64 for CI (on ARM Mac)
docker buildx build --platform linux/amd64 -t myapp:1.2.3-amd64 --load .
```

### Platform-Aware Dockerfile

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.22-alpine AS builder
ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

WORKDIR /app
COPY . .
RUN GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -o /app/server

FROM alpine:3.19
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]
```

### CI Example (GitHub Actions)

```yaml
- name: Set up Docker Buildx
  uses: docker/setup-buildx-action@v3

- name: Build and push multi-arch
  uses: docker/build-push-action@v5
  with:
    context: .
    platforms: linux/amd64,linux/arm64
    push: true
    tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

---

## Vulnerability Scanning

### Docker Scout (Built-in)

```bash
# Scan for CVEs
docker scout cves myapp:1.2.3

# Quick overview
docker scout quickview myapp:1.2.3

# Base image recommendations
docker scout recommendations myapp:1.2.3

# Compare two images
docker scout compare myapp:1.2.3 --to myapp:1.2.2
```

### Trivy

```bash
# Scan an image
trivy image myapp:1.2.3

# Scan with severity filter
trivy image --severity HIGH,CRITICAL myapp:1.2.3

# Scan and fail on critical (for CI)
trivy image --exit-code 1 --severity CRITICAL myapp:1.2.3

# Scan a Dockerfile for misconfigurations
trivy config Dockerfile
```

### Grype

```bash
# Scan an image
grype myapp:1.2.3

# Output as JSON (for CI processing)
grype -o json myapp:1.2.3

# Fail on high or critical
grype --fail-on high myapp:1.2.3
```

### Scanning in CI vs Runtime

| When | Tool | Purpose |
|------|------|---------|
| Build time | trivy, grype, docker scout | Catch vulnerabilities before push |
| Registry | ECR scanning, Artifact Analysis | Continuous scanning of stored images |
| Runtime | Falco, Sysdig | Detect runtime anomalies and exploits |
| Admission | OPA Gatekeeper, Kyverno | Block unscanned or vulnerable images from deploying |

---

## Image Signing

### Cosign (Sigstore)

```bash
# Generate a key pair (first time)
cosign generate-key-pair

# Sign an image
cosign sign --key cosign.key myregistry.com/myapp:1.2.3

# Keyless signing (uses OIDC identity)
cosign sign myregistry.com/myapp:1.2.3

# Verify a signature
cosign verify --key cosign.pub myregistry.com/myapp:1.2.3

# Keyless verification
cosign verify \
  --certificate-identity=user@example.com \
  --certificate-oidc-issuer=https://accounts.google.com \
  myregistry.com/myapp:1.2.3
```

### Notation (Notary v2)

```bash
# Sign an image
notation sign myregistry.com/myapp:1.2.3

# Verify
notation verify myregistry.com/myapp:1.2.3
```

### CI Integration (GitHub Actions with Cosign)

```yaml
- name: Install Cosign
  uses: sigstore/cosign-installer@v3

- name: Sign image
  env:
    COSIGN_EXPERIMENTAL: 1
  run: |
    cosign sign --yes ghcr.io/${{ github.repository }}@${{ steps.build.outputs.digest }}
```

---

## Cleanup

### Local Cleanup

```bash
# Remove all stopped containers, unused networks, dangling images, and build cache
docker system prune

# Remove ALL unused images (not just dangling)
docker system prune -a

# Check disk usage
docker system df
docker system df -v    # Verbose (per-image breakdown)

# Targeted cleanup
docker container prune  # Remove stopped containers
docker image prune -a   # Remove unused images
docker volume prune     # Remove unused volumes (WARNING: data loss)
docker builder prune    # Remove build cache
```

### ECR Lifecycle Policies

Automatically clean up old images in ECR:

```json
{
  "rules": [
    {
      "rulePriority": 1,
      "description": "Keep last 10 tagged images",
      "selection": {
        "tagStatus": "tagged",
        "tagPrefixList": ["v"],
        "countType": "imageCountMoreThan",
        "countNumber": 10
      },
      "action": { "type": "expire" }
    },
    {
      "rulePriority": 2,
      "description": "Remove untagged images older than 7 days",
      "selection": {
        "tagStatus": "untagged",
        "countType": "sinceImagePushed",
        "countUnit": "days",
        "countNumber": 7
      },
      "action": { "type": "expire" }
    }
  ]
}
```

```bash
# Apply lifecycle policy
aws ecr put-lifecycle-policy \
  --repository-name myapp \
  --lifecycle-policy-text file://lifecycle-policy.json
```

### GHCR Cleanup

```bash
# List package versions
gh api user/packages/container/myapp/versions

# Delete a specific version
gh api --method DELETE user/packages/container/myapp/versions/<version-id>
```

For automated GHCR cleanup, use the `actions/delete-package-versions` GitHub Action.
