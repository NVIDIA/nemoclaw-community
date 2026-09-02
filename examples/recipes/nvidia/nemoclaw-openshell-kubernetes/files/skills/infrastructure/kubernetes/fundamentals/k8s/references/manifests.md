# Kubernetes Manifest Patterns

Production-ready YAML templates with annotations explaining key decisions. Copy and adapt these patterns.

---

## Table of Contents

1. [Deployment](#deployment)
2. [StatefulSet](#statefulset)
3. [DaemonSet](#daemonset)
4. [Service](#service)
5. [Ingress](#ingress)
6. [ConfigMap and Secret](#configmap-and-secret)
7. [HPA](#hpa-horizontal-pod-autoscaler)
8. [PDB](#pdb-poddisruptionbudget)
9. [NetworkPolicy](#networkpolicy)
10. [Resource Management](#resource-management)

---

## Deployment

Standard stateless workload with production best practices.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  namespace: production
  labels:
    app: myapp
    version: v1
spec:
  replicas: 3
  revisionHistoryLimit: 5        # Keep 5 revisions for rollback
  selector:
    matchLabels:
      app: myapp
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%              # Extra pods during rollout
      maxUnavailable: 0          # Zero downtime
  template:
    metadata:
      labels:
        app: myapp
        version: v1
    spec:
      serviceAccountName: myapp  # Dedicated SA, not default
      terminationGracePeriodSeconds: 30
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: myapp
          image: registry.example.com/myapp:v1.2.3  # Always use specific tags
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          livenessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 15
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /ready
              port: http
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
          startupProbe:               # Slow-starting apps
            httpGet:
              path: /healthz
              port: http
            failureThreshold: 30
            periodSeconds: 10
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: POD_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
          volumeMounts:
            - name: config
              mountPath: /etc/myapp
              readOnly: true
            - name: tmp
              mountPath: /tmp         # Writable dir for readOnlyRootFilesystem
      volumes:
        - name: config
          configMap:
            name: myapp-config
        - name: tmp
          emptyDir: {}
      affinity:
        podAntiAffinity:             # Spread across nodes
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: myapp
                topologyKey: kubernetes.io/hostname
      topologySpreadConstraints:      # Even zone distribution
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: myapp
```

---

## StatefulSet

For workloads requiring stable network identity and persistent storage (databases, caches).

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: production
spec:
  serviceName: postgres-headless    # Required: headless service name
  replicas: 3
  revisionHistoryLimit: 5           # Keep 5 revisions for rollback
  podManagementPolicy: OrderedReady # Sequential startup (default)
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0                  # Update all pods (set higher for canary)
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: postgres
          image: postgres:16
          ports:
            - name: tcp-postgres
              containerPort: 5432
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "2"
              memory: 4Gi
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: gp3
        resources:
          requests:
            storage: 50Gi
---
# Headless Service (required for StatefulSet)
apiVersion: v1
kind: Service
metadata:
  name: postgres-headless
  namespace: production
spec:
  clusterIP: None                   # Headless
  selector:
    app: postgres
  ports:
    - name: tcp-postgres
      port: 5432
      targetPort: tcp-postgres
```

---

## DaemonSet

Runs exactly one pod per node (monitoring agents, log collectors, network plugins).

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
  selector:
    matchLabels:
      app: node-exporter
  template:
    metadata:
      labels:
        app: node-exporter
    spec:
      tolerations:                   # Run on all nodes including masters
        - operator: Exists
      hostNetwork: true              # Access node-level metrics
      containers:
        - name: node-exporter
          image: prom/node-exporter:v1.7.0
          ports:
            - name: metrics
              containerPort: 9100
              hostPort: 9100
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
```

---

## Service

### ClusterIP (internal only — default)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: myapp
  namespace: production
spec:
  type: ClusterIP
  selector:
    app: myapp
  ports:
    - name: http
      port: 80               # Service port (what clients connect to)
      targetPort: http        # Container port name or number
      protocol: TCP
```

### NodePort (expose on every node)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: myapp-nodeport
  namespace: production
spec:
  type: NodePort
  selector:
    app: myapp
  ports:
    - name: http
      port: 80
      targetPort: http
      nodePort: 30080         # Optional: 30000-32767 range
```

### LoadBalancer (cloud provider LB)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: myapp-lb
  namespace: production
  annotations:
    # AWS example:
    service.beta.kubernetes.io/aws-load-balancer-type: nlb
    service.beta.kubernetes.io/aws-load-balancer-scheme: internet-facing
spec:
  type: LoadBalancer
  selector:
    app: myapp
  ports:
    - name: https
      port: 443
      targetPort: http
```

### ExternalName (alias for external service)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-db
  namespace: production
spec:
  type: ExternalName
  externalName: mydb.example.com   # CNAME to external service
```

---

## Ingress

### HTTP with TLS

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp
  namespace: production
  annotations:
    # nginx-specific (adjust for your controller)
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - myapp.example.com
      secretName: myapp-tls          # TLS Secret with tls.crt + tls.key
  rules:
    - host: myapp.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: myapp
                port:
                  name: http
```

### Path-based routing (multiple backends)

```yaml
spec:
  rules:
    - host: example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: api-service
                port:
                  number: 80
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend-service
                port:
                  number: 80
```

---

## ConfigMap and Secret

### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: myapp-config
  namespace: production
data:
  # Simple key-value
  LOG_LEVEL: "info"
  MAX_CONNECTIONS: "100"
  # File content
  config.yaml: |
    server:
      port: 8080
      timeout: 30s
    database:
      pool_size: 10
```

### Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: myapp-secrets
  namespace: production
type: Opaque
stringData:                          # Use stringData (plaintext, encoded on apply)
  DATABASE_URL: "postgres://user:pass@host:5432/db"
  API_KEY: "sk-..."
```

### Mounting as Volume (preferred over env vars — supports live updates)

```yaml
containers:
  - name: myapp
    volumeMounts:
      - name: config
        mountPath: /etc/myapp/config.yaml
        subPath: config.yaml         # Mount single file, not directory
        readOnly: true
volumes:
  - name: config
    configMap:
      name: myapp-config
```

### As Environment Variables

```yaml
containers:
  - name: myapp
    envFrom:
      - configMapRef:
          name: myapp-config         # All keys become env vars
      - secretRef:
          name: myapp-secrets
    env:
      - name: SPECIFIC_KEY
        valueFrom:
          secretKeyRef:
            name: myapp-secrets
            key: API_KEY
```

---

## HPA (Horizontal Pod Autoscaler)

### CPU/Memory-based

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: myapp
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: myapp
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70     # Scale when avg CPU > 70%
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60   # Wait 60s before scaling up again
      policies:
        - type: Percent
          value: 50                     # Scale up by max 50% at a time
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300  # Wait 5m before scaling down
      policies:
        - type: Percent
          value: 25                     # Scale down by max 25% at a time
          periodSeconds: 120
```

**Requirements:** Resource `requests` must be set on containers for CPU/memory metrics to work. Metrics Server must be installed.

---

## PDB (PodDisruptionBudget)

Ensures minimum availability during voluntary disruptions (node drains, upgrades, autoscaler).

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: myapp
  namespace: production
spec:
  minAvailable: 2                    # Always keep at least 2 pods running
  # OR: maxUnavailable: 1            # Allow at most 1 pod down at a time
  selector:
    matchLabels:
      app: myapp
```

**Guidelines:**
- Use `minAvailable` for services with known minimum replica requirements
- Use `maxUnavailable: 1` for most stateless services (allows rolling disruptions)
- For StatefulSets with quorum (e.g., etcd): set `minAvailable` to quorum size
- Never set `minAvailable` equal to `replicas` — blocks all disruptions including upgrades

---

## NetworkPolicy

### Default Deny All (apply first, then allow selectively)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}                    # Applies to all pods in namespace
  policyTypes:
    - Ingress
    - Egress
```

### Allow DNS Egress (required after default deny)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

### Allow Specific Communication

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-myapp-to-db
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: database
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: myapp           # Only myapp pods can reach the database
      ports:
        - protocol: TCP
          port: 5432
```

---

## Resource Management

### Requests vs Limits

| Aspect | Requests | Limits |
|--------|----------|--------|
| Purpose | Scheduling guarantee (reserved) | Maximum allowed |
| CPU behavior | Guaranteed minimum | Throttled at limit |
| Memory behavior | Guaranteed minimum | OOMKilled at limit |
| Scheduler | Uses requests to place pods | Does not consider limits |

### QoS Classes

| Class | Condition | Eviction Priority |
|-------|-----------|-------------------|
| **Guaranteed** | requests == limits for all containers | Last to be evicted |
| **Burstable** | At least one request or limit set | Middle priority |
| **BestEffort** | No requests or limits set | First to be evicted |

**Production recommendation:** Set both requests and limits for all containers. Use Guaranteed QoS for critical workloads.

### LimitRange (namespace defaults)

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
    - type: Container
      default:                       # Default limits if not specified
        cpu: 500m
        memory: 512Mi
      defaultRequest:                # Default requests if not specified
        cpu: 100m
        memory: 128Mi
      max:                           # Maximum allowed
        cpu: "4"
        memory: 8Gi
      min:                           # Minimum required
        cpu: 50m
        memory: 64Mi
```

### ResourceQuota (namespace totals)

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: namespace-quota
  namespace: production
spec:
  hard:
    requests.cpu: "20"
    requests.memory: 40Gi
    limits.cpu: "40"
    limits.memory: 80Gi
    pods: "50"
    services.loadbalancers: "2"
    persistentvolumeclaims: "20"
```
