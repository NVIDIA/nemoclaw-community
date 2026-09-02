---
name: docker-docker
description: "Docker operations, Dockerfile best practices, Compose, and image optimization. Trigger for: Docker, Dockerfile, container, image, docker-compose, multi-stage build, layer caching, distroless, container registry, ECR, GCR, GHCR, docker build, docker run, docker exec, docker logs, volume mounts, port mapping, container networking, image optimization, BuildKit. Implicit queries: \"make my image smaller\", \"container won't start\", \"build is slow\", \"reduce image size\", \"set up local dev environment\", \"why is my container crashing\", \"optimize layers\", \"hot reload in docker\". Trigger even without the word Docker."
---

# Docker Operations & Best Practices

This skill covers Docker operations (building, running, debugging containers), Dockerfile best practices, Docker Compose workflows, image optimization, and registry management.

**Scripts:** Always run scripts with `--help` first. Do not read script source unless debugging the script itself.

**References:** Load reference files on demand based on the task at hand. Do not pre-load all references.

**Slash commands:** Users can also invoke these directly:
- `/docker-skills:docker-debug [container]` — Diagnose a running or failed container
- `/docker-skills:docker-build [context]` — Build, tag, and validate a Docker image
- `/docker-skills:docker-optimize [image]` — Analyze an image and suggest size reductions

---

## Quick Command Reference

| Category | Command | Purpose |
|----------|---------|---------|
| **Build** | `docker build -t <name>:<tag> .` | Build image from Dockerfile in current dir |
| **Build** | `docker build -f Dockerfile.prod -t <name>:<tag> .` | Build from specific Dockerfile |
| **Build** | `DOCKER_BUILDKIT=1 docker build --progress=plain -t <name> .` | Build with BuildKit and full output |
| **Run** | `docker run -d --name <name> -p <host>:<container> <image>` | Run detached with port mapping |
| **Run** | `docker run --rm -it <image> /bin/sh` | Interactive shell, auto-remove on exit |
| **Run** | `docker run -v $(pwd):/app -w /app <image> <cmd>` | Run with bind mount and working dir |
| **Run** | `docker run --env-file .env <image>` | Run with environment file |
| **Inspect** | `docker ps -a` | List all containers (including stopped) |
| **Inspect** | `docker logs <container> --tail=100 -f` | Follow last 100 log lines |
| **Inspect** | `docker inspect <container>` | Full container metadata as JSON |
| **Inspect** | `docker exec -it <container> /bin/sh` | Shell into running container |
| **Inspect** | `docker stats` | Live CPU/memory/IO for all containers |
| **Inspect** | `docker diff <container>` | Show filesystem changes in container |
| **Clean** | `docker system prune -a` | Remove all unused images, containers, networks |
| **Clean** | `docker volume prune` | Remove all unused volumes |
| **Clean** | `docker builder prune` | Remove build cache |
| **Network** | `docker network ls` | List networks |
| **Network** | `docker network inspect <network>` | Show network details and connected containers |
| **Volume** | `docker volume ls` | List volumes |
| **Compose** | `docker compose up -d` | Start all services detached |
| **Compose** | `docker compose down -v` | Stop and remove containers, networks, and volumes |
| **Compose** | `docker compose logs -f <service>` | Follow logs for a service |
| **Compose** | `docker compose ps` | List running Compose services |

---

## Dockerfile Best Practices Quick Ref

Follow these rules in order of importance:

1. **Use specific base image tags** — Never use `:latest` in production. Pin to a digest or exact version (e.g., `node:20.11-alpine3.19`).

2. **Order layers from least to most frequently changing:**
   ```
   FROM base          # Rarely changes
   RUN apt-get ...    # OS deps change infrequently
   COPY package.json  # Dependency manifest changes sometimes
   RUN npm install    # Deps rebuild only when manifest changes
   COPY . .           # App code changes every build
   RUN npm run build  # Build step runs on code changes
   ```

3. **Use multi-stage builds** — Separate build-time tools from runtime image. Build stage installs compilers, dev dependencies; runtime stage copies only artifacts.

4. **Combine RUN commands** — Merge related `RUN` instructions with `&&` to reduce layers. Always clean up in the same layer (`apt-get install && rm -rf /var/lib/apt/lists/*`).

5. **Leverage BuildKit cache mounts** — Use `--mount=type=cache,target=/root/.npm` for package manager caches to speed up rebuilds.

6. **Use `.dockerignore`** — Exclude `.git`, `node_modules`, `__pycache__`, `.env`, `*.md`, test fixtures, and build artifacts.

7. **Run as non-root** — Add `USER nonroot` or `USER 1001` after creating the user. Never run production containers as root.

8. **Use COPY, not ADD** — `ADD` has implicit tar extraction and URL fetching. Use `COPY` unless you specifically need those features.

