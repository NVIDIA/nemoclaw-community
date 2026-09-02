---
name: kubernetes-platform-docker-containers
description: Master Docker containerization, image building, optimization, and container registry management. Learn containerization best practices and image security.
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 01-cluster-admin
bond_type: PRIMARY_BOND
capabilities: ["Multi-stage builds", "Image optimization", "Registry management", "Container security", "Build caching", "Distroless images", "Image scanning", "OCI compliance"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["build", "optimize", "scan", "push", "inspect"]
    dockerfile_path:
      type: string
    registry:
      type: string
    target_size:
      type: string
output_schema:
  type: object
  properties:
    image_info:
      type: object
    vulnerabilities:
      type: array
    optimization_suggestions:
      type: array
---

# Docker & Containers

## Executive Summary
Production-grade container image building and management covering multi-stage builds, image optimization, security scanning, and registry operations. This skill provides deep expertise in creating minimal, secure, and efficient container images following industry best practices and OCI specifications.

## Core Competencies

### 1. Production-Grade Multi-Stage Builds

**Optimized Node.js Application**
```dockerfile
# Stage 1: Dependencies
FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production && npm cache clean --force

# Stage 2: Build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 3: Production
FROM gcr.io/distroless/nodejs20-debian12 AS production
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./

ENV NODE_ENV=production
USER nonroot:nonroot
EXPOSE 3000
CMD ["dist/server.js"]
```

**Optimized Go Application**
```dockerfile
# Stage 1: Build
FROM golang:1.22-alpine AS builder
RUN apk add --no-cache git ca-certificates tzdata
WORKDIR /app

# Cache dependencies
COPY go.mod go.sum ./
RUN go mod download && go mod verify

# Build
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags="-w -s -X main.version=${VERSION}" \
    -o /app/server ./cmd/server

# Stage 2: Production (scratch)
FROM scratch AS production
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo
COPY --from=builder /app/server /server

USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["/server"]
```

**Optimized Python Application**
```dockerfile
# Stage 1: Dependencies
FROM python:3.12-slim AS builder
WORKDIR /app

RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.in-project true

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-interaction --no-ansi

# Stage 2: Production
FROM python:3.12-slim AS production
WORKDIR /app

# Create non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# Copy virtual environment
COPY --from=builder /app/.venv /app/.venv
COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER appuser:appgroup
EXPOSE 8000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:app"]
```

### 2. Image Optimization Strategies

**Layer Optimization Checklist**
```
┌─────────────────────────────────────────────────────────────┐
│              IMAGE OPTIMIZATION CHECKLIST                    │
├─────────────────────────────────────────────────────────────┤
│ ✓ Use minimal base images (alpine, distroless, scratch)    │
│ ✓ Multi-stage builds to exclude build tools                │
│ ✓ Combine RUN commands to reduce layers                    │
│ ✓ Order layers by change frequency (least → most)          │
│ ✓ Use .dockerignore to exclude unnecessary files           │
│ ✓ Clean package manager cache in same RUN command          │
│ ✓ Use specific version tags, avoid :latest                 │
│ ✓ Set appropriate user permissions                         │
│ ✓ Use COPY instead of ADD when possible                    │
│ ✓ Leverage build cache effectively                         │
└─────────────────────────────────────────────────────────────┘
```

**Optimized .dockerignore**
```
# Git
.git
.gitignore

# Dependencies
node_modules
.venv
vendor

# Build artifacts
dist
build
*.egg-info

# IDE and editors
.idea
.vscode
*.swp
*.swo

# Testing
coverage
.pytest_cache
__pycache__

# Documentation
docs
*.md
!README.md

# CI/CD
.github
.gitlab-ci.yml
Jenkinsfile

# Docker
Dockerfile*
docker-compose*
.docker

# Secrets and config
.env*
*.pem
*.key
secrets/
```

**Base Image Comparison**
```
┌──────────────────┬────────────┬─────────────────────────────────┐
│ Base Image       │ Size       │ Use Case                        │
├──────────────────┼────────────┼─────────────────────────────────┤
│ ubuntu:22.04     │ ~77MB      │ Debugging, full tooling         │
│ debian:slim      │ ~52MB      │ Compatibility, some tools       │
│ alpine:3.19      │ ~7MB       │ Small size, musl libc           │
│ distroless       │ ~2-20MB    │ Minimal, no shell               │
│ scratch          │ 0MB        │ Static binaries only            │
│ chainguard       │ ~2-10MB    │ Security-focused, maintained    │
└──────────────────┴────────────┴─────────────────────────────────┘
```

### 3. Container Security

**Security-Hardened Dockerfile**
```dockerfile
FROM node:20-alpine AS builder
# ... build steps ...

FROM gcr.io/distroless/nodejs20-debian12

# Use digest for immutability
# FROM gcr.io/distroless/nodejs20-debian12@sha256:abc123...

WORKDIR /app

# Copy only necessary files
COPY --from=builder --chown=nonroot:nonroot /app/dist ./dist
COPY --from=builder --chown=nonroot:nonroot /app/node_modules ./node_modules
COPY --from=builder --chown=nonroot:nonroot /app/package.json ./

# Security labels
LABEL org.opencontainers.image.source="https://github.com/org/repo"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.vendor="MyCompany"

# Run as non-root
USER nonroot:nonroot

# Read-only filesystem compatible
VOLUME ["/tmp"]

ENV NODE_ENV=production
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["/nodejs/bin/node", "-e", "require('http').get('http://localhost:3000/health')"]

ENTRYPOINT ["/nodejs/bin/node"]
CMD ["dist/server.js"]
```

**Image Scanning with Trivy**
```bash
# Scan image for vulnerabilities
trivy image --severity HIGH,CRITICAL myapp:latest

# Scan with SARIF output for GitHub
trivy image --format sarif --output results.sarif myapp:latest

# Scan and fail on critical
trivy image --exit-code 1 --severity CRITICAL myapp:latest

# Generate SBOM
trivy image --format cyclonedx --output sbom.json myapp:latest
```

**Image Signing with Cosign**
```bash
# Generate key pair
cosign generate-key-pair

# Sign image
cosign sign --key cosign.key myregistry.io/myapp:v1.0.0

# Verify signature
cosign verify --key cosign.pub myregistry.io/myapp:v1.0.0

# Keyless signing (GitHub Actions)
cosign sign --yes \
  --oidc-issuer=https://token.actions.githubusercontent.com \
  myregistry.io/myapp:${{ github.sha }}
```

### 4. Registry Management

**Multi-Registry Push Configuration**
```bash
# Build with BuildKit
DOCKER_BUILDKIT=1 docker build \
  --platform linux/amd64,linux/arm64 \
  --push \
  --cache-from type=registry,ref=myregistry.io/myapp:cache \
  --cache-to type=registry,ref=myregistry.io/myapp:cache,mode=max \
  -t myregistry.io/myapp:v1.0.0 \
  -t myregistry.io/myapp:latest \
  .

# Push to multiple registries
for registry in docker.io gcr.io ghcr.io; do
  docker tag myapp:v1.0.0 $registry/myorg/myapp:v1.0.0
  docker push $registry/myorg/myapp:v1.0.0
done
```

**Registry Authentication in Kubernetes**
```yaml
# ImagePullSecret for private registry
apiVersion: v1
kind: Secret
metadata:
  name: regcred
  namespace: production
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: |
    eyJhdXRocyI6eyJteXJlZ2lzdHJ5LmF6dXJlY3IuaW8iOnsiYXV0aCI6IlkyeH...
---
# Usage in Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  template:
    spec:
      imagePullSecrets:
      - name: regcred
      containers:
      - name: app
        image: myregistry.azurecr.io/myapp:v1.0.0@sha256:abc123...
```

### 5. Build Optimization

**BuildKit Caching Strategies**
```dockerfile
# syntax=docker/dockerfile:1.6

FROM node:20-alpine AS builder

# Mount cache for npm
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Mount secrets without embedding in image
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm install @private/package

# Mount ssh for private repos
RUN --mount=type=ssh \
    git clone git@github.com:org/private-repo.git
```

**GitHub Actions CI/CD**
```yaml
name: kubernetes-platform-docker-containers

on:
  push:
    branches: [main]
    tags: ['v*']

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      id-token: write  # For keyless signing
      security-events: write  # For SARIF upload

    steps:
    - uses: actions/checkout@v4

    - name: Set up QEMU
      uses: docker/setup-qemu-action@v3

    - name: Set up Docker Buildx
      uses: docker/setup-buildx-action@v3

    - name: Login to Container Registry
      uses: docker/login-action@v3
      with:
        registry: ${{ env.REGISTRY }}
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}

    - name: Extract metadata
      id: meta
      uses: docker/metadata-action@v5
      with:
        images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
        tags: |
          type=semver,pattern={{version}}
          type=semver,pattern={{major}}.{{minor}}
          type=sha,prefix=

    - name: Build and push
      uses: docker/build-push-action@v5
      with:
        context: .
        platforms: linux/amd64,linux/arm64
        push: true
        tags: ${{ steps.meta.outputs.tags }}
        labels: ${{ steps.meta.outputs.labels }}
        cache-from: type=gha
        cache-to: type=gha,mode=max
        provenance: true
        sbom: true

    - name: Run Trivy vulnerability scanner
      uses: aquasecurity/trivy-action@master
      with:
        image-ref: '${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}'
        format: 'sarif'
        output: 'trivy-results.sarif'
        severity: 'CRITICAL,HIGH'

    - name: Upload Trivy scan results
      uses: github/codeql-action/upload-sarif@v2
      with:
        sarif_file: 'trivy-results.sarif'

    - name: Install Cosign
      uses: sigstore/cosign-installer@v3

    - name: Sign image
      run: |
        cosign sign --yes ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}@${{ steps.build.outputs.digest }}
```

## Integration Patterns

### Used by skill: **cluster-admin**
- Node container runtime configuration
- Registry credentials management
- Image pull policies

### Coordinates with skill: **security**
- Image vulnerability scanning
- Signature verification
- Supply chain security

### Works with skill: **gitops**
- Image promotion workflows
- Automated deployments
- Version management

## Troubleshooting Guide

### Decision Tree: Build Issues

```
Docker Build Problem?
│
├── Build fails at COPY/ADD
│   ├── Check: file exists in build context
│   ├── Check: .dockerignore not excluding file
│   └── Verify: correct relative paths
│
├── Build slow
│   ├── Check: layer ordering (frequent changes last)
│   ├── Enable: BuildKit (DOCKER_BUILDKIT=1)
│   ├── Use: cache mounts for package managers
│   └── Verify: .dockerignore excludes large files
│
├── Image too large
│   ├── Use: multi-stage builds
│   ├── Switch: to smaller base image
│   ├── Clean: caches in same RUN command
│   └── Analyze: with dive tool
│
└── Security vulnerabilities
    ├── Update: base image to latest patch
    ├── Minimize: installed packages
    ├── Use: distroless or scratch
    └── Scan: regularly with Trivy
```

### Debug Commands Cheatsheet

```bash
# Inspect image layers and size
docker history myapp:latest --no-trunc
dive myapp:latest  # Interactive layer analysis

# Debug build
DOCKER_BUILDKIT=1 docker build --progress=plain -t myapp .
docker build --no-cache -t myapp .

# Inspect image metadata
docker inspect myapp:latest
docker inspect --format='{{.Config.Labels}}' myapp:latest
skopeo inspect docker://myregistry.io/myapp:latest

# Test image locally
docker run --rm -it --entrypoint=/bin/sh myapp:latest
docker run --rm myapp:latest cat /etc/os-release

# Check for secrets in image
docker history --no-trunc myapp:latest | grep -i secret
trivy image --scanners secret myapp:latest

# Analyze vulnerabilities
trivy image --severity CRITICAL myapp:latest
grype myapp:latest

# Export filesystem
docker export $(docker create myapp:latest) | tar -tvf - | head -100
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Large image size | Multi-stage builds, distroless base |
| Slow builds | BuildKit caching, layer optimization |
| Security vulnerabilities | Regular base image updates, minimal installs |
| Cache invalidation | Order commands by change frequency |
| Multi-arch support | Docker Buildx with QEMU |
| Private dependencies | Build secrets, SSH mounts |
| Image provenance | Cosign signing, SLSA attestations |
| Registry limits | Use caching registry, rate limit handling |

## Success Criteria

| Metric | Target |
|--------|--------|
| Image size reduction | >50% from naive builds |
| Build time (cached) | <2 minutes |
| Critical vulnerabilities | 0 |
| High vulnerabilities | <5 |
| Image signature | 100% production images |
| Multi-arch support | amd64 + arm64 |
| SBOM generation | 100% |

## Resources
- [Docker Documentation](https://docs.docker.com/)
- [Best Practices for Writing Dockerfiles](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
- [Distroless Images](https://github.com/GoogleContainerTools/distroless)
- [Trivy Scanner](https://aquasecurity.github.io/trivy/)
- [Cosign Signing](https://docs.sigstore.dev/cosign/overview/)
