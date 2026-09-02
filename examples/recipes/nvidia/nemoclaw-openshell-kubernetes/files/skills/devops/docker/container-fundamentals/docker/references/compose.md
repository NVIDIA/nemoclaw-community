# Docker Compose Reference

Complete guide to Docker Compose patterns: service definitions, networking, volumes, environment management, development workflows, profiles, and production-ready examples.

---

## Service Definitions

### Basic Structure

```yaml
# docker-compose.yml
services:
  app:
    image: myapp:1.2.3                    # Use pre-built image
    # OR
    build:
      context: .                           # Build context path
      dockerfile: Dockerfile               # Dockerfile path (default: Dockerfile)
      args:
        NODE_ENV: production               # Build arguments
      target: runtime                      # Multi-stage target
    container_name: myapp                  # Explicit container name (optional)
    ports:
      - "3000:3000"                        # host:container
      - "127.0.0.1:9229:9229"             # Bind to localhost only (debug port)
    environment:
      NODE_ENV: production
      LOG_LEVEL: info
    env_file:
      - .env                               # Load from file
    volumes:
      - ./src:/app/src                     # Bind mount
      - node_modules:/app/node_modules     # Named volume
    networks:
      - backend
    restart: unless-stopped                # Restart policy
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M
        reservations:
          cpus: "0.25"
          memory: 128M
```

### Restart Policies

| Policy | Behavior |
|--------|----------|
| `no` | Never restart (default) |
| `always` | Always restart, including on daemon startup |
| `on-failure` | Restart only on non-zero exit code |
| `unless-stopped` | Restart unless manually stopped (recommended for production) |

---

## depends_on with Healthcheck

Use `condition: service_healthy` so dependent services wait for real readiness, not just container start:

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myapp -d myapp"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    volumes:
      - redisdata:/data

  app:
    build: .
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "3000:3000"
```

### Common Healthcheck Commands

| Service | Healthcheck |
|---------|-------------|
| PostgreSQL | `pg_isready -U <user> -d <db>` |
| MySQL | `mysqladmin ping -h localhost` |
| Redis | `redis-cli ping` |
| MongoDB | `mongosh --eval "db.adminCommand('ping')"` |
| Elasticsearch | `curl -f http://localhost:9200/_cluster/health` |
| RabbitMQ | `rabbitmq-diagnostics -q ping` |
| HTTP app | `curl -f http://localhost:<port>/health` |
| TCP check | `nc -z localhost <port>` |

---

## Networking

### Default Behavior

All services in a Compose file share a default network. Services reach each other by service name:

```yaml
services:
  app:
    # Can reach db at "db:5432" and redis at "redis:6379"
    environment:
      DATABASE_URL: postgres://myapp:secret@db:5432/myapp
      REDIS_URL: redis://redis:6379
  db:
    image: postgres:16-alpine
  redis:
    image: redis:7-alpine
```

### Custom Networks

Isolate services into separate networks:

```yaml
services:
  frontend:
    networks:
      - frontend-net

  api:
    networks:
      - frontend-net          # Reachable from frontend
      - backend-net           # Can reach database

  db:
    networks:
      - backend-net           # Only reachable from api

networks:
  frontend-net:
  backend-net:
```

### Port Mapping

```yaml
ports:
  - "3000:3000"               # Map host 3000 to container 3000
  - "127.0.0.1:3000:3000"     # Bind to localhost only (not externally accessible)
  - "8080:80"                  # Map host 8080 to container 80
  - "3000"                     # Map random host port to container 3000
```

**`expose` vs `ports`:**
- `expose` — Makes port accessible to other containers on the same network (not to host)
- `ports` — Maps port to host (externally accessible)

### Host Networking

```yaml
services:
  app:
    network_mode: host         # Use host network directly (Linux only)
```

### Accessing Host from Container

```yaml
services:
  app:
    extra_hosts:
      - "host.docker.internal:host-gateway"    # Works on Linux
    # On Docker Desktop, host.docker.internal is available by default
```

---

## Volumes

### Named Volumes (Persistent Data)