9. **Prefer exec form for CMD/ENTRYPOINT** — Use `CMD ["node", "server.js"]` not `CMD node server.js`. Exec form handles signals correctly.

10. **Add HEALTHCHECK** — Define health endpoints so orchestrators can detect unhealthy containers.

11. **Pin package versions** — Use `apt-get install curl=7.88.1-10` and lock files for reproducible builds.

12. **Don't store secrets in images** — Use BuildKit `--mount=type=secret` for build-time secrets. Never use `ARG` or `ENV` for secrets.

For complete Dockerfile patterns with multi-stage examples for Go, Node.js, Python, and Java, read [Dockerfile Reference](./references/dockerfile.md).

---

## Docker Compose Quick Ref

### Service Pattern

```yaml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=production
    env_file:
      - .env
    volumes:
      - ./src:/app/src          # Bind mount for dev hot-reload
      - node_modules:/app/node_modules  # Named volume for deps
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - backend
```

### Key Patterns

- **depends_on with healthcheck** — Use `condition: service_healthy` so services wait for real readiness, not just container start.
- **Named volumes** — Use for persistent data (databases). Survive `docker compose down`.
- **Bind mounts** — Use for development hot-reload. Map host code into container.
- **Custom networks** — Services on the same network reach each other by service name (DNS).
- **env_file** — Keep secrets out of `docker-compose.yml`. Use `.env` for local, `env_file:` for explicit files.
- **Variable interpolation** — Use `${VAR:-default}` in compose files. Docker Compose reads `.env` automatically.
- **Profiles** — Tag optional services (e.g., monitoring, debug) with `profiles: [debug]`. Start with `--profile debug`.
- **Override files** — `docker-compose.override.yml` auto-loaded for local dev overrides. Use `-f base.yml -f prod.yml` for environments.

For complete Compose patterns including networking, profiles, multi-file setups, and a full-stack example, read [Compose Reference](./references/compose.md).

---

## Container Troubleshooting Decision Tree

Follow the diagnostic path: **ps → logs → inspect → exec**

```
Container not working?
│
├─ Won't start at all
│  ├─ Check: docker logs <container>
│  ├─ Check: docker inspect <container> → State.Error
│  ├─ Entrypoint/CMD error?
│  │  ├─ "exec format error" → Wrong platform or missing shebang
│  │  ├─ "not found" → Binary missing or wrong base image
│  │  └─ "permission denied" → File not executable or USER lacks permissions
│  ├─ Missing dependencies?
│  │  └─ "shared library not found" → Missing OS packages in runtime image
│  └─ Port conflict?
│     └─ "address already in use" → Another process using that port
│
├─ Exits immediately (code 0 or 1)
│  ├─ Exit code 0 → CMD completed and exited. Need a foreground process
│  ├─ Exit code 1 → Application error on startup. Check logs
│  ├─ Using shell form? → Switch to exec form for proper signal handling
│  └─ Check: docker run -it <image> /bin/sh → Debug interactively
│
├─ OOMKilled (exit code 137)
│  ├─ Check: docker inspect <container> | jq '.[0].State.OOMKilled'
│  ├─ Check: docker stats (watch memory usage)
│  ├─ Increase --memory limit
│  └─ Profile application for memory leaks
│
├─ Networking issues
│  ├─ Port not accessible?
│  │  ├─ Check: docker port <container> → Verify port mapping
│  │  ├─ App binding to localhost? → Must bind to 0.0.0.0 inside container
│  │  └─ Firewall? → Check host firewall rules
│  ├─ Container-to-container DNS fails?
│  │  ├─ Same network? → docker network inspect <network>
│  │  └─ Use service name, not container ID, for DNS
│  └─ Can't reach host?
│     └─ Use host.docker.internal (Docker Desktop) or --network host
│
├─ Volume/mount issues
│  ├─ Permission denied on mounted files?
│  │  ├─ UID/GID mismatch between host and container user
│  │  └─ Fix: match USER uid with host file owner, or use --user flag
│  ├─ Files not appearing?
│  │  ├─ Wrong host path → Use absolute paths
│  │  └─ Named volume masking bind mount → Check volume precedence
│  └─ Data lost on restart?
│     └─ Use named volumes, not anonymous volumes
│
└─ Build fails
   ├─ COPY file not found → File excluded by .dockerignore or wrong context
   ├─ apt-get fails → Add --no-install-recommends, run apt-get update first
   ├─ Cache not working → Layer ordering wrong (see best practices above)
   └─ BuildKit syntax error → Check # syntax=docker/dockerfile:1 directive
```

For detailed troubleshooting with step-by-step resolution for every error state, read [Troubleshooting Guide](./references/troubleshooting.md).

---

## Image Optimization Checklist

Follow these steps to reduce image size, roughly in order of impact:

1. **Switch to a smaller base image** — `alpine` (5 MB), `slim` (80 MB), `distroless` (20 MB), or `scratch` (0 B) instead of full Debian/Ubuntu (120+ MB).

