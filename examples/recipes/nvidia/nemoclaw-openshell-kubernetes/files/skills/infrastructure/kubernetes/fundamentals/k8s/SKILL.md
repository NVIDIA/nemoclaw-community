---
name: kubernetes-k8s
description: "Kubernetes operations, troubleshooting, and platform engineering. Trigger for: kubectl, pods, deployments, services, ingress, Helm charts, K8s manifests, RBAC, pod security, network policies, CrashLoopBackOff, OOMKilled, ImagePullBackOff, node scheduling, HPA, cluster health, container debugging, rollbacks. Implicit queries: \"which apps are failing\", \"compare namespaces\", \"what is broken\", \"is everything healthy\", \"check cluster status\", \"why is my service down\", \"pod keeps restarting\", \"container out of memory\", \"set resource limits\", \"create namespace with quotas\", \"audit permissions\", \"canary deployment\", \"rolling restart\", \"scale up\", \"scale down\". Tools: kustomize, kubectl, kubelet, kubeconfig, helm, helmfile, prometheus, servicemonitor, grafana, ArgoCD, flux, gitops. Trigger even without the word Kubernetes."
---

# Kubernetes Operations & Platform Engineering

This skill covers day-to-day Kubernetes operations (troubleshooting, debugging, scaling) and platform engineering (manifests, Helm, RBAC, autoscaling, monitoring).

**Scripts:** Always run scripts with `--help` first. Do not read script source unless debugging the script itself.

**References:** Load reference files on demand based on the task at hand. Do not pre-load all references.

**Slash commands:** Users can also invoke these directly:
- `/k8s-skills:k8s-debug [pod] [namespace]` — Diagnose a pod or deployment
- `/k8s-skills:k8s-deploy [action] [name] [namespace]` — Deploy, rollback, or restart
- `/k8s-skills:k8s-health [namespace]` — Cluster or namespace health check

---

## Quick Command Reference

| Category | Command | Purpose |
|----------|---------|---------|
| **Inspect** | `kubectl get pods -n <ns>` | List pods in namespace |
| **Inspect** | `kubectl get pods -A --field-selector status.phase!=Running` | Find non-running pods across cluster |
| **Inspect** | `kubectl get all -n <ns>` | All resources in namespace |
| **Inspect** | `kubectl get nodes -o wide` | Node status with IPs and versions |
| **Inspect** | `kubectl top pods -n <ns>` | Pod CPU/memory usage |
| **Inspect** | `kubectl top nodes` | Node CPU/memory usage |
| **Debug** | `kubectl describe pod <pod> -n <ns>` | Full pod details + events |
| **Debug** | `kubectl logs <pod> -n <ns> --tail=100` | Recent logs |
| **Debug** | `kubectl logs <pod> -n <ns> --previous` | Logs from crashed container |
| **Debug** | `kubectl logs <pod> -n <ns> -c <container>` | Specific container logs |
| **Debug** | `kubectl exec -it <pod> -n <ns> -- /bin/sh` | Shell into container |
| **Debug** | `kubectl debug <pod> -it --image=busybox -n <ns>` | Ephemeral debug container |
| **Debug** | `kubectl port-forward svc/<svc> <local>:<remote> -n <ns>` | Test service connectivity |
| **Debug** | `kubectl get events -n <ns> --sort-by=.lastTimestamp` | Recent events sorted |
| **Deploy** | `kubectl apply -f <file>` | Apply manifest declaratively |
| **Deploy** | `kubectl rollout status deployment/<name> -n <ns>` | Watch rollout progress |
| **Deploy** | `kubectl rollout restart deployment/<name> -n <ns>` | Graceful rolling restart |
| **Deploy** | `kubectl rollout undo deployment/<name> -n <ns>` | Rollback to previous revision |
| **Deploy** | `kubectl rollout history deployment/<name> -n <ns>` | View revision history |
| **Scale** | `kubectl scale deployment/<name> --replicas=<N> -n <ns>` | Manual horizontal scale |
| **Config** | `kubectl config current-context` | Show active context |
| **Config** | `kubectl config use-context <ctx>` | Switch cluster/context |
| **Config** | `kubectl config get-contexts` | List all contexts |

