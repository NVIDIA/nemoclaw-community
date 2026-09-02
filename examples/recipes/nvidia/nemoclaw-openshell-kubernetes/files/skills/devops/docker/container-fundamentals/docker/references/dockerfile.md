# Dockerfile Reference

Comprehensive guide to writing production-quality Dockerfiles: base image selection, multi-stage builds, layer caching, BuildKit features, security, and complete examples.

---

## Base Image Selection

Choose the smallest base image that meets your runtime requirements:

| Base Image | Size | Use Case | Trade-offs |
|------------|------|----------|------------|
| `scratch` | 0 B | Static Go binaries, Rust binaries | No shell, no debugging tools, no libc |
| `alpine` | ~5 MB | Most production workloads | Uses musl libc (rare compat issues), apk package manager |
| `distroless` | ~20 MB | Security-sensitive production | No shell, no package manager, minimal attack surface |
| `*-slim` (e.g., `debian-slim`) | ~80 MB | Apps needing glibc, broader package availability | Larger than alpine but avoids musl issues |
| `debian` / `ubuntu` | ~120 MB | Full toolchain needed, development, CI | Large, but widest compatibility |

### Decision Guide

- **Go, Rust (static binary):** Use `scratch` or `distroless/static`
- **Node.js:** Use `node:<version>-alpine` or `gcr.io/distroless/nodejs<version>-debian12`
- **Python:** Use `python:<version>-slim` (alpine has issues with compiled packages like numpy)
- **Java:** Use `eclipse-temurin:<version>-jre-alpine` or `gcr.io/distroless/java<version>-debian12`
- **General-purpose:** Start with `alpine`, fall back to `slim` if you hit musl issues

### Pinning Versions

```dockerfile
# Bad: unpredictable, changes without warning
FROM node:latest
FROM node:20

# Good: specific patch version
FROM node:20.11-alpine3.19

# Best: pinned to digest (immutable)
FROM node:20.11-alpine3.19@sha256:abcdef1234567890...
```

---

## Multi-Stage Builds

Use multi-stage builds to separate build-time dependencies from the runtime image. The final image contains only what the application needs to run.

### Go

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /app/server ./cmd/server

FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/server /server
EXPOSE 8080
ENTRYPOINT ["/server"]
```

**Result:** ~10-20 MB (vs ~300 MB with full Go image)

### Node.js

```dockerfile
# syntax=docker/dockerfile:1
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production

FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -D appuser
COPY --from=deps /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./
USER appuser
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://localhost:3000/health || exit 1
CMD ["node", "dist/index.js"]
```

**Key:** Separate `deps` stage (production only) from `builder` stage (all deps + build). Runtime gets only production deps and built artifacts.

### Python

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
WORKDIR /app
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app appuser
COPY --from=builder /install /usr/local
COPY . .
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "app:create_app()"]
```

**Key:** Install compiled dependencies (gcc, build-essential) only in builder. Copy installed packages to runtime via `--prefix=/install`.

### Java

```dockerfile
# syntax=docker/dockerfile:1
FROM eclipse-temurin:21-jdk-alpine AS builder
WORKDIR /app
COPY gradle/ gradle/
COPY gradlew build.gradle.kts settings.gradle.kts ./
RUN ./gradlew dependencies --no-daemon
COPY src/ src/
RUN ./gradlew bootJar --no-daemon

FROM eclipse-temurin:21-jre-alpine AS runtime
WORKDIR /app
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -D appuser
COPY --from=builder /app/build/libs/*.jar app.jar
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://localhost:8080/actuator/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
```

**Key:** Use JDK for building, JRE for runtime. Copy only the fat JAR. The JRE-alpine image is ~100 MB vs ~400 MB for full JDK.

---

## Layer Caching Strategy

Docker caches each layer. If a layer changes, all subsequent layers are invalidated. The golden rule: **order layers from least frequently changing to most frequently changing.**

