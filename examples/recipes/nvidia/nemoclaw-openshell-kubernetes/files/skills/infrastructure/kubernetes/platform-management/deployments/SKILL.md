---
name: kubernetes-platform-deployments
description: Master Kubernetes Deployments, StatefulSets, DaemonSets, and workload orchestration. Learn deployment patterns and container orchestration strategies.
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 03-deployment-orchestration
bond_type: PRIMARY_BOND
capabilities: ["Deployment strategies", "Rolling updates", "StatefulSet management", "DaemonSet operations", "Job/CronJob scheduling", "Pod lifecycle", "Resource management", "Autoscaling"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["deploy", "rollout", "scale", "rollback", "status"]
    workload_type:
      type: string
      enum: ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"]
    strategy:
      type: string
      enum: ["RollingUpdate", "Recreate", "Canary", "BlueGreen"]
output_schema:
  type: object
  properties:
    status:
      type: string
    replicas:
      type: object
    rollout_history:
      type: array
---

# Kubernetes Deployments

## Executive Summary
Production-grade workload orchestration covering all Kubernetes workload types with deployment strategies, lifecycle management, and autoscaling patterns. This skill provides deep expertise in managing stateless and stateful applications at enterprise scale with zero-downtime deployments.

## Core Competencies

### 1. Production Deployment Configuration

**Enterprise-Grade Deployment**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  namespace: production
  labels:
    app.kubernetes.io/name: api-server
    app.kubernetes.io/version: "2.1.0"
    app.kubernetes.io/component: backend
    app.kubernetes.io/part-of: ecommerce
spec:
  replicas: 3
  revisionHistoryLimit: 5
  progressDeadlineSeconds: 600
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: api-server
  template:
    metadata:
      labels:
        app.kubernetes.io/name: api-server
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
    spec:
      serviceAccountName: api-server
      securityContext:
        runAsNonRoot: true
        runAsUser: 10000
        fsGroup: 10000
        seccompProfile:
          type: RuntimeDefault

      terminationGracePeriodSeconds: 60

      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchLabels:
                  app.kubernetes.io/name: api-server
              topologyKey: topology.kubernetes.io/zone

      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app.kubernetes.io/name: api-server

      containers:
      - name: api-server
        image: myregistry.io/api-server:2.1.0@sha256:abc123
        imagePullPolicy: IfNotPresent

        ports:
        - name: http
          containerPort: 8080

        env:
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name

        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi

        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]

        readinessProbe:
          httpGet:
            path: /health/ready
            port: http
          initialDelaySeconds: 5
          periodSeconds: 10

        livenessProbe:
          httpGet:
            path: /health/live
            port: http
          initialDelaySeconds: 15
          periodSeconds: 20

        startupProbe:
          httpGet:
            path: /health/startup
            port: http
          failureThreshold: 30
          periodSeconds: 5

        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 10"]

        volumeMounts:
        - name: tmp
          mountPath: /tmp

      volumes:
      - name: tmp
        emptyDir: {}
```

### 2. Deployment Strategies

**Strategy Comparison**
```
┌─────────────────┬───────────────┬───────────────┬─────────────────┐
│ Strategy        │ Downtime      │ Resource Cost │ Rollback Speed  │
├─────────────────┼───────────────┼───────────────┼─────────────────┤
│ Rolling Update  │ Zero          │ 1x + surge    │ Medium          │
│ Recreate        │ Yes           │ 1x            │ N/A             │
│ Blue-Green      │ Zero          │ 2x            │ Instant         │
│ Canary          │ Zero          │ 1.x           │ Fast            │
└─────────────────┴───────────────┴───────────────┴─────────────────┘
```

**Canary with Argo Rollouts**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: api-server
spec:
  replicas: 10
  selector:
    matchLabels:
      app: api-server
  template:
    spec:
      containers:
      - name: api-server
        image: myregistry.io/api-server:2.1.0
  strategy:
    canary:
      steps:
      - setWeight: 5
      - pause: {duration: 5m}
      - setWeight: 20
      - pause: {duration: 10m}
      - setWeight: 50
      - pause: {duration: 10m}
      analysis:
        templates:
        - templateName: success-rate
```

### 3. StatefulSet for Databases

**Production PostgreSQL**
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
  namespace: database
spec:
  serviceName: postgresql
  replicas: 3
  podManagementPolicy: OrderedReady
  updateStrategy:
    type: RollingUpdate
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
        fsGroup: 999

      containers:
      - name: postgresql
        image: postgres:16-alpine
        ports:
        - containerPort: 5432

        env:
        - name: POSTGRES_DB
          value: "appdb"
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata

        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2000m
            memory: 4Gi

        readinessProbe:
          exec:
            command: ["pg_isready", "-U", "postgres"]
          initialDelaySeconds: 5
          periodSeconds: 10

        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data

  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: fast-ssd
      resources:
        requests:
          storage: 100Gi
```

### 4. DaemonSet for Node Services

**Log Collector**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: logging
spec:
  selector:
    matchLabels:
      app: fluent-bit
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
  template:
    metadata:
      labels:
        app: fluent-bit
    spec:
      serviceAccountName: fluent-bit
      tolerations:
      - operator: Exists
      priorityClassName: system-node-critical

      containers:
      - name: fluent-bit
        image: fluent/fluent-bit:2.2
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 256Mi
        volumeMounts:
        - name: varlog
          mountPath: /var/log
          readOnly: true

      volumes:
      - name: varlog
        hostPath:
          path: /var/log
```

### 5. Horizontal Pod Autoscaling

**HPA with Custom Metrics**
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
  minReplicas: 3
  maxReplicas: 50
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: 1000
```

### 6. Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api-server-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: api-server
```

## Integration Patterns

### Uses skill: **cluster-admin**
- Resource quota management
- Node scheduling policies

### Coordinates with skill: **storage-networking**
- PersistentVolume provisioning
- Service discovery

### Works with skill: **monitoring**
- Deployment metrics
- Rollout monitoring

## Troubleshooting Guide

### Decision Tree: Deployment Issues

```
Deployment Problem?
│
├── Pods not starting
│   ├── ImagePullBackOff → Check image/registry
│   ├── CrashLoopBackOff → Check logs, limits
│   ├── Pending → Check resources, affinity
│   └── ContainerCreating → Check volumes
│
├── Rollout stuck
│   ├── Check: progressDeadlineSeconds
│   ├── Verify: PDB not blocking
│   └── Check: probe configuration
│
└── Scaling issues
    ├── Check: HPA status
    ├── Verify: metrics-server
    └── Check: resource requests
```

### Debug Commands

```bash
# Deployment status
kubectl get deployments -o wide
kubectl rollout status deployment/api-server
kubectl rollout history deployment/api-server

# Pod debugging
kubectl describe pod <pod-name>
kubectl logs <pod-name> --previous

# Scale operations
kubectl scale deployment/api-server --replicas=5
kubectl rollout undo deployment/api-server --to-revision=2
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Slow rollouts | Increase maxSurge |
| Pod evictions | Configure PDB |
| ImagePullBackOff | Check registry auth |
| CrashLoopBackOff | Check logs, limits |
| HPA flapping | Increase stabilization |

## Success Criteria

| Metric | Target |
|--------|--------|
| Deployment success | 99.9% |
| Rollout duration | <10 min |
| Pod availability | 99.99% |
| Zero-downtime | 100% |

## Resources
- [Kubernetes Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [Argo Rollouts](https://argoproj.github.io/rollouts/)