---

## Pod Troubleshooting

Follow the diagnostic path: **get → describe → logs → exec**

```
Pod not healthy?
│
├─ Status: CrashLoopBackOff
│  ├─ Check: kubectl logs <pod> --previous
│  ├─ Check: kubectl describe pod <pod> → Events section
│  ├─ Exit code 137 (OOMKilled)?
│  │  └─ Increase memory limits, check for memory leaks
│  ├─ Exit code 1 (app error)?
│  │  └─ Read logs, fix application startup
│  └─ Probe failure?
│     └─ Adjust initialDelaySeconds, check endpoint health
│
├─ Status: ImagePullBackOff
│  ├─ Check: kubectl describe pod <pod> → image name/tag
│  ├─ Registry auth? → Verify imagePullSecrets
│  ├─ Image exists? → Check registry directly
│  └─ Network? → Can node reach registry?
│
├─ Status: Pending
│  ├─ Check: kubectl describe pod <pod> → Events
│  ├─ Insufficient resources? → kubectl describe nodes, check allocatable
│  ├─ NodeSelector/affinity mismatch? → Verify node labels
│  ├─ Taint not tolerated? → Add tolerations or remove taint
│  └─ PVC not bound? → kubectl get pvc -n <ns>
│
├─ Status: Init:Error / Init:CrashLoopBackOff
│  ├─ Check: kubectl logs <pod> -c <init-container>
│  └─ Common: DB migration failed, config dependency not ready
│
├─ Status: Evicted
│  ├─ Check: kubectl describe node <node> → Conditions
│  ├─ DiskPressure? → Clean up node disk
│  └─ MemoryPressure? → Check resource quotas, set proper requests
│
└─ Status: Terminating (stuck)
   ├─ Check: kubectl describe pod <pod> → finalizers
   ├─ Finalizer stuck? → Patch to remove finalizer
   └─ Last resort: kubectl delete pod <pod> --grace-period=0 --force
```

For detailed debugging workflows with step-by-step resolution for every error state, read [Troubleshooting Guide](./references/troubleshooting.md).

---

## Deployment Workflow

### Standard Apply → Monitor → Verify

```bash
# 1. Validate manifest before applying
kubectl diff -f manifest.yaml

# 2. Apply the change
kubectl apply -f manifest.yaml

# 3. Monitor rollout
kubectl rollout status deployment/<name> -n <ns> --timeout=300s

# 4. Verify pods are healthy
kubectl get pods -n <ns> -l app=<name>
kubectl logs -l app=<name> -n <ns> --tail=20

# 5. Verify service endpoints
kubectl get endpoints <service> -n <ns>
```

### Rollback

```bash
# Check revision history
kubectl rollout history deployment/<name> -n <ns>

# Rollback to previous revision
kubectl rollout undo deployment/<name> -n <ns>

# Rollback to specific revision
kubectl rollout undo deployment/<name> -n <ns> --to-revision=<N>

# Verify rollback completed
kubectl rollout status deployment/<name> -n <ns>
```

### Rolling Update Strategy

When writing Deployment manifests, configure the update strategy:

```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%        # Extra pods during rollout
      maxUnavailable: 25%   # Max pods unavailable during rollout
```

For complete manifest patterns including probes, anti-affinity, and security contexts, read [Manifest Patterns](./references/manifests.md).

---

## Emergency Procedures

### 1. Stop Bleeding — Scale to Zero

```bash
kubectl scale deployment/<name> --replicas=0 -n <ns>
```

### 2. Rollback a Bad Deployment