```yaml
services:
  db:
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:                        # Docker manages storage location
    driver: local
```

Named volumes persist across `docker compose down`. They are removed with `docker compose down -v`.

### Bind Mounts (Development)

```yaml
services:
  app:
    volumes:
      - ./src:/app/src           # Sync host code into container
      - ./config:/app/config:ro  # Read-only mount
```

Bind mounts mirror the host filesystem into the container. Changes on either side are immediately visible.

### tmpfs (Temporary In-Memory)

```yaml
services:
  app:
    tmpfs:
      - /tmp
      - /app/cache
```

tmpfs mounts are stored in memory and never written to disk. Useful for sensitive temporary data.

### Volume Patterns

```yaml
volumes:
  # Default local driver
  pgdata:

  # External volume (pre-created, not managed by Compose)
  shared-data:
    external: true

  # Named volume with options
  nfs-data:
    driver: local
    driver_opts:
      type: nfs
      o: addr=10.0.0.1,rw
      device: ":/exports/data"
```

### Preventing node_modules Conflicts

A common pattern to prevent host `node_modules` from overriding container dependencies:

```yaml
services:
  app:
    volumes:
      - .:/app                           # Bind mount entire project
      - /app/node_modules                # Anonymous volume masks host node_modules
```

Or better, use a named volume:

```yaml
services:
  app:
    volumes:
      - .:/app
      - node_modules:/app/node_modules   # Named volume for deps

volumes:
  node_modules:
```

---

## Environment Variables

### Inline Definition

```yaml
services:
  app:
    environment:
      NODE_ENV: production
      DATABASE_URL: postgres://user:pass@db:5432/myapp
      DEBUG: "false"
```

### From .env File

Docker Compose automatically reads `.env` in the project directory for variable interpolation:

```
# .env
POSTGRES_VERSION=16
APP_PORT=3000
DB_PASSWORD=supersecret
```

```yaml
services:
  db:
    image: postgres:${POSTGRES_VERSION}-alpine
  app:
    ports:
      - "${APP_PORT}:3000"
```

### env_file Directive

Load environment variables from a file into the container:

```yaml
services:
  app:
    env_file:
      - .env                   # Base environment
      - .env.local             # Local overrides (gitignored)
```

### Variable Interpolation

```yaml
services:
  app:
    image: ${REGISTRY:-docker.io}/${IMAGE_NAME}:${TAG:-latest}
    environment:
      - LOG_LEVEL=${LOG_LEVEL:-info}     # Default to "info"
      - DB_HOST=${DB_HOST:?DB_HOST must be set}  # Error if unset
```

| Syntax | Behavior |
|--------|----------|
| `${VAR}` | Value of VAR, empty if unset |
| `${VAR:-default}` | Value of VAR, or "default" if unset/empty |
| `${VAR-default}` | Value of VAR, or "default" if unset |
| `${VAR:?error}` | Value of VAR, or error if unset/empty |

---

## Development Patterns

### Hot-Reload with Bind Mounts

```yaml
services:
  app:
    build:
      context: .
      target: development              # Use dev stage of multi-stage Dockerfile
    volumes:
      - ./src:/app/src                 # Sync source code
      - ./package.json:/app/package.json
    environment:
      NODE_ENV: development
    command: npm run dev               # Override CMD with dev server
    ports:
      - "3000:3000"                    # App port
      - "127.0.0.1:9229:9229"         # Debugger port (localhost only)
```

### compose.override.yml for Local Dev

Docker Compose automatically merges `docker-compose.yml` with `docker-compose.override.yml`:

```yaml
# docker-compose.yml (base, committed to git)
services:
  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      NODE_ENV: production

  db:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
```

```yaml
# docker-compose.override.yml (local dev, gitignored)
services:
  app:
    volumes:
      - ./src:/app/src
    environment:
      NODE_ENV: development
      DEBUG: "true"
    command: npm run dev
    ports:
      - "127.0.0.1:9229:9229"          # Debugger

  db:
    ports:
      - "127.0.0.1:5432:5432"          # Expose DB locally
    environment:
      POSTGRES_PASSWORD: localdev
```

