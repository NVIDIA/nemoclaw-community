<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# Kubernetes Error Message Decoder

Quick reference for common Kubernetes error messages and their solutions.

## Pod Status Errors

### CrashLoopBackOff

**Meaning**: Container keeps crashing and Kubernetes is backing off restart attempts.

**Investigation**:

```bash
kubectl logs <pod> -n <namespace> --previous
kubectl describe pod <pod> -n <namespace> | grep -A 5 "Last State"
```

**Common Causes**:

- Application startup failure
- Missing configuration/secrets
- Dependency not available
- Memory limit too low (check for OOMKilled)

---

### ImagePullBackOff / ErrImagePull

**Meaning**: Cannot pull the container image.

**Investigation**:

```bash
kubectl describe pod <pod> -n <namespace> | grep -A 3 "Warning"
```

**Common Causes**:

- Image name/tag typo
- Private registry without credentials
- Registry rate limiting
- Network connectivity to registry

---

### Pending

**Meaning**: Pod cannot be scheduled to any node.

**Investigation**:

```bash
kubectl describe pod <pod> -n <namespace> | grep -A 10 "Events"
```

**Common Causes**:

- Insufficient cluster resources
- Node selector/affinity not satisfied
- Taints without tolerations
- PVC not bound

---

### OOMKilled

**Meaning**: Container exceeded memory limit and was killed.

**Investigation**:

```bash
kubectl describe pod <pod> -n <namespace> | grep -i oom
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
```

**Fix**: Increase memory limit or fix memory leak in application.

---

### CreateContainerConfigError

**Meaning**: Container configuration is invalid.

**Investigation**:

```bash
kubectl describe pod <pod> -n <namespace> | grep -A 5 "Warning"
```

**Common Causes**:

- Secret or ConfigMap doesn't exist
- Key not found in Secret/ConfigMap
- Invalid mount path

---

### RunContainerError

**Meaning**: Container failed to start.

**Investigation**:

```bash
kubectl describe pod <pod> -n <namespace>
```

**Common Causes**:

- Invalid command or args
- Missing executable in image
- Security context issues

---

## Container Exit Codes

| Code | Signal  | Meaning            | Common Cause                                  |
| ---- | ------- | ------------------ | --------------------------------------------- |
| 0    | -       | Success            | Normal exit (check if should be long-running) |
| 1    | -       | Application error  | Check application logs                        |
| 2    | -       | Misuse             | Invalid arguments or command                  |
| 126  | -       | Cannot execute     | Permission denied                             |
| 127  | -       | Command not found  | Missing binary in image                       |
| 128  | -       | Invalid exit       | Exit called with invalid code                 |
| 130  | SIGINT  | Interrupt          | Ctrl+C or sent SIGINT                         |
| 137  | SIGKILL | Killed             | OOMKilled or `kill -9`                        |
| 139  | SIGSEGV | Segmentation fault | Memory access violation                       |
| 143  | SIGTERM | Terminated         | Graceful shutdown requested                   |

---

## Event Warnings

### FailedScheduling

```
Warning  FailedScheduling  default-scheduler  0/3 nodes are available:
3 Insufficient cpu.
```

**Fix**: Add nodes, reduce resource requests, or delete unused pods.

---

### FailedMount

```
Warning  FailedMount  Unable to attach or mount volumes:
timed out waiting for the condition
```

**Common Causes**:

- PVC not bound
- Storage class misconfigured
- Volume already attached to another node
- CSI driver issue

---

### Unhealthy

```
Warning  Unhealthy  Readiness probe failed: Get "http://10.0.0.5:8080/health":
dial tcp 10.0.0.5:8080: connect: connection refused
```

**Fix**: Check application is listening on expected port, adjust probe timing.

---

### BackOff

```
Warning  BackOff  Back-off restarting failed container
```

**Meaning**: Container keeps failing, increasing backoff delay between restarts.

**Fix**: Check logs for crash reason.

---

### Evicted

```
Status: Failed
Reason: Evicted
Message: The node was low on resource: memory.
```

**Cause**: Node ran out of resources and evicted pod.

**Fix**:

- Check node memory pressure
- Set resource limits on pods
- Add more nodes

---

### NodeNotReady

```
Warning  NodeNotReady  Node not ready
```

**Investigation**:

```bash
kubectl describe node <node-name>
kubectl get events --field-selector involvedObject.name=<node-name>
```

---

## Service/Networking Errors

### No Endpoints Available

```
Error: no endpoints available for service
```

**Cause**: Service selector doesn't match any pod labels.

**Fix**:

```bash
# Check service selector
kubectl get svc <service> -o yaml | grep selector -A 5

# Check pod labels
kubectl get pods --show-labels

# Verify endpoints
kubectl get endpoints <service>
```

---

### Connection Refused

**Cause**: Target pod not listening on port.

**Investigation**:

```bash
# Check pod is running
kubectl get pods

# Check container is listening
kubectl exec <pod> -- netstat -tlnp
```

---

### DNS Resolution Failed

```
nslookup: can't resolve 'service-name'
```

**Investigation**:

```bash
# Check CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Check CoreDNS logs
kubectl logs -n kube-system -l k8s-app=kube-dns
```

---

## RBAC Errors

### Forbidden

```
Error from server (Forbidden): pods is forbidden:
User "system:serviceaccount:default:default" cannot list resource "pods"
```

**Fix**: Create appropriate Role/RoleBinding or ClusterRole/ClusterRoleBinding.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
rules:
  - apiGroups: ['']
    resources: ['pods']
    verbs: ['get', 'list', 'watch']
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
subjects:
  - kind: ServiceAccount
    name: default
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```