```bash
kubectl rollout undo deployment/<name> -n <ns>
kubectl rollout status deployment/<name> -n <ns>
```

### 3. Drain a Node for Maintenance

```bash
# Prevent new scheduling
kubectl cordon <node>

# Evict pods (respects PDB)
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data

# After maintenance, re-enable
kubectl uncordon <node>
```

### 4. Force-Delete a Stuck Pod

```bash
# Only as last resort — try graceful delete first
kubectl delete pod <pod> -n <ns> --grace-period=0 --force
```

### 5. Apply Emergency Resource Quota

```bash
# Prevent runaway resource consumption in a namespace
kubectl apply -f - <<EOF
apiVersion: v1
kind: ResourceQuota
metadata:
  name: emergency-quota
  namespace: <ns>
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    pods: "20"
EOF
```

### 6. Kill a Runaway CronJob

```bash
# Suspend the CronJob to prevent new runs
kubectl patch cronjob/<name> -n <ns> -p '{"spec":{"suspend":true}}'

# Delete active jobs
kubectl delete job -l job-name=<cronjob-name> -n <ns>
```

---

## Helm Quick Reference

| Command | Purpose |
|---------|---------|
| `helm install <release> <chart> -n <ns>` | Deploy new release |
| `helm upgrade <release> <chart> -n <ns>` | Update existing release |
| `helm upgrade --install <release> <chart> -n <ns>` | Idempotent install/upgrade |
| `helm rollback <release> <revision> -n <ns>` | Revert to previous version |
| `helm uninstall <release> -n <ns>` | Remove release |
| `helm list -n <ns>` | Show releases |
| `helm history <release> -n <ns>` | Version history |
| `helm status <release> -n <ns>` | Current release status |
| `helm get values <release> -n <ns>` | Current values for release |
| `helm get manifest <release> -n <ns>` | Rendered manifests |
| `helm template <chart> -f values.yaml` | Preview rendered manifests locally |
| `helm repo add <name> <url>` | Add chart repository |
| `helm repo update` | Refresh repository index |
| `helm search repo <keyword>` | Find charts |
| `helm lint <chart>` | Validate chart |

### Values Override Precedence

Lower overrides higher:
1. Chart `values.yaml` (defaults)
2. `-f custom-values.yaml` (file override)
3. `--set key=value` (CLI override)

### Common Flags

- `--atomic` — Auto-rollback on failure (implies `--wait`)
- `--wait` — Wait until all resources are healthy
- `--timeout 5m` — Max wait time
- `--dry-run` — Preview without applying
- `--create-namespace` — Create namespace if missing
- `-f values-prod.yaml` — Environment-specific values

For Helm chart structure, Helmfile, values management, and testing, read [Helm Guide](./references/helm.md).

---

## Diagnostic Scripts

### Pod Diagnostics

Run `bash scripts/diagnose.sh --help` for full usage.

Diagnoses a specific pod or all unhealthy pods in a namespace. Checks status, events, logs, resource usage, and outputs a structured report with suggested fixes.

```bash
# Diagnose a specific pod
bash scripts/diagnose.sh -n <namespace> <pod-name>

# Diagnose all non-running pods in a namespace
bash scripts/diagnose.sh -n <namespace> --all
```

### Cluster Health

Run `bash scripts/cluster-health.sh --help` for full usage.

Produces a cluster health overview: node status, resource utilization, unhealthy pods, pending PVCs, and recent warning events.

```bash
# Health check for current context
bash scripts/cluster-health.sh

# Health check for specific context
bash scripts/cluster-health.sh --context <context-name>
```

### RBAC Audit

Run `bash scripts/rbac-audit.sh --help` for full usage.

Audits RBAC permissions across the cluster: finds cluster-admin bindings, wildcard permissions, default service account usage, secrets access, and unused service accounts.

```bash
# Audit entire cluster
bash scripts/rbac-audit.sh

# Audit specific namespace
bash scripts/rbac-audit.sh --namespace production
```