### Debugging in Container

```yaml
# Node.js debugging
services:
  app:
    command: node --inspect=0.0.0.0:9229 dist/index.js
    ports:
      - "127.0.0.1:9229:9229"

# Python debugging (debugpy)
services:
  app:
    command: python -m debugpy --listen 0.0.0.0:5678 --wait-for-client app.py
    ports:
      - "127.0.0.1:5678:5678"
```

---

## Profiles

Tag services with profiles to make them optional:

```yaml
services:
  app:
    build: .
    ports:
      - "3000:3000"

  db:
    image: postgres:16-alpine

  # Only starts with --profile monitoring
  prometheus:
    image: prom/prometheus:latest
    profiles:
      - monitoring
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    profiles:
      - monitoring
    ports:
      - "3001:3000"

  # Only starts with --profile debug
  adminer:
    image: adminer:latest
    profiles:
      - debug
    ports:
      - "8080:8080"
```

```bash
# Start core services only
docker compose up -d

# Start with monitoring
docker compose --profile monitoring up -d

# Start with everything
docker compose --profile monitoring --profile debug up -d
```

---

## Resource Limits

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: "1.0"           # Max 1 CPU
          memory: 512M          # Max 512 MB RAM
        reservations:
          cpus: "0.25"          # Guaranteed 0.25 CPU
          memory: 128M          # Guaranteed 128 MB RAM
```

For `docker compose up` (not Swarm), resource limits require `--compatibility` flag or Docker Compose v2.

---

## Multi-File Compose

### Environment-Specific Configuration

```bash
# Development (uses default override)
docker compose up -d

# Production
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Testing
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d
```

```yaml
# docker-compose.prod.yml
services:
  app:
    image: registry.example.com/myapp:${TAG}
    restart: always
    environment:
      NODE_ENV: production
    deploy:
      resources:
        limits:
          memory: 1G
      replicas: 2

  db:
    restart: always
    volumes:
      - pgdata:/var/lib/postgresql/data
```

### Merging Behavior

- **Scalars** (image, command): Override replaces
- **Lists** (ports, volumes): Merged (appended)
- **Maps** (environment, labels): Merged (keys override)

---

## Complete Full-Stack Example

Web application with PostgreSQL, Redis, background worker, and Nginx reverse proxy:

```yaml
# docker-compose.yml
services:
  # Nginx reverse proxy
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/certs:/etc/nginx/certs:ro
    depends_on:
      app:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - frontend

  # Application server
  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    environment:
      NODE_ENV: production
      DATABASE_URL: postgres://${DB_USER}:${DB_PASSWORD}@db:5432/${DB_NAME}
      REDIS_URL: redis://redis:6379
      SESSION_SECRET: ${SESSION_SECRET}
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:3000/health"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 15s
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - frontend
      - backend
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M

  # Background worker (same image, different command)
  worker:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    command: ["node", "dist/worker.js"]
    environment:
      NODE_ENV: production
      DATABASE_URL: postgres://${DB_USER}:${DB_PASSWORD}@db:5432/${DB_NAME}
      REDIS_URL: redis://redis:6379
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - backend
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 256M

  # PostgreSQL database
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d:ro
    restart: unless-stopped
    networks:
      - backend

  # Redis cache
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 128mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    volumes:
      - redisdata:/data
    restart: unless-stopped
    networks:
      - backend

volumes:
  pgdata:
  redisdata:

networks:
  frontend:
  backend:
```

```ini
# .env (gitignored)
DB_NAME=myapp
DB_USER=myapp
DB_PASSWORD=changeme-in-production
SESSION_SECRET=changeme-in-production
TAG=latest
```

### Running

```bash
# Start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f app worker

# Scale workers
docker compose up -d --scale worker=3

# Rebuild after code changes
docker compose build app worker
docker compose up -d app worker

# Full teardown (preserving volumes)
docker compose down

# Full teardown (including volumes - DATA LOSS)
docker compose down -v
```
