# Docker Troubleshooting Guide

Symptom-driven troubleshooting: each section follows the pattern **symptoms, diagnostic commands, common causes, and fixes**.

---

## Container Won't Start

### Symptoms

- `docker run` exits immediately with an error
- `docker ps -a` shows container in `Created` or `Exited` state
- `docker compose up` shows errors and the service never becomes healthy

### Diagnostic Commands

```bash
# Check container status and exit code
docker ps -a --filter name=<container>

# Read container logs
docker logs <container>

# Inspect full container state
docker inspect <container> | jq '.[0].State'

# Check the entrypoint and command
docker inspect <container> | jq '.[0].Config.Entrypoint, .[0].Config.Cmd'

# Try running interactively to debug
docker run --rm -it --entrypoint /bin/sh <image>
```

### Common Causes and Fixes

**"exec format error"**
- Wrong platform (e.g., ARM image on AMD64 host, or vice versa)
- Script missing shebang (`#!/bin/sh` at top of entrypoint script)
- Fix: Rebuild for correct platform (`--platform linux/amd64`) or add shebang

**"not found" or "no such file or directory"**
- Binary does not exist in the image (common with multi-stage builds that forgot to COPY)
- Shell form CMD with missing `/bin/sh` (e.g., distroless images)
- Fix: Use exec form `CMD ["binary"]`, verify binary was copied in final stage

**"permission denied"**
- Entrypoint script is not executable
- Running as non-root USER but file requires root
- Fix: `RUN chmod +x entrypoint.sh` or `RUN chown appuser:appgroup /app`

**"shared library not found" / "cannot open shared object"**
- Missing OS libraries in runtime image (common when building on full image, running on alpine)
- Fix: Install required libraries in runtime stage, or use static linking (`CGO_ENABLED=0` for Go)

**"address already in use"**
- Port is already bound by another container or host process
- Fix: `docker ps` to find the conflicting container, `lsof -i :<port>` to find host process

---

## Container Exits Immediately

### Symptoms

- Container starts and immediately exits with code 0 or 1
- `docker compose up` shows service starting and stopping in a loop
- `docker ps` shows no running containers, `docker ps -a` shows Exited status

### Diagnostic Commands

```bash
# Check exit code
docker inspect <container> | jq '.[0].State.ExitCode'

# Read all logs (even if container exited)
docker logs <container>

# Run interactively to see what happens
docker run --rm -it <image>

# Override CMD to get a shell
docker run --rm -it --entrypoint /bin/sh <image>
```

### Common Causes and Fixes

**Exit code 0 — No foreground process**
- CMD runs a command that completes (e.g., `echo hello`, `ls`)
- Background daemon without `-f` or `--foreground` flag
- Fix: CMD must be a blocking foreground process. Use `CMD ["nginx", "-g", "daemon off;"]` not `CMD ["nginx"]`

**Exit code 1 — Application error**
- Crash on startup due to missing config, database not ready, bad environment variable
- Fix: Read the logs (`docker logs`), fix the application error

**Shell form vs exec form**
- Shell form (`CMD node server.js`) wraps in `/bin/sh -c`, which may exit before the child process
- Fix: Use exec form (`CMD ["node", "server.js"]`)

**PID 1 and signal handling**
- When a process is not PID 1, it may not receive SIGTERM properly
- Fix: Use exec form (runs as PID 1), or use `tini` as an init process:
  ```dockerfile
  RUN apk add --no-cache tini
  ENTRYPOINT ["/sbin/tini", "--"]
  CMD ["node", "server.js"]
  ```

**Compose restart loop**
- Service keeps restarting because `depends_on` is not waiting for readiness
- Fix: Use `depends_on` with `condition: service_healthy` and define healthchecks

---

## OOMKilled (Out of Memory)

### Symptoms

- Container exits with code 137
- Application becomes unresponsive before crashing
- `docker inspect` shows `OOMKilled: true`

### Diagnostic Commands

```bash
# Confirm OOMKilled
docker inspect <container> | jq '.[0].State.OOMKilled'

# Check current memory limit
docker inspect <container> | jq '.[0].HostConfig.Memory'

# Watch live memory usage
docker stats <container>

# Check system dmesg for OOM messages (Linux)
dmesg | grep -i oom
```

### Common Causes and Fixes

**Memory limit too low**
- Container memory limit is lower than what the application needs
- Fix: Increase `--memory` flag or `deploy.resources.limits.memory` in Compose

**Memory leak in application**
- Memory grows unbounded over time
- Fix: Profile the application, look for:
  - Unbounded caches or buffers
  - Event listeners not cleaned up
  - Large data loaded into memory
  - Node.js: use `--max-old-space-size` and heap snapshots
  - Java: tune JVM heap (`-Xmx`)
  - Python: use `tracemalloc` or `memory_profiler`

