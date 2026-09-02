---
name: kubernetes-platform-troubleshooting
description: Kubernetes debugging, problem diagnosis, and issue resolution
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 01-cluster-admin
bond_type: PRIMARY_BOND
capabilities: ["Pod debugging", "Log analysis", "Network diagnosis", "Cluster health", "Performance tuning", "Resource analysis", "Event investigation", "Root cause analysis"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["diagnose", "debug", "analyze", "fix", "investigate"]
    target:
      type: string
      enum: ["pod", "node", "service", "network", "storage", "cluster"]
    symptoms:
      type: array
output_schema:
  type: object
  properties:
    diagnosis:
      type: string
    root_cause:
      type: string
    resolution:
      type: array
---

# Kubernetes Troubleshooting

## Executive Summary
Production-grade Kubernetes troubleshooting covering systematic diagnosis, debugging techniques, and resolution patterns. This skill provides deep expertise in rapid incident response, root cause analysis, and creating effective runbooks for enterprise environments.

## Core Competencies

### 1. Pod Troubleshooting

**Status Decision Tree**
```
Pod Issue?
│
├── Pending
│   ├── Insufficient resources → Check node capacity, requests
│   ├── No matching node → Check nodeSelector, affinity
│   ├── PVC not bound → Check StorageClass, PV availability
│   └── Image pull issues → Check registry, imagePullSecrets
│
├── CrashLoopBackOff
│   ├── Check: kubectl logs <pod> --previous
│   ├── App error → Fix application code
│   ├── OOMKilled → Increase memory limits
│   └── Probe failure → Adjust probe settings
│
├── ImagePullBackOff
│   ├── Wrong image name → Verify image:tag
│   ├── Private registry → Check imagePullSecrets
│   └── Registry down → Check registry availability
│
└── Running but not ready
    ├── Readiness probe failing → Check probe config
    └── Dependency unavailable → Check upstream services
```

**Debug Commands**
```bash
# Comprehensive pod info
kubectl describe pod <pod-name> -n <namespace>
kubectl get pod <pod-name> -o yaml

# Container logs
kubectl logs <pod-name> -c <container> --tail=100
kubectl logs <pod-name> --previous  # crashed container
kubectl logs -l app=myapp --all-containers

# Live debugging
kubectl debug <pod-name> -it --image=nicolaka/netshoot
kubectl exec -it <pod-name> -- /bin/sh

# Resource usage
kubectl top pod <pod-name>
kubectl describe node | grep -A 5 "Allocated resources"
```

### 2. Network Troubleshooting

**Connectivity Decision Tree**
```
Network Issue?
│
├── DNS not resolving
│   ├── Check CoreDNS pods: kubectl get pods -n kube-system -l k8s-app=kube-dns
│   ├── Test resolution: kubectl run debug --rm -it --image=busybox -- nslookup kubernetes
│   └── Check NetworkPolicy egress for DNS
│
├── Service unreachable
│   ├── Check endpoints: kubectl get endpoints <service>
│   ├── No endpoints → Pod selector mismatch
│   ├── Verify port mapping: targetPort matches container port
│   └── Check NetworkPolicy ingress
│
├── Pod-to-pod fails
│   ├── Same node → CNI issue, check CNI pods
│   ├── Cross-node → Node networking, firewall rules
│   └── Check NetworkPolicies blocking traffic
│
└── External access fails
    ├── Ingress → Check ingress controller logs
    ├── LoadBalancer → Check cloud LB status
    └── NodePort → Check node firewall
```

**Network Debug Commands**
```bash
# DNS testing
kubectl run debug --rm -it --image=nicolaka/netshoot -- \
  nslookup <service>.<namespace>.svc.cluster.local

# Connectivity testing
kubectl run debug --rm -it --image=nicolaka/netshoot -- \
  curl -v http://<service>:<port>/health

# TCP connection test
kubectl run debug --rm -it --image=nicolaka/netshoot -- \
  nc -zv <service> <port>

# Network policy check
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy <name>
```

### 3. Node Troubleshooting

**Node Health Analysis**
```bash
# Node conditions
kubectl describe node <node> | grep -A 20 "Conditions:"

# Node events
kubectl get events --field-selector involvedObject.name=<node>

# System resource usage
kubectl top node <node>

# Pod distribution
kubectl get pods -A --field-selector spec.nodeName=<node>

# Node logs (via ssh)
journalctl -u kubelet --since "1 hour ago"
journalctl -u containerd --since "1 hour ago"
```

**Common Node Issues**
```
Node NotReady?
│
├── Check kubelet: systemctl status kubelet
├── Check container runtime: systemctl status containerd
├── Check certificates: ls -la /var/lib/kubelet/pki/
├── Check disk: df -h /var/lib/kubelet
└── Check network: ping <api-server-ip>
```

### 4. Cluster Component Debugging

**Control Plane Checks**
```bash
# API server
kubectl get pods -n kube-system -l component=kube-apiserver
kubectl logs -n kube-system kube-apiserver-<node>

# Scheduler
kubectl logs -n kube-system kube-scheduler-<node>
kubectl get events --field-selector reason=FailedScheduling

# Controller Manager
kubectl logs -n kube-system kube-controller-manager-<node>

# etcd
kubectl get pods -n kube-system -l component=etcd
ETCDCTL_API=3 etcdctl endpoint health
```

### 5. Performance Debugging

**Resource Analysis**
```bash
# High CPU pods
kubectl top pods -A --sort-by=cpu | head -10

# High memory pods
kubectl top pods -A --sort-by=memory | head -10

# OOMKilled detection
kubectl get pods -A -o json | jq '.items[] | select(.status.containerStatuses[]?.lastState.terminated.reason == "OOMKilled")'

# Throttled pods (requires cAdvisor)
kubectl get --raw /apis/metrics.k8s.io/v1beta1/pods
```

## Integration Patterns

### Uses skill: **cluster-admin**
- Control plane debugging
- Node management

### Coordinates with skill: **monitoring**
- Metrics analysis
- Log aggregation

### Works with skill: **storage-networking**
- Network diagnosis
- Storage issues

## Troubleshooting Toolkit

**Essential Tools**
```bash
# Install debug tools in cluster
kubectl apply -f https://k8s.io/examples/admin/dns/dnsutils.yaml

# Quick debug pod
kubectl run debug --rm -it --image=nicolaka/netshoot -- bash

# stern for multi-pod logs
stern -n <namespace> <pod-prefix>

# k9s for interactive UI
k9s -n <namespace>
```

## Common Challenges & Solutions

| Issue | Diagnosis | Resolution |
|-------|-----------|------------|
| CrashLoopBackOff | Check logs --previous | Fix app, adjust resources |
| ImagePullBackOff | Check image name, secrets | Fix image, add pullSecret |
| Pending pods | kubectl describe | Add resources, fix affinity |
| OOMKilled | Check memory usage | Increase limits |
| DNS failures | Test CoreDNS | Check egress policy |
| Service unreachable | Check endpoints | Fix selector |
| Node NotReady | Check kubelet | Restart kubelet |

## Success Criteria

| Metric | Target |
|--------|--------|
| MTTR | <15 minutes |
| First response | <5 minutes |
| Root cause found | 95% |
| Runbook coverage | Core scenarios |

## Resources
- [Kubernetes Debugging](https://kubernetes.io/docs/tasks/debug/)
- [kubectl debug](https://kubernetes.io/docs/reference/kubectl/cheatsheet/#interacting-with-running-pods)