### Correct Ordering

```dockerfile
# 1. Base image (rarely changes)
FROM node:20-alpine

# 2. System dependencies (change infrequently)
RUN apk add --no-cache curl

# 3. Set working directory
WORKDIR /app

# 4. Dependency manifests (change sometimes)
COPY package.json package-lock.json ./

# 5. Install dependencies (rebuilds only when manifests change)
RUN npm ci

# 6. Application code (changes every build)
COPY . .

# 7. Build step (runs on code changes)
RUN npm run build
```

### Common Mistakes

```dockerfile
# WRONG: Copying everything first busts the cache for npm install every time
COPY . .
RUN npm install

# RIGHT: Copy only manifests, install, then copy code
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
```

```dockerfile
# WRONG: apt-get update and install in separate layers
# If the install layer changes, the update layer is cached (stale index)
RUN apt-get update
RUN apt-get install -y curl

# RIGHT: Always combine update + install + cleanup
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*
```

---

## BuildKit Features

Enable BuildKit for faster builds and advanced features:

```bash
# Enable BuildKit
export DOCKER_BUILDKIT=1

# Or prefix individual commands
DOCKER_BUILDKIT=1 docker build .
```

### Cache Mounts

Persist package manager caches between builds without including them in the image:

```dockerfile
# syntax=docker/dockerfile:1

# npm cache
RUN --mount=type=cache,target=/root/.npm npm ci

# pip cache
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# apt cache
RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt/lists \
    apt-get update && apt-get install -y curl

# Go module cache
RUN --mount=type=cache,target=/go/pkg/mod go mod download

# Maven cache
RUN --mount=type=cache,target=/root/.m2 mvn package -DskipTests
```

### Secret Mounts

Pass secrets at build time without embedding them in the image:

```dockerfile
# syntax=docker/dockerfile:1

# Use a secret file
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci

# Build command:
# docker build --secret id=npmrc,src=$HOME/.npmrc .
```

### SSH Mounts

Forward SSH agent for private repo access during build:

```dockerfile
# syntax=docker/dockerfile:1

RUN --mount=type=ssh git clone git@github.com:org/private-repo.git

# Build command:
# docker build --ssh default .
```

### Parallel Builds

BuildKit automatically parallelizes independent stages:

```dockerfile
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/ .
RUN npm ci && npm run build

FROM python:3.12-slim AS backend
WORKDIR /backend
COPY backend/ .
RUN pip install -r requirements.txt

FROM nginx:alpine AS final
COPY --from=frontend /frontend/dist /usr/share/nginx/html
COPY --from=backend /backend /app
```

The `frontend` and `backend` stages build in parallel.

---

## .dockerignore

Always create a `.dockerignore` to reduce build context size and avoid leaking secrets:

```
# Version control
.git
.gitignore

# Dependencies (rebuilt in container)
node_modules
vendor
__pycache__
*.pyc
.venv
venv

# Build output
dist
build
*.o
*.a

# IDE and OS files
.vscode
.idea
*.swp
.DS_Store
Thumbs.db

# Docker files
Dockerfile*
docker-compose*
.dockerignore

# Environment and secrets
.env
.env.*
*.pem
*.key
credentials.json

# Documentation and tests
*.md
LICENSE
docs/
tests/
test/
coverage/
.nyc_output

# CI/CD
.github
.gitlab-ci.yml
.circleci
Jenkinsfile
```

**Impact:** A typical project with `.git/` and `node_modules/` can have a build context of 500+ MB. With `.dockerignore`, it drops to a few MB.

---

## Security Best Practices

### Run as Non-Root

```dockerfile
# Alpine
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -D appuser
USER appuser

# Debian/Ubuntu
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app appuser
USER appuser

# Distroless (already non-root)
FROM gcr.io/distroless/nodejs20-debian12:nonroot
```

### Drop Capabilities