**JVM not respecting container limits**
- Older JVMs do not see container memory limits, allocate based on host memory
- Fix: Use JDK 11+ (container-aware by default) or set `-Xmx` explicitly

**Multiple processes in one container**
- Running supervisor, multiple workers, or background processes that each consume memory
- Fix: Limit worker count, or split into separate containers

---

## Networking Issues

### Symptoms

- Cannot reach the application from the host browser
- Container-to-container communication fails
- DNS resolution fails inside container
- Connection refused or timeout errors

### Diagnostic Commands

```bash
# Check port mappings
docker port <container>

# Verify container is listening
docker exec <container> netstat -tlnp
# or
docker exec <container> ss -tlnp

# Check which network the container is on
docker inspect <container> | jq '.[0].NetworkSettings.Networks'

# List networks and their containers
docker network ls
docker network inspect <network>

# DNS test from inside container
docker exec <container> nslookup <service-name>

# Connectivity test from inside container
docker exec <container> wget -qO- http://<service>:<port>/health
docker exec <container> curl -f http://<service>:<port>/health
```

### Common Causes and Fixes

**Port not accessible from host**
- Application binds to `127.0.0.1` inside the container (not accessible from outside)
- Fix: Bind to `0.0.0.0` inside the container (e.g., `--host 0.0.0.0`, `--bind 0.0.0.0`)

**Port already in use**
- Another container or host process is using the same host port
- Fix: `docker ps` to find conflicting container, `lsof -i :<port>` for host process, change port mapping

**Container-to-container DNS fails**
- Containers on different Docker networks
- Using container ID instead of service name
- Fix: Ensure both containers are on the same network. Use service name (from Compose) or container name for DNS

**Cannot reach host services from container**
- Docker Desktop: Use `host.docker.internal` hostname
- Linux: Use `--network host` or add `extra_hosts: ["host.docker.internal:host-gateway"]`

**Published vs exposed ports**
- `EXPOSE` in Dockerfile does not publish the port. It is documentation only.
- `ports:` in Compose or `-p` flag in `docker run` actually publishes the port
- Fix: Ensure the port is published, not just exposed

---

## Volume and Mount Issues

### Symptoms

- "Permission denied" when reading/writing mounted files
- Files written in container do not appear on host (or vice versa)
- Data disappears after `docker compose down`
- "No such file or directory" for a mount path

### Diagnostic Commands

```bash
# Check what is mounted
docker inspect <container> | jq '.[0].Mounts'

# Check file permissions inside container
docker exec <container> ls -la /app
docker exec <container> id    # Show UID/GID of container user

# Check host file permissions
ls -la /host/path/to/mount

# Check volume details
docker volume inspect <volume-name>
```

### Common Causes and Fixes

**Permission denied (UID/GID mismatch)**
- Container runs as a user (e.g., UID 1001) that does not match the host file owner
- Fix: Match the container USER UID to the host file owner, or use `--user $(id -u):$(id -g)` at runtime
  ```bash
  docker run --user $(id -u):$(id -g) -v $(pwd):/app myimage
  ```

**Files not appearing on host**
- Using a named volume instead of a bind mount (named volumes are managed by Docker, not visible at a simple host path)
- Fix: Use bind mount syntax (`./path:/container/path`) for host-visible files

**Data lost after docker compose down**
- Anonymous volumes are removed with `docker compose down`
- Fix: Use named volumes for persistent data:
  ```yaml
  volumes:
    - pgdata:/var/lib/postgresql/data
  volumes:
    pgdata:
  ```

**Named volume masking bind mount**
- A named volume from a previous run takes precedence over a bind mount on the same path
- Fix: Remove the old volume (`docker volume rm <name>`) or use a different mount path

**Path not found on host**
- Bind mount uses a relative path that resolves incorrectly
- Docker Desktop file sharing not enabled for the host directory
- Fix: Use absolute paths, ensure the directory exists on the host, check Docker Desktop file sharing settings

---

## Build Failures

### Symptoms

- `docker build` fails at a specific step
- Cache is not being used (rebuilding everything every time)
- Build succeeds locally but fails in CI

### Diagnostic Commands

```bash
# Build with verbose output
DOCKER_BUILDKIT=1 docker build --progress=plain -t myapp .

# Build without cache (to rule out stale cache)
docker build --no-cache -t myapp .

# Check build context size
du -sh . --exclude=node_modules --exclude=.git

# Check what .dockerignore excludes
# (no built-in command, but you can check manually)
cat .dockerignore
```

### Common Causes and Fixes

**COPY file not found**
- File is excluded by `.dockerignore`
- File is outside the build context (Docker cannot COPY files above the context directory)
- Fix: Check `.dockerignore`, ensure the file is within the build context path

