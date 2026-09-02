---
name: devops-practices
description: Kubernetes operations, container builds, CI/CD workflows, and local development environment management
version: 1.0.0
tags: [devops, kubernetes, docker, ci-cd, k3s, github-actions]
---

# DevOps Skill

Kubernetes deployment, container management, and CI/CD operations for the SmartEM system.

## When to Use

- Managing local k3s/k8s development cluster
- Building and pushing container images
- Debugging CI/CD workflow failures
- Setting up or modifying deployment configurations
- Managing secrets and config maps

## SmartEM Infrastructure

### Local Development Cluster

**Known issue: k3s kubeconfig permissions**

k3s is installed with tight permissions on the kubeconfig file. After every system reboot, `kubectl` commands will fail with:

```
error: error loading config file "/etc/rancher/k3s/k3s.yaml": permission denied
```

Fix by running (requires sudo):

```bash
sudo chmod 644 /etc/rancher/k3s/k3s.yaml
```

If you encounter this error, advise the user to run the above command. Other permission-related issues may also surface with k3s (e.g. node token permissions, containerd socket access). These are typically resolved with similar `chmod` or group membership adjustments after reboot.

**Cluster management:**

The `dev-k8s.sh` orchestration script lives in **smartem-devtools** (it used to live in smartem-decisions). It needs a sibling checkout of `smartem-decisions` to build the backend image from `Dockerfile.dev`; override `SMARTEM_DECISIONS_PATH` if your layout differs.

```bash
cd repos/DiamondLightSource/smartem-devtools

# Start local k3s cluster with all services (backend, postgres, rabbitmq, mongo, es, keycloak mock, FE)
./scripts/k8s/dev-k8s.sh up

# Stop and cleanup
./scripts/k8s/dev-k8s.sh down

# Check cluster status
kubectl get pods -n smartem-decisions
kubectl get services -n smartem-decisions
```

**Keycloak in the dev stack:**

The in-cluster Keycloak mock (`keycloak-mock/keycloak.yaml`, pulled in via the development kustomization) is the primary local auth provider. It is brought up automatically by `dev-k8s.sh up` and reachable at `http://localhost:30090`.

The `keycloak-mock/docker-compose.yml` in the same directory is a **fallback for FE-only development** — use it when working inside `smartem-frontend` in isolation without the rest of the k3s stack. Do not run both at once or the NodePort/host-port mapping will collide.

### Services (smartem-decisions namespace)

| Service | Port | NodePort | Purpose |
|---------|------|----------|---------|
| smartem-http-api-service | 8000 | 30080 | Backend API |
| rabbitmq-service | 5672/15672 | 30672 | Message queue |
| postgres-service | 5432 | - | Database |

### Deployment Environments

```
k8s/
├── development/    # Local dev cluster
├── staging/        # Pre-production
└── production/     # Live environment
```

## Container Operations

### Build Images

```bash
cd repos/DiamondLightSource/smartem-decisions

# Build local dev backend image (matches what dev-k8s.sh expects)
docker build -f Dockerfile.dev -t smartem-decisions:latest .

# Build production image
docker build -t smartem-backend:dev .

# Build with specific Python version (from Dockerfile)
docker build --build-arg PYTHON_VERSION=3.12 -t smartem-backend:dev .

# Multi-stage build (production)
docker build --target production -t smartem-backend:prod .
```

`dev-k8s.sh up` will build `smartem-decisions:latest` automatically if it is missing, loading it into k3s containerd. Pre-build it manually only if you want to iterate without re-running `up`.

### Push to Registry

```bash
# Login to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

# Tag and push
docker tag smartem-backend:dev ghcr.io/diamondlightsource/smartem-backend:dev
docker push ghcr.io/diamondlightsource/smartem-backend:dev
```

### Debug Container

```bash
# Run interactive shell in container
docker run -it --rm smartem-backend:dev /bin/bash

# Inspect running container
docker exec -it <container_id> /bin/bash

# Check logs
docker logs -f <container_id>
```

