---
name: kubernetes-platform-cost-optimization
description: Kubernetes cost management, resource optimization, and FinOps practices
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 01-cluster-admin
bond_type: PRIMARY_BOND
capabilities: ["Resource right-sizing", "Cost visibility", "Autoscaling", "Spot instances", "FinOps", "Waste elimination", "Budget management", "Chargeback"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["analyze", "optimize", "report", "alert", "recommend"]
    scope:
      type: string
      enum: ["cluster", "namespace", "workload", "node"]
output_schema:
  type: object
  properties:
    current_cost:
      type: number
    savings_potential:
      type: number
    recommendations:
      type: array
---

# Kubernetes Cost Optimization

## Executive Summary
Production-grade Kubernetes cost management covering resource optimization, autoscaling, and FinOps practices. This skill provides deep expertise in achieving 30-50% cost reduction while maintaining performance and reliability.

## Core Competencies

### 1. Resource Right-Sizing

**Vertical Pod Autoscaler**
```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: api-server-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-server
  updatePolicy:
    updateMode: "Auto"  # or "Off" for recommendations only
  resourcePolicy:
    containerPolicies:
    - containerName: api-server
      minAllowed:
        cpu: 100m
        memory: 128Mi
      maxAllowed:
        cpu: 4
        memory: 8Gi
      controlledResources: ["cpu", "memory"]
```

**Resource Recommendations Analysis**
```bash
# Get VPA recommendations
kubectl describe vpa api-server-vpa

# Check current vs recommended
kubectl get vpa api-server-vpa -o jsonpath='{.status.recommendation}'

# Goldilocks for all deployments
kubectl apply -f https://github.com/FairwindsOps/goldilocks/releases/latest/download/goldilocks.yaml
kubectl label namespace production goldilocks.fairwinds.com/enabled=true
```

### 2. Cost Visibility

**Kubecost Installation**
```bash
helm repo add kubecost https://kubecost.github.io/cost-analyzer/
helm install kubecost kubecost/cost-analyzer \
  --namespace kubecost --create-namespace \
  --set kubecostToken="YOUR_TOKEN" \
  --set prometheus.nodeExporter.enabled=false \
  --set prometheus.serviceAccounts.nodeExporter.create=false
```

**Cost Allocation Labels**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  labels:
    # Cost allocation labels
    team: backend
    environment: production
    product: ecommerce
    cost-center: engineering
spec:
  template:
    metadata:
      labels:
        team: backend
        cost-center: engineering
```

### 3. Intelligent Autoscaling

**HPA with Cost Awareness**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-server
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-server
  minReplicas: 2
  maxReplicas: 20
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

**KEDA for Event-Driven Scaling**
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: api-server
spec:
  scaleTargetRef:
    name: api-server
  minReplicaCount: 0  # Scale to zero!
  maxReplicaCount: 50
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus:9090
      metricName: http_requests_total
      query: sum(rate(http_requests_total{app="api-server"}[1m]))
      threshold: "100"
  - type: cron
    metadata:
      timezone: America/New_York
      start: 0 8 * * 1-5
      end: 0 20 * * 1-5
      desiredReplicas: "5"
```

### 4. Spot/Preemptible Nodes

**Mixed Node Pool Strategy**
```yaml
# Spot-tolerant workloads
apiVersion: apps/v1
kind: Deployment
metadata:
  name: batch-processor
spec:
  template:
    spec:
      nodeSelector:
        kubernetes.io/capacity-type: spot
      tolerations:
      - key: kubernetes.io/capacity-type
        value: spot
        effect: NoSchedule
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            preference:
              matchExpressions:
              - key: kubernetes.io/capacity-type
                operator: In
                values:
                - spot
```

**Cluster Autoscaler with Mixed Pools**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
spec:
  template:
    spec:
      containers:
      - name: cluster-autoscaler
        command:
        - ./cluster-autoscaler
        - --expander=priority
        - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled
        - --balance-similar-node-groups=true
        - --skip-nodes-with-local-storage=false
```

### 5. Waste Elimination

**Idle Resource Detection**
```bash
# Find oversized deployments
kubectl get deployments -A -o json | jq '
  .items[] |
  select(.spec.replicas > 0) |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    replicas: .spec.replicas,
    cpu_request: .spec.template.spec.containers[0].resources.requests.cpu,
    memory_request: .spec.template.spec.containers[0].resources.requests.memory
  }
'

# Find unused PVCs
kubectl get pvc -A --no-headers | while read ns name _; do
  used=$(kubectl get pods -n $ns -o json | jq --arg pvc "$name" '.items[] | select(.spec.volumes[]?.persistentVolumeClaim.claimName == $pvc)')
  [ -z "$used" ] && echo "Unused PVC: $ns/$name"
done
```

**Resource Cleanup Policy**
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: cleanup-stale-pods
spec:
  rules:
  - name: delete-completed-jobs
    match:
      resources:
        kinds:
        - Job
    preconditions:
      all:
      - key: "{{ request.object.status.succeeded }}"
        operator: Equals
        value: 1
      - key: "{{ time_since('', '{{ request.object.status.completionTime }}', '') }}"
        operator: GreaterThan
        value: "24h"
    mutate:
      patchStrategicMerge:
        metadata:
          deletionTimestamp: "{{ time_now() }}"
```

## Integration Patterns

### Uses skill: **cluster-admin**
- Node pool management
- Cluster autoscaling

### Coordinates with skill: **monitoring**
- Resource metrics
- Cost dashboards

### Works with skill: **deployments**
- HPA configuration
- Resource requests

## Troubleshooting Guide

### Decision Tree: Cost Issues

```
High Costs?
│
├── Over-provisioned
│   ├── Check VPA recommendations
│   ├── Right-size requests
│   └── Enable HPA
│
├── Idle resources
│   ├── Find unused PVCs
│   ├── Check scale-to-zero
│   └── Clean up stale jobs
│
└── Wrong instance types
    ├── Use spot for batch
    ├── Review node pools
    └── Check reserved coverage
```

### Debug Commands

```bash
# Cost analysis
kubectl top pods -A --sort-by=cpu
kubectl top pods -A --sort-by=memory

# Resource efficiency
kubectl get pods -A -o json | jq '[.items[].spec.containers[].resources] | add'

# Kubecost API
curl http://kubecost:9090/model/allocation?window=7d&aggregate=namespace
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Overprovisioning | VPA, right-sizing |
| Idle resources | Scale-to-zero, cleanup |
| Spot interruptions | PDB, spreading |
| Cost attribution | Labels, Kubecost |

## Success Criteria

| Metric | Target |
|--------|--------|
| Cost reduction | 30-50% |
| Resource utilization | >60% |
| Waste identification | <10% idle |
| Budget compliance | 100% |

## Resources
- [Kubecost Documentation](https://docs.kubecost.com/)
- [VPA](https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler)
- [KEDA](https://keda.sh/)