**apt-get fails**
- Missing `apt-get update` before `apt-get install`
- Stale cached `apt-get update` layer from a previous build
- Fix: Always combine `apt-get update && apt-get install` in the same RUN:
  ```dockerfile
  RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates \
      && rm -rf /var/lib/apt/lists/*
  ```

**Cache not working (rebuilding everything)**
- A frequently-changing file is COPY'd early (e.g., `COPY . .` before `RUN npm install`)
- `.dockerignore` is missing, so `.git/` or other changing files invalidate cache
- Fix: Order layers from least to most frequently changing (see Dockerfile best practices)

**BuildKit syntax errors**
- Missing `# syntax=docker/dockerfile:1` directive at top of file
- Using `--mount` features without BuildKit enabled
- Fix: Add syntax directive, ensure `DOCKER_BUILDKIT=1` is set

**Build succeeds locally, fails in CI**
- Local build uses cache, CI starts fresh
- Different platform (local is ARM, CI is AMD64)
- Fix: Test with `--no-cache` locally, ensure platform consistency

---

## No Space Left on Device

### Symptoms

- `docker build` fails with "no space left on device"
- `docker pull` fails with disk space errors
- Container fails to write files

### Diagnostic Commands

```bash
# Check Docker disk usage
docker system df

# Detailed disk usage (per-image, per-container, per-volume)
docker system df -v

# Check host disk
df -h

# Find large images
docker images --format "{{.Repository}}:{{.Tag}} {{.Size}}" | sort -k2 -h

# Find large volumes
docker volume ls -q | xargs -I {} docker volume inspect {} --format '{{.Name}}: {{.Mountpoint}}'
```

### Common Causes and Fixes

**Accumulated build cache**
- BuildKit caches intermediate layers aggressively
- Fix: `docker builder prune` to clear build cache

**Stopped containers and dangling images**
- Stopped containers and their writable layers consume disk
- Dangling images (untagged) accumulate over time
- Fix: `docker system prune -a` removes all unused containers, networks, and images

**Large unused volumes**
- Database volumes from old projects, test runs
- Fix: `docker volume prune` (WARNING: permanently deletes data in unused volumes)

**Image layers not shared**
- Using different base images across projects means no shared layers
- Fix: Standardize on a common base image where possible

**Full cleanup (when you need space urgently)**
```bash
# Remove everything unused (containers, images, networks, volumes)
docker system prune -a --volumes

# Check space recovered
docker system df
```

---

## Slow Builds

### Symptoms

- `docker build` takes minutes when it should take seconds
- Every build seems to rebuild everything from scratch
- Large build context being sent to daemon

### Diagnostic Commands

```bash
# Check build context size (what gets sent to the daemon)
du -sh .

# Build with timing
DOCKER_BUILDKIT=1 docker build --progress=plain -t myapp . 2>&1 | tee build.log

# Check if .dockerignore exists and is effective
cat .dockerignore
```

### Common Causes and Fixes

**Missing .dockerignore**
- Without `.dockerignore`, the entire directory (including `.git/`, `node_modules/`, etc.) is sent as build context
- A 500 MB build context adds 10+ seconds before the build even starts
- Fix: Create `.dockerignore` excluding `.git`, `node_modules`, `__pycache__`, build outputs

**Cache-busting layers**
- `COPY . .` early in the Dockerfile invalidates all subsequent layers on every code change
- Fix: Copy dependency manifests first, install deps, then copy code:
  ```dockerfile
  COPY package.json package-lock.json ./
  RUN npm ci
  COPY . .
  ```

**Not using BuildKit**
- Legacy builder is single-threaded and has less efficient caching
- Fix: `export DOCKER_BUILDKIT=1` or use Docker Desktop (BuildKit is default)

**BuildKit parallel stages not being used**
- Multi-stage builds with independent stages run sequentially without BuildKit
- Fix: Enable BuildKit, structure Dockerfile with independent stages

**No registry cache in CI**
- CI builds start from scratch every time
- Fix: Use BuildKit cache export/import:
  ```bash
  # Push cache to registry
  docker buildx build \
    --cache-to type=registry,ref=myregistry/myapp:cache \
    --cache-from type=registry,ref=myregistry/myapp:cache \
    -t myapp:latest .
  ```
  Or use GitHub Actions cache:
  ```yaml
  - uses: docker/build-push-action@v5
    with:
      cache-from: type=gha
      cache-to: type=gha,mode=max
  ```

**Large base image downloads**
- Using `ubuntu:22.04` (120 MB) when `alpine` (5 MB) would work
- Fix: Switch to smaller base images where possible

**Unnecessary packages installed**
- `apt-get install` without `--no-install-recommends` pulls in extra packages
- Build tools left in the final image
- Fix: Use `--no-install-recommends`, use multi-stage builds to separate build and runtime