## Kubernetes Operations

### Common Commands

```bash
# Get resources
kubectl get pods,svc,deploy -n smartem-decisions

# Describe resource (debugging)
kubectl describe pod <pod-name> -n smartem-decisions

# Logs
kubectl logs -f <pod-name> -n smartem-decisions
kubectl logs -f deployment/smartem-http-api -n smartem-decisions

# Execute in pod
kubectl exec -it <pod-name> -n smartem-decisions -- /bin/bash

# Port forward for local access
kubectl port-forward svc/smartem-http-api-service 8000:8000 -n smartem-decisions
kubectl port-forward svc/rabbitmq-service 15672:15672 -n smartem-decisions
```

### Apply Configurations

```bash
# Apply kustomize overlay
kubectl apply -k k8s/development/

# Restart deployment (pick up new image)
kubectl rollout restart deployment/smartem-http-api -n smartem-decisions

# Watch rollout
kubectl rollout status deployment/smartem-http-api -n smartem-decisions
```

### Secrets Management

```bash
# Create secret from literal
kubectl create secret generic db-credentials \
  --from-literal=POSTGRES_USER=smartem \
  --from-literal=POSTGRES_PASSWORD=secret \
  -n smartem-decisions

# Create secret from file
kubectl create secret generic app-config \
  --from-file=.env \
  -n smartem-decisions

# View secret (base64 decoded)
kubectl get secret db-credentials -n smartem-decisions -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d
```

## CI/CD Workflows

### smartem-decisions Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| ci.yml | Push/PR to main | Tests, lint, type check |
| _container.yml | Tag push (v*) | Build and push Docker image |
| _docs.yml | Tag push | Build and publish docs |
| security-scan.yml | Schedule/manual | gitleaks scanning |
| build_win_smartem_agent.yml | Push to main | Windows .exe build |

### Debugging CI Failures

```bash
# View workflow runs
gh run list --repo DiamondLightSource/smartem-decisions

# View specific run
gh run view <run-id> --repo DiamondLightSource/smartem-decisions

# View logs
gh run view <run-id> --log --repo DiamondLightSource/smartem-decisions

# Re-run failed jobs
gh run rerun <run-id> --failed --repo DiamondLightSource/smartem-decisions
```

### Local CI Simulation

```bash
cd repos/DiamondLightSource/smartem-decisions

# Run what CI runs
pip install -e .[all]
pre-commit run --all-files
pytest
pyright src tests
ruff check && ruff format --check
```

## GitHub Actions Templates

### Basic Python CI

```yaml
name: devops-practices
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .[dev]
      - run: pytest
      - run: pyright src
```

### Container Build

```yaml
name: devops-practices
on:
  push:
    tags: ["v*"]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.ref_name }}
```

## Troubleshooting

### Pod Not Starting

```bash
# Check events
kubectl describe pod <pod-name> -n smartem-decisions

# Common issues:
# - ImagePullBackOff: Check image name, registry auth
# - CrashLoopBackOff: Check logs, entrypoint
# - Pending: Check resources, node capacity
```

### Service Not Accessible

```bash
# Check endpoints
kubectl get endpoints <service-name> -n smartem-decisions

# Check service selector matches pod labels
kubectl get pods --show-labels -n smartem-decisions

# Test from within cluster
kubectl run -it --rm debug --image=curlimages/curl -- curl http://smartem-http-api-service:8000/health
```

### RabbitMQ Connection Issues

```bash
# Check RabbitMQ is running
kubectl get pods -l app=rabbitmq -n smartem-decisions

# Access management UI
kubectl port-forward svc/rabbitmq-service 15672:15672 -n smartem-decisions
# Then open http://localhost:15672 (guest/guest)

# Check queues
kubectl exec -it <rabbitmq-pod> -- rabbitmqctl list_queues
```

## References

- Kubernetes docs: https://kubernetes.io/docs/
- k3s docs: https://docs.k3s.io/
- GitHub Actions: https://docs.github.com/en/actions
- Docker docs: https://docs.docker.com/