### Namespace Setup

Run `bash scripts/namespace-setup.sh --help` for full usage.

Generates production-ready namespace setup manifests: namespace with PSS labels, ResourceQuota, LimitRange, NetworkPolicy (default deny), dedicated ServiceAccount, and RBAC.

```bash
# Generate manifests to stdout
bash scripts/namespace-setup.sh my-namespace

# Write to files
bash scripts/namespace-setup.sh my-namespace --output ./manifests/

# Apply directly (with confirmation)
bash scripts/namespace-setup.sh my-namespace --apply
```

---

## Reference Files

Load these references as needed based on the task:

- **[Troubleshooting Guide](./references/troubleshooting.md)** — Complete debugging workflows:
  - CrashLoopBackOff, OOMKilled, ImagePullBackOff detailed resolution
  - Node-level issues (DiskPressure, MemoryPressure, NotReady)
  - Networking failures (DNS, Service, Ingress)
  - Storage issues (PVC pending, mount errors)

- **[Manifest Patterns](./references/manifests.md)** — Production-ready YAML templates:
  - Deployment, StatefulSet, DaemonSet with best practices
  - Service, Ingress, NetworkPolicy
  - ConfigMap, Secret, HPA, PDB
  - Resource requests/limits and QoS classes

- **[Security Reference](./references/security.md)** — Hardening and access control:
  - RBAC Role/ClusterRole/Binding patterns
  - Pod Security Standards (Restricted, Baseline, Privileged)
  - Network policies for namespace isolation
  - Secrets management (sealed-secrets, external-secrets)

- **[Monitoring Guide](./references/monitoring.md)** — Observability setup:
  - Prometheus alerting rules for common failure modes
  - ServiceMonitor / PodMonitor patterns
  - Grafana dashboard guidelines
  - Key metrics (USE method, RED method)

- **[Helm Guide](./references/helm.md)** — Helm operations and chart authoring:
  - Chart directory structure and templating
  - Values file management and overrides
  - Helmfile for multi-chart deployments
  - Chart testing and linting

- **[GitOps Reference](./references/gitops.md)** — ArgoCD and Flux:
  - ArgoCD Application CRD, sync policies, app-of-apps, ApplicationSet
  - Flux GitRepository, Kustomization, HelmRelease, image automation
  - Environment promotion, secrets in GitOps (SOPS, sealed-secrets)
  - ArgoCD vs Flux comparison and rollback patterns

- **[Examples](./examples/)** — Ready-to-use templates:
  - Complete Helm chart for a production web application
  - Helmfile config for multi-environment deployments
  - Environment-specific values (dev, staging, production)

### Quick Task Reference

| Task | Action |
|------|--------|
| Pod crashing or stuck | Use decision tree above. For detailed steps → `troubleshooting.md` |
| Writing new manifests | Read `manifests.md` for templates. Check `security.md` for security context |
| Setting up monitoring | Read `monitoring.md` for alerting rules and ServiceMonitor patterns |
| Helm deployment | Use Helm Quick Reference above. For chart authoring → `helm.md` |
| Security audit or RBAC | Read `security.md` for Role/Binding patterns and Pod Security Standards |
| Cluster health check | Run `scripts/cluster-health.sh` |
| Diagnose specific pod | Run `scripts/diagnose.sh -n <ns> <pod>` |
| Set up a new namespace | Run `scripts/namespace-setup.sh` or read `manifests.md` |
| Audit RBAC permissions | Run `scripts/rbac-audit.sh` |
| Helm chart template | Copy from `examples/helm-chart/` and customize |
| Multi-env Helmfile | Copy from `examples/helmfile/` and customize |
| Set up ArgoCD or Flux | Read `gitops.md` for Application CRDs, sync policies, and repo structure |
| GitOps secrets | Read `gitops.md` → Shared Patterns → Secrets in GitOps |