2. **Use multi-stage builds** — Build in a full image, copy only the binary/artifacts to a minimal runtime image. Typical 10x-50x reduction.

3. **Remove build dependencies** — Don't install compilers, headers, or dev packages in the final stage.

4. **Clean up package manager caches in the same layer** — `RUN apt-get install -y pkg && rm -rf /var/lib/apt/lists/*` (must be same `RUN` to save space).

5. **Use `.dockerignore`** — Prevent `.git/` (often 100+ MB), `node_modules/`, test fixtures, and docs from entering build context.

6. **Minimize layers** — Combine related `RUN` commands. Each layer adds overhead.

7. **Use BuildKit cache mounts** — `--mount=type=cache` for pip, npm, apt caches. Faster builds without bloating the image.

8. **Strip binaries** — For compiled languages, strip debug symbols (`strip --strip-all binary` or `-ldflags="-s -w"` in Go).

9. **Audit with dive** — Run `dive <image>` to inspect each layer and find wasted space.

10. **Check with docker scout** — Run `docker scout cves <image>` to find vulnerabilities and `docker scout recommendations <image>` for base image suggestions.

11. **Use `docker history`** — Run `docker history <image>` to see per-layer sizes and identify bloated layers.

12. **Compress assets** — For web apps, pre-compress static files. Remove source maps in production.

For multi-stage Dockerfile examples and base image comparison, read [Dockerfile Reference](./references/dockerfile.md).

---

## Diagnostic Scripts

### Image Audit

Run `bash scripts/image-audit.sh --help` for full usage.

Analyzes a Docker image for size optimization opportunities: layer-by-layer breakdown, identifies large files, detects unnecessary packages, checks for common anti-patterns (running as root, no healthcheck, unneeded cache dirs).

```bash
# Audit a specific image
bash scripts/image-audit.sh myapp:latest

# Audit with detailed layer breakdown
bash scripts/image-audit.sh myapp:latest --layers

# Compare two images
bash scripts/image-audit.sh myapp:v1 --compare myapp:v2
```

### Compose Check

Run `bash scripts/compose-check.sh --help` for full usage.

Validates a Docker Compose file: checks for missing healthchecks, hardcoded secrets, missing restart policies, privileged mode, volume backup needs, and network isolation gaps.

```bash
# Check compose file in current directory
bash scripts/compose-check.sh

# Check a specific file
bash scripts/compose-check.sh -f docker-compose.prod.yml

# Check with strict mode (warnings become errors)
bash scripts/compose-check.sh --strict
```

---

## Reference Files

Load these references as needed based on the task:

- **[Dockerfile Reference](./references/dockerfile.md)** — Complete Dockerfile guide:
  - Base image comparison (alpine, slim, distroless, scratch)
  - Multi-stage build patterns for Go, Node.js, Python, Java
  - Layer caching strategy and BuildKit features
  - Security best practices and production-ready examples

- **[Compose Reference](./references/compose.md)** — Docker Compose patterns:
  - Service definitions, networking, and volume management
  - depends_on with healthchecks for reliable startup ordering
  - Development patterns (hot-reload, debugger, override files)
  - Complete full-stack example with web, database, cache, and worker

- **[Registry Reference](./references/registry.md)** — Registry operations:
  - Image tagging strategies (semver, git SHA, why :latest is dangerous)
  - Push/pull for ECR, GCR, GHCR, and Docker Hub
  - Multi-architecture builds with buildx
  - Vulnerability scanning and image signing

- **[Troubleshooting Guide](./references/troubleshooting.md)** — Debugging workflows:
  - Container won't start, exits immediately, OOMKilled
  - Networking issues (ports, DNS, container-to-container)
  - Volume and mount permission problems
  - Build failures and slow build diagnosis

### Quick Task Reference

| Task | Action |
|------|--------|
| Container crashing or stuck | Use decision tree above. For detailed steps, read `troubleshooting.md` |
| Writing a new Dockerfile | Read `dockerfile.md` for multi-stage patterns and base image selection |
| Reducing image size | Use optimization checklist above. Run `scripts/image-audit.sh` |
| Setting up Docker Compose | Read `compose.md` for service patterns and full-stack example |
| Pushing to a registry | Read `registry.md` for auth setup and tagging strategies |
| Multi-arch builds | Read `registry.md` for buildx setup and manifest lists |
| Debugging network issues | Use decision tree above. Read `troubleshooting.md` for detailed steps |
| Build is slow | Check `.dockerignore`, layer ordering, BuildKit cache. Read `dockerfile.md` |
| Hot-reload in dev | Read `compose.md` for bind mount and override patterns |
| Scanning for vulnerabilities | Read `registry.md` for docker scout, trivy, and grype |
| Validating compose file | Run `scripts/compose-check.sh` |
| Auditing image size | Run `scripts/image-audit.sh <image>` |