Run containers with minimal privileges:

```bash
docker run --cap-drop ALL --cap-add NET_BIND_SERVICE myapp
```

### Read-Only Root Filesystem

```bash
docker run --read-only --tmpfs /tmp myapp
```

### No Secrets in Build Args

```dockerfile
# WRONG: ARG values are visible in image history
ARG DB_PASSWORD
RUN echo "password=$DB_PASSWORD" > /app/config

# RIGHT: Use secret mounts
RUN --mount=type=secret,id=db_password \
    cat /run/secrets/db_password > /app/config
```

### HEALTHCHECK

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
```

---

## ARG vs ENV

| Feature | `ARG` | `ENV` |
|---------|-------|-------|
| Available at | Build time only | Build time and runtime |
| Set from CLI | `--build-arg` | `-e` or `--env` |
| Persists in image | No (not in final image layers) | Yes |
| Visible in history | Yes (`docker history`) | Yes |
| Use for secrets | Never | Never |

### When to Use

```dockerfile
# ARG: Build-time configuration (version selection, feature flags)
ARG NODE_VERSION=20
FROM node:${NODE_VERSION}-alpine

ARG BUILD_ENV=production
RUN if [ "$BUILD_ENV" = "development" ]; then npm install; else npm ci --production; fi

# ENV: Runtime configuration
ENV PORT=3000
ENV NODE_ENV=production
ENV LOG_LEVEL=info

# Combined: ARG for build-time default, ENV for runtime override
ARG DEFAULT_PORT=3000
ENV PORT=${DEFAULT_PORT}
```

---

## ENTRYPOINT vs CMD

| Feature | `ENTRYPOINT` | `CMD` |
|---------|-------------|-------|
| Override with | `--entrypoint` | Arguments after image name |
| Purpose | Define the executable | Default arguments |
| Combined | ENTRYPOINT + CMD = full command | CMD provides default args to ENTRYPOINT |

### Exec Form vs Shell Form

```dockerfile
# Exec form (preferred): runs as PID 1, receives signals correctly
CMD ["node", "server.js"]
ENTRYPOINT ["python", "app.py"]

# Shell form: wraps in /bin/sh -c, does NOT receive signals
CMD node server.js
ENTRYPOINT python app.py
```

### Combining ENTRYPOINT and CMD

```dockerfile
# ENTRYPOINT = the binary, CMD = default arguments
ENTRYPOINT ["python", "manage.py"]
CMD ["runserver", "0.0.0.0:8000"]

# docker run myapp → python manage.py runserver 0.0.0.0:8000
# docker run myapp migrate → python manage.py migrate
```

---

## HEALTHCHECK

Define health checks so orchestrators (Compose, Swarm, K8s) can detect unhealthy containers:

```dockerfile
# HTTP health check (most common)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# TCP health check (when curl is not available)
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://localhost:8080/health || exit 1

# Custom script
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/app/healthcheck.sh"]

# For apps without HTTP (e.g., worker processes)
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD pgrep -f "worker" || exit 1
```

### Parameters

- `--interval` — Time between checks (default: 30s)
- `--timeout` — Max time for a check to complete (default: 30s)
- `--start-period` — Grace period for container startup (default: 0s)
- `--retries` — Consecutive failures before marking unhealthy (default: 3)

---

## Complete Production Examples

### Production Node.js

```dockerfile
# syntax=docker/dockerfile:1
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --production

FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build && npm prune --production

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -D appuser
COPY --from=deps /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./
RUN chown -R appuser:appgroup /app
USER appuser
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:3000/health || exit 1
CMD ["node", "dist/index.js"]
```

### Production Python (FastAPI)

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app appuser
COPY --from=builder /install /usr/local
COPY . .
RUN chown -R appuser:appgroup /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### Production Go

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /app/server ./cmd/server

FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/server /server
EXPOSE 8080
ENTRYPOINT ["/server"]
```
