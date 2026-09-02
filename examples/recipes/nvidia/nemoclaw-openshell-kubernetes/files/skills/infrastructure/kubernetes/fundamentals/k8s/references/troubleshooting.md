# Kubernetes Troubleshooting Guide

Detailed debugging workflows for every common error state. Each section follows the pattern: **symptoms → diagnostic commands → common causes → resolution steps**.

---

## Table of Contents

1. [Pod Error States](#pod-error-states)
2. [Node Issues](#node-issues)
3. [Networking Issues](#networking-issues)
4. [Storage Issues](#storage-issues)

---

## Pod Error States

### CrashLoopBackOff

The container repeatedly crashes and Kubernetes restarts it with exponential backoff delays.

**Diagnose:**

```bash
# Check pod status and restart count
kubectl get pod <pod> -n <ns> -o wide

# Check events for scheduling/pull/start failures
kubectl describe pod <pod> -n <ns>

# Check current container logs
kubectl logs <pod> -n <ns> --tail=100

# Check previous (crashed) container logs
kubectl logs <pod> -n <ns> --previous

# For multi-container pods, specify container
kubectl logs <pod> -n <ns> -c <container> --previous
```

**Common causes and fixes:**

| Cause | Indicator | Fix |
|-------|-----------|-----|
| Application error | Non-zero exit code in `describe` output, error in logs | Fix application code/config |
| OOMKilled | Exit code 137, Reason: OOMKilled | Increase memory limits (see OOMKilled section) |
| Missing config/secret | Log shows "file not found" or "env var missing" | Verify ConfigMap/Secret exists and is mounted |
| Failed liveness probe | Events show "Liveness probe failed" | Increase `initialDelaySeconds`, fix health endpoint |
| Port conflict | "bind: address already in use" in logs | Check if another container uses the same port |
| Missing dependencies | Connection refused/timeout to DB, Redis, etc. | Verify dependent services are running |
| Permissions | "permission denied" in logs | Check securityContext, file ownership in image |

### OOMKilled

Container terminated because it exceeded its memory limit or the node is under memory pressure.

**Diagnose:**

```bash
# Confirm OOMKilled
kubectl describe pod <pod> -n <ns> | grep -A5 "Last State"
# Look for: Reason: OOMKilled, Exit Code: 137

# Check current memory limits
kubectl get pod <pod> -n <ns> -o jsonpath='{.spec.containers[*].resources}'

# Check actual memory usage (if pod is running)
kubectl top pod <pod> -n <ns>

# Check node memory pressure
kubectl describe node <node> | grep -A5 "Conditions"
```

**Resolution:**

1. **Increase memory limits** — If the app genuinely needs more memory:
   ```yaml
   resources:
     requests:
       memory: "512Mi"
     limits:
       memory: "1Gi"    # Increase this
   ```

2. **Investigate memory leaks** — If usage grows unbounded:
   - Check application profiling (heap dumps, memory profilers)
   - Look for connection pool exhaustion, cache growth, goroutine leaks
   - Set up VPA in recommendation mode to track actual usage over time

3. **Node-level OOM** — If the node itself is under pressure:
   - Check if requests are set too low (pod scheduled but uses more than requested)
   - Increase node pool size or add larger nodes
   - Set proper requests so the scheduler places pods correctly

### ImagePullBackOff

Kubernetes cannot pull the container image from the registry.

**Diagnose:**

```bash
# Check the exact error
kubectl describe pod <pod> -n <ns> | grep -A10 "Events"
# Look for: "Failed to pull image", "unauthorized", "not found"

# Check the image reference
kubectl get pod <pod> -n <ns> -o jsonpath='{.spec.containers[*].image}'

# Check imagePullSecrets
kubectl get pod <pod> -n <ns> -o jsonpath='{.spec.imagePullSecrets}'
kubectl get secret <secret-name> -n <ns>
```

**Common causes and fixes:**

| Cause | Fix |
|-------|-----|
| Wrong image name or tag | Correct the image reference, verify tag exists in registry |
| Missing imagePullSecrets | Create secret: `kubectl create secret docker-registry <name> --docker-server=<registry> --docker-username=<user> --docker-password=<pass> -n <ns>` |
| Expired credentials | Refresh the registry credentials in the Secret |
| Private registry without auth | Add imagePullSecrets to pod spec or ServiceAccount |
| Network access | Verify node can reach registry (firewall, proxy, DNS) |
| Rate limiting (Docker Hub) | Use authenticated pulls or mirror images to private registry |

### Pending

Pod accepted by the API server but not yet scheduled to a node.

**Diagnose:**

```bash
# Check why scheduling failed
kubectl describe pod <pod> -n <ns> | grep -A20 "Events"

# Check node resources
kubectl describe nodes | grep -A5 "Allocated resources"

# Check if PVC is bound
kubectl get pvc -n <ns>

# Check node taints
kubectl get nodes -o custom-columns='NAME:.metadata.name,TAINTS:.spec.taints[*].key'

# Check resource quotas
kubectl get resourcequota -n <ns>
```

**Common causes and fixes:**

| Cause | Indicator | Fix |
|-------|-----------|-----|
| Insufficient CPU/memory | "Insufficient cpu" or "Insufficient memory" in events | Add nodes, reduce requests, or lower other workloads |
| NodeSelector mismatch | "didn't match Pod's node affinity/selector" | Add labels to nodes or update selector |
| Taint not tolerated | "had taint {key}, that the pod didn't tolerate" | Add toleration to pod spec or remove taint |
| PVC not bound | "persistentvolumeclaim not found" or PVC in Pending state | Check StorageClass, provision PV, fix PVC spec |
| ResourceQuota exceeded | "exceeded quota" in events | Increase quota or reduce resource requests |
| Too many pods | "Too many pods" | Increase maxPods on node or add nodes |

### Init:Error / Init:CrashLoopBackOff

An init container is failing, preventing the main containers from starting.

**Diagnose:**

```bash
# List init container statuses
kubectl get pod <pod> -n <ns> -o jsonpath='{.status.initContainerStatuses[*].name}'

# Check logs for the failing init container
kubectl logs <pod> -n <ns> -c <init-container-name>

# Describe for events
kubectl describe pod <pod> -n <ns>
```

**Common causes:**
- Database migration script failed
- Dependency service not yet available (race condition at startup)
- Config file generation failed
- Permission issues with shared volumes

**Fix:** Address the root cause in the init container. If it is a timing issue, add retry logic or use a readiness gate.

### Evicted

Pod was evicted from the node due to resource pressure.

**Diagnose:**

```bash
# Check eviction reason
kubectl describe pod <pod> -n <ns> | grep -i "status\|reason\|message"

# Check node conditions
kubectl describe node <node> | grep -A10 "Conditions"

# Check for DiskPressure, MemoryPressure, PIDPressure
```

**Resolution:**
- **DiskPressure** — Clean up unused images: kubelet GC, or manually prune. Increase node disk size.
- **MemoryPressure** — Set proper resource requests so pods are scheduled to nodes with capacity. Consider PriorityClass for critical workloads.
- **Eviction order** — Pods without requests (BestEffort QoS) are evicted first, then Burstable, then Guaranteed. Set requests=limits for critical pods.

---

## Node Issues

### NotReady

A node has stopped communicating with the control plane or failed health checks.

**Diagnose:**

```bash
# Check node conditions
kubectl describe node <node> | grep -A15 "Conditions"

# Check node events
kubectl get events --field-selector involvedObject.name=<node> --sort-by=.lastTimestamp

# If you have SSH access
ssh <node> "systemctl status kubelet"
ssh <node> "journalctl -u kubelet --since '10 minutes ago'"
```

**Common causes:**
- kubelet crashed or stopped
- Node ran out of disk, memory, or PIDs
- Network partition (node cannot reach API server)
- Container runtime (containerd/docker) crashed
- Kernel panic or hardware failure
- Certificate expiration

**Resolution:**
1. Check kubelet status and restart if needed
2. Check container runtime status
3. Check disk space (`df -h`) and memory (`free -m`)
4. Check network connectivity to API server
5. If unrecoverable, cordon → drain → replace the node

### DiskPressure

Node disk usage exceeds the eviction threshold (typically 85%).

**Diagnose:**

```bash
kubectl describe node <node> | grep -i diskpressure
# If SSH access:
ssh <node> "df -h"
ssh <node> "crictl images | wc -l"
```

**Resolution:**
- Clean up unused container images: `crictl rmi --prune`
- Clean up completed pods/jobs
- Increase node disk size
- Set imagefs eviction thresholds appropriately in kubelet config

### MemoryPressure

Node memory usage exceeds the eviction threshold.

**Diagnose:**

```bash
kubectl describe node <node> | grep -i memorypressure
kubectl top node <node>
kubectl top pods --all-namespaces --sort-by=memory | head -20
```

**Resolution:**
- Identify pods consuming excessive memory
- Set proper resource requests and limits
- Add nodes to the cluster
- Consider vertical scaling (larger nodes)

---

## Networking Issues

### DNS Resolution Failures

Pods cannot resolve service names or external hostnames.

**Diagnose:**

```bash
# Test DNS from within a pod
kubectl exec -it <pod> -n <ns> -- nslookup kubernetes.default
kubectl exec -it <pod> -n <ns> -- nslookup <service-name>.<namespace>.svc.cluster.local

# If pod lacks tools, create a debug pod
kubectl run dns-test --image=busybox:1.36 --restart=Never -- sleep 3600
kubectl exec -it dns-test -- nslookup <service-name>

# Check CoreDNS pods
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
```

**Common causes:**
- CoreDNS pods crashed or overloaded
- NetworkPolicy blocking DNS (UDP port 53) egress
- `/etc/resolv.conf` misconfigured in pod
- Service name typo (FQDN: `<svc>.<ns>.svc.cluster.local`)

### Service Not Reachable

A Service exists but traffic does not reach the pods.

**Diagnose:**

```bash
# Check service endpoints (should list pod IPs)
kubectl get endpoints <service> -n <ns>

# If endpoints are empty, check selector match
kubectl get svc <service> -n <ns> -o jsonpath='{.spec.selector}'
kubectl get pods -n <ns> --show-labels | grep <selector-value>

# Check if pods are Ready
kubectl get pods -n <ns> -l <selector> -o wide

# Test from within cluster
kubectl run curl-test --image=curlimages/curl --restart=Never -- curl -s http://<service>.<ns>:port
```

**Common causes:**
- Selector mismatch between Service and Pod labels
- Pods not Ready (failing readiness probe) — not added to endpoints
- Wrong port in Service spec (targetPort must match container port)
- NetworkPolicy blocking ingress traffic

### Ingress Not Working

External traffic not reaching the service via Ingress.

**Diagnose:**

```bash
# Check Ingress resource
kubectl describe ingress <name> -n <ns>

# Check Ingress controller logs
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=50

# Verify backend service and endpoints
kubectl get svc <backend-service> -n <ns>
kubectl get endpoints <backend-service> -n <ns>

# Check TLS certificate
kubectl get secret <tls-secret> -n <ns>
```

**Common causes:**
- Ingress controller not installed or not running
- Incorrect `ingressClassName` or annotations
- TLS secret missing or malformed
- Backend service selector mismatch
- Path matching issues (prefix vs exact vs regex)

---

## Storage Issues

### PVC Pending

PersistentVolumeClaim remains in Pending state and is not bound to a PV.

**Diagnose:**

```bash
# Check PVC status and events
kubectl describe pvc <name> -n <ns>

# Check available PVs
kubectl get pv

# Check StorageClass
kubectl get storageclass
kubectl describe storageclass <name>
```

**Common causes:**
- No StorageClass set and no default StorageClass exists
- StorageClass provisioner not installed or failing
- Requested storage size exceeds available capacity
- Access mode mismatch (ReadWriteOnce vs ReadWriteMany)
- For static provisioning: no matching PV available

**Resolution:**
1. Verify StorageClass exists and is default (or set `storageClassName` in PVC)
2. Check that the CSI driver / provisioner is running
3. For cloud providers, check IAM permissions for volume provisioning
4. Reduce requested size or provision larger volumes

### Volume Mount Errors

Pod fails to start because a volume cannot be mounted.

**Diagnose:**

```bash
kubectl describe pod <pod> -n <ns> | grep -A10 "Events"
# Look for: "FailedMount", "MountVolume.SetUp failed"
```

**Common causes:**
- Volume already attached to another node (for single-attach volumes like EBS)
- Stale volume attachment after node failure — delete the VolumeAttachment object
- Permission denied — check `fsGroup` in securityContext
- ConfigMap or Secret referenced but does not exist
- Subpath does not exist in the volume
