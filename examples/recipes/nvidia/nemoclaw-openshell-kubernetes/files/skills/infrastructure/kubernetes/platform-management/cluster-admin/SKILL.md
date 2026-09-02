---
name: kubernetes-platform-cluster-admin
description: Master Kubernetes cluster administration, from initial setup through production management. Learn cluster installation, scaling, upgrades, and HA strategies.
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 01-cluster-admin
bond_type: PRIMARY_BOND
capabilities: ["Cluster lifecycle management", "Node administration", "HA configuration", "Cluster upgrades", "etcd management", "Resource quotas", "Namespace management", "Cluster autoscaling"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["create", "upgrade", "scale", "backup", "restore", "diagnose"]
    cluster_type:
      type: string
      enum: ["kind", "minikube", "kubeadm", "eks", "aks", "gke"]
    target:
      type: string
output_schema:
  type: object
  properties:
    status:
      type: string
    commands:
      type: array
    recommendations:
      type: array
---

# Cluster Administration

## Executive Summary
Production-grade Kubernetes cluster administration covering the complete lifecycle from initial deployment to day-2 operations. This skill provides deep expertise in cluster architecture, high availability configurations, upgrade strategies, and operational best practices aligned with CKA/CKS certification standards.

## Core Competencies

### 1. Cluster Architecture Mastery

**Control Plane Components**
```
┌─────────────────────────────────────────────────────────────────┐
│                      CONTROL PLANE                               │
├─────────────┬─────────────┬──────────────┬────────────────────┤
│ API Server  │ Scheduler   │ Controller   │ etcd               │
│             │             │ Manager      │                    │
│ - AuthN     │ - Pod       │ - ReplicaSet │ - Cluster state    │
│ - AuthZ     │   placement │ - Endpoints  │ - 3+ nodes for HA  │
│ - Admission │ - Node      │ - Namespace  │ - Regular backups  │
│   control   │   affinity  │ - ServiceAcc │ - Encryption       │
└─────────────┴─────────────┴──────────────┴────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      WORKER NODES                                │
├─────────────────┬─────────────────┬─────────────────────────────┤
│ kubelet         │ kube-proxy      │ Container Runtime           │
│ - Pod lifecycle │ - iptables/ipvs │ - containerd (recommended)  │
│ - Node status   │ - Service VIPs  │ - CRI-O                     │
│ - Volume mount  │ - Load balance  │ - gVisor (sandboxed)        │
└─────────────────┴─────────────────┴─────────────────────────────┘
```

**Production Cluster Bootstrap (kubeadm)**
```bash
# Initialize control plane with HA
sudo kubeadm init \
  --control-plane-endpoint "k8s-api.example.com:6443" \
  --upload-certs \
  --pod-network-cidr=10.244.0.0/16 \
  --service-cidr=10.96.0.0/12 \
  --apiserver-advertise-address=0.0.0.0 \
  --apiserver-cert-extra-sans=k8s-api.example.com

# Join additional control plane nodes
kubeadm join k8s-api.example.com:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <cert-key>

# Join worker nodes
kubeadm join k8s-api.example.com:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

### 2. Node Management

**Node Lifecycle Operations**
```bash
# View node details with resource usage
kubectl get nodes -o wide
kubectl top nodes

# Label nodes for workload placement
kubectl label nodes worker-01 node-type=compute tier=production
kubectl label nodes worker-02 node-type=gpu accelerator=nvidia-a100

# Taint nodes for dedicated workloads
kubectl taint nodes worker-gpu dedicated=gpu:NoSchedule

# Cordon node (prevent new pods)
kubectl cordon worker-03

# Drain node safely (for maintenance)
kubectl drain worker-03 \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=300 \
  --timeout=600s

# Return node to service
kubectl uncordon worker-03
```

**Node Problem Detector Configuration**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-problem-detector
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: node-problem-detector
  template:
    metadata:
      labels:
        app: node-problem-detector
    spec:
      containers:
      - name: node-problem-detector
        image: registry.k8s.io/node-problem-detector/node-problem-detector:v0.8.14
        securityContext:
          # node-problem-detector reads host kernel logs (/dev/kmsg), which
          # requires privileged mode. Do not copy this block into workloads
          # that do not need host-level access; prefer the least-privilege
          # securityContext shown in the k8s-security skill.
          privileged: true
        env:
        - name: NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        volumeMounts:
        - name: log
          mountPath: /var/log
          readOnly: true
        - name: kmsg
          mountPath: /dev/kmsg
          readOnly: true
      volumes:
      - name: log
        hostPath:
          path: /var/log
      - name: kmsg
        hostPath:
          path: /dev/kmsg
      tolerations:
      - operator: Exists
        effect: NoSchedule
```

### 3. High Availability Configuration

**HA Architecture Pattern**
```
                    ┌─────────────────┐
                    │  Load Balancer  │
                    │ (HAProxy/NLB)   │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ Control Plane │    │ Control Plane │    │ Control Plane │
│     Node 1    │    │     Node 2    │    │     Node 3    │
├───────────────┤    ├───────────────┤    ├───────────────┤
│ API Server    │    │ API Server    │    │ API Server    │
│ Scheduler     │    │ Scheduler     │    │ Scheduler     │
│ Controller    │    │ Controller    │    │ Controller    │
│ etcd          │◄──►│ etcd          │◄──►│ etcd          │
└───────────────┘    └───────────────┘    └───────────────┘
        │                    │                    │
        └────────────────────┴────────────────────┘
                             │
                    ┌────────┴────────┐
                    │  Worker Nodes   │
                    │  (N instances)  │
                    └─────────────────┘
```

**etcd Backup & Restore**
```bash
# Backup etcd
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot-$(date +%Y%m%d).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Verify backup
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-snapshot-*.db --write-out=table

# Restore etcd (disaster recovery)
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot-*.db \
  --data-dir=/var/lib/etcd-restored \
  --name=etcd-0 \
  --initial-cluster=etcd-0=https://10.0.0.10:2380 \
  --initial-advertise-peer-urls=https://10.0.0.10:2380

# Automated backup CronJob
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-backup
  namespace: kube-system
spec:
  schedule: "0 */6 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: bitnami/etcd:3.5
            command:
            - /bin/sh
            - -c
            - |
              etcdctl snapshot save /backup/etcd-\$(date +%Y%m%d-%H%M).db
            env:
            - name: ETCDCTL_API
              value: "3"
            volumeMounts:
            - name: backup
              mountPath: /backup
            - name: etcd-certs
              mountPath: /etc/kubernetes/pki/etcd
              readOnly: true
          volumes:
          - name: backup
            persistentVolumeClaim:
              claimName: etcd-backup-pvc
          - name: etcd-certs
            hostPath:
              path: /etc/kubernetes/pki/etcd
          restartPolicy: OnFailure
          nodeSelector:
            node-role.kubernetes.io/control-plane: ""
          tolerations:
          - key: node-role.kubernetes.io/control-plane
            effect: NoSchedule
EOF
```

### 4. Cluster Upgrades

**Upgrade Strategy Decision Tree**
```
Upgrade Required?
│
├── Minor Version (1.29 → 1.30)
│   ├── Review release notes for breaking changes
│   ├── Test in staging environment
│   ├── Upgrade control plane first
│   │   └── One node at a time
│   └── Upgrade workers (rolling)
│
├── Patch Version (1.30.0 → 1.30.1)
│   ├── Generally safe, security fixes
│   └── Can upgrade more aggressively
│
└── Major changes in components
    ├── Test thoroughly
    ├── Have rollback plan
    └── Consider blue-green cluster
```

**Production Upgrade Process**
```bash
# Step 1: Upgrade kubeadm on control plane
sudo apt-mark unhold kubeadm
sudo apt-get update && sudo apt-get install -y kubeadm=1.30.0-00
sudo apt-mark hold kubeadm

# Step 2: Plan the upgrade
sudo kubeadm upgrade plan

# Step 3: Apply upgrade on first control plane
sudo kubeadm upgrade apply v1.30.0

# Step 4: Upgrade kubelet and kubectl
kubectl drain control-plane-1 --ignore-daemonsets
sudo apt-mark unhold kubelet kubectl
sudo apt-get install -y kubelet=1.30.0-00 kubectl=1.30.0-00
sudo apt-mark hold kubelet kubectl
sudo systemctl daemon-reload
sudo systemctl restart kubelet
kubectl uncordon control-plane-1

# Step 5: Upgrade additional control planes
sudo kubeadm upgrade node
# Then upgrade kubelet/kubectl as above

# Step 6: Upgrade worker nodes (rolling)
for node in $(kubectl get nodes -l node-role.kubernetes.io/worker -o name); do
  kubectl drain $node --ignore-daemonsets --delete-emptydir-data
  # SSH to node and upgrade packages
  kubectl uncordon $node
  sleep 60  # Allow pods to stabilize
done
```

### 5. Resource Management

**Namespace Resource Quotas**
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-quota
  namespace: team-backend
spec:
  hard:
    requests.cpu: "20"
    requests.memory: 40Gi
    limits.cpu: "40"
    limits.memory: 80Gi
    persistentvolumeclaims: "10"
    requests.storage: 500Gi
    pods: "50"
    services: "20"
    secrets: "50"
    configmaps: "50"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: team-backend
spec:
  limits:
  - type: Container
    default:
      cpu: 500m
      memory: 512Mi
    defaultRequest:
      cpu: 100m
      memory: 128Mi
    min:
      cpu: 50m
      memory: 64Mi
    max:
      cpu: 4
      memory: 8Gi
  - type: PersistentVolumeClaim
    min:
      storage: 1Gi
    max:
      storage: 100Gi
```

**Cluster Autoscaler Configuration**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cluster-autoscaler
  template:
    metadata:
      labels:
        app: cluster-autoscaler
    spec:
      serviceAccountName: cluster-autoscaler
      containers:
      - name: cluster-autoscaler
        image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.30.0
        command:
        - ./cluster-autoscaler
        - --v=4
        - --stderrthreshold=info
        - --cloud-provider=aws
        - --skip-nodes-with-local-storage=false
        - --expander=least-waste
        - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/my-cluster
        - --balance-similar-node-groups
        - --scale-down-enabled=true
        - --scale-down-delay-after-add=10m
        - --scale-down-unneeded-time=10m
        - --scale-down-utilization-threshold=0.5
        resources:
          limits:
            cpu: 100m
            memory: 600Mi
          requests:
            cpu: 100m
            memory: 600Mi
```

## Integration Patterns

### Uses skill: **docker-containers**
- Container runtime configuration
- Image management on nodes
- Registry authentication

### Coordinates with skill: **security**
- RBAC for cluster admins
- Node security hardening
- Audit logging configuration

### Works with skill: **monitoring**
- Cluster health dashboards
- Control plane metrics
- Node resource alerting

## Troubleshooting Guide

### Decision Tree: Cluster Health Issues

```
Cluster Health Problem?
│
├── API Server unreachable
│   ├── Check: systemctl status kube-apiserver
│   ├── Check: /var/log/kube-apiserver.log
│   ├── Verify: etcd connectivity
│   └── Verify: certificates not expired
│
├── Node NotReady
│   ├── Check: kubelet status on node
│   ├── Check: container runtime status
│   ├── Verify: node network connectivity
│   └── Check: disk pressure, memory pressure
│
├── Pods Pending (no scheduling)
│   ├── Check: kubectl describe pod
│   ├── Verify: node resources available
│   ├── Check: taints and tolerations
│   └── Verify: PVC bound (if using volumes)
│
└── etcd Issues
    ├── Check: etcdctl endpoint health
    ├── Check: etcd member list
    ├── Verify: disk I/O performance
    └── Check: cluster quorum
```

### Debug Commands Cheatsheet

```bash
# Cluster-wide diagnostics
kubectl cluster-info dump --output-directory=/tmp/cluster-dump
kubectl get componentstatuses
kubectl get nodes -o wide
kubectl get events --sort-by='.lastTimestamp' -A

# Control plane health
kubectl get pods -n kube-system
kubectl logs -n kube-system kube-apiserver-<node>
kubectl logs -n kube-system kube-scheduler-<node>
kubectl logs -n kube-system kube-controller-manager-<node>

# etcd health
ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Node diagnostics
kubectl describe node <node-name>
kubectl get node <node-name> -o yaml | grep -A 10 conditions
ssh <node> "journalctl -u kubelet --since '1 hour ago'"

# Certificate expiration check
kubeadm certs check-expiration

# Resource usage
kubectl top nodes
kubectl top pods -A --sort-by=memory
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| etcd performance degradation | Use SSD storage, tune compaction |
| Certificate expiration | Set up cert-manager, kubeadm renew |
| Node resource exhaustion | Configure eviction thresholds, resource quotas |
| Control plane overload | Add more control plane nodes, tune rate limits |
| Upgrade failures | Always backup etcd, use staged rollouts |
| kubelet not starting | Check containerd socket, certificates |
| API server latency | Enable priority/fairness, scale API servers |
| Cluster state drift | GitOps, regular audits, policy enforcement |

## Success Criteria

| Metric | Target |
|--------|--------|
| Cluster uptime | 99.9% |
| API server latency p99 | <200ms |
| etcd backup success | 100% |
| Node ready status | 100% |
| Upgrade success rate | 100% |
| Certificate validity | >30 days |
| Control plane pods healthy | 100% |

## Resources
- [Official Kubernetes Documentation](https://kubernetes.io/docs/)
- [Kubernetes Cluster Administration](https://kubernetes.io/docs/tasks/administer-cluster/)
- [kubeadm Reference](https://kubernetes.io/docs/reference/setup-tools/kubeadm/)
- [etcd Operations Guide](https://etcd.io/docs/v3.5/op-guide/)
