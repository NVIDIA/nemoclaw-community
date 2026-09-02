<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# kubectl Cheat Sheet

Essential kubectl commands for troubleshooting.

## Cluster Information

```bash
# Cluster info
kubectl cluster-info
kubectl version

# Node status
kubectl get nodes
kubectl describe node <node-name>
kubectl top nodes
```

## Pod Operations

### Viewing Pods

```bash
# List pods
kubectl get pods                              # Current namespace
kubectl get pods -n <namespace>               # Specific namespace
kubectl get pods -A                           # All namespaces
kubectl get pods -o wide                      # More details (IP, node)
kubectl get pods --show-labels                # Show labels
kubectl get pods -l app=myapp                 # Filter by label
kubectl get pods --field-selector status.phase=Running

# Non-running pods (troubleshooting)
kubectl get pods -A | grep -v Running
kubectl get pods -A | grep -E 'Error|CrashLoop|Pending|Unknown'
```

### Pod Details

```bash
# Describe (events, status, conditions)
kubectl describe pod <pod-name> -n <namespace>

# YAML output
kubectl get pod <pod-name> -o yaml

# JSON path queries
kubectl get pod <pod-name> -o jsonpath='{.status.phase}'
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].restartCount}'
```

### Pod Logs

```bash
# Basic logs
kubectl logs <pod-name>
kubectl logs <pod-name> -n <namespace>

# Options
kubectl logs <pod-name> --tail=100            # Last 100 lines
kubectl logs <pod-name> -f                    # Follow (stream)
kubectl logs <pod-name> --previous            # Previous container
kubectl logs <pod-name> -c <container>        # Specific container
kubectl logs <pod-name> --since=1h            # Last hour
kubectl logs <pod-name> --timestamps          # With timestamps

# All containers in pod
kubectl logs <pod-name> --all-containers
```

### Pod Execution

```bash
# Execute command
kubectl exec <pod-name> -- <command>
kubectl exec <pod-name> -n <namespace> -- ls -la

# Interactive shell
kubectl exec -it <pod-name> -- /bin/sh
kubectl exec -it <pod-name> -- /bin/bash
kubectl exec -it <pod-name> -c <container> -- /bin/sh

# Common debugging commands
kubectl exec <pod-name> -- env                # Environment vars
kubectl exec <pod-name> -- cat /etc/hosts     # DNS entries
kubectl exec <pod-name> -- printenv           # All env vars
kubectl exec <pod-name> -- wget -qO- localhost:8080/health
```

### Pod Management

```bash
# Delete pod (triggers restart if managed by controller)
kubectl delete pod <pod-name> -n <namespace>

# Force delete stuck pod
kubectl delete pod <pod-name> --grace-period=0 --force

# Copy files
kubectl cp <pod-name>:/path/to/file ./local-file
kubectl cp ./local-file <pod-name>:/path/to/file
```

## Deployments

```bash
# List deployments
kubectl get deployments -n <namespace>
kubectl describe deployment <name> -n <namespace>

# Scaling
kubectl scale deployment <name> --replicas=3

# Rollout status
kubectl rollout status deployment/<name>
kubectl rollout history deployment/<name>

# Rollback
kubectl rollout undo deployment/<name>
kubectl rollout undo deployment/<name> --to-revision=2

# Restart (rolling restart)
kubectl rollout restart deployment/<name>
```

## Services & Networking

```bash
# List services
kubectl get svc -n <namespace>
kubectl describe svc <service-name>

# Endpoints (pods backing a service)
kubectl get endpoints <service-name>

# Port forwarding (local debugging)
kubectl port-forward pod/<pod-name> 8080:80
kubectl port-forward svc/<service-name> 8080:80

# DNS debugging
kubectl run dnsutils --rm -it --image=gcr.io/kubernetes-e2e-test-images/dnsutils -- nslookup <service>
```

## ConfigMaps & Secrets

```bash
# List
kubectl get configmaps -n <namespace>
kubectl get secrets -n <namespace>

# View contents
kubectl get configmap <name> -o yaml
kubectl get secret <name> -o yaml

# Decode secret
kubectl get secret <name> -o jsonpath='{.data.password}' | base64 -d

# Create from file
kubectl create configmap <name> --from-file=<path>
kubectl create secret generic <name> --from-literal=password=mypass
```

## Resource Usage

```bash
# Node resources
kubectl top nodes
kubectl describe node <node> | grep -A 10 "Allocated resources"

# Pod resources
kubectl top pods -n <namespace>
kubectl top pods -A --sort-by=memory
kubectl top pods -A --sort-by=cpu
kubectl top pod <pod-name> --containers
```

## Events

```bash
# All events in namespace
kubectl get events -n <namespace>

# Sorted by time
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# Watch events
kubectl get events -n <namespace> -w

# Filter warnings
kubectl get events -n <namespace> --field-selector type=Warning
```

## Debugging Pods

```bash
# Create debug pod
kubectl run debug --rm -it --image=busybox -- /bin/sh
kubectl run debug --rm -it --image=nicolaka/netshoot -- /bin/bash

# Debug existing pod (ephemeral container)
kubectl debug <pod-name> -it --image=busybox

# Node debugging
kubectl debug node/<node-name> -it --image=busybox
```

## Context & Namespace

```bash
# View contexts
kubectl config get-contexts
kubectl config current-context

# Switch context
kubectl config use-context <context-name>

# Set default namespace
kubectl config set-context --current --namespace=<namespace>

# Quick namespace switch (with alias)
alias kns='kubectl config set-context --current --namespace'
kns production
```

## Output Formatting

```bash
# Output formats
kubectl get pods -o wide                      # Additional columns
kubectl get pods -o yaml                      # YAML
kubectl get pods -o json                      # JSON
kubectl get pods -o name                      # Just names

# Custom columns
kubectl get pods -o custom-columns=NAME:.metadata.name,STATUS:.status.phase

# JSONPath
kubectl get pods -o jsonpath='{.items[*].metadata.name}'
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
```

## Useful Aliases

```bash
# Add to ~/.bashrc or ~/.zshrc
alias k='kubectl'
alias kgp='kubectl get pods'
alias kgpa='kubectl get pods -A'
alias kgs='kubectl get svc'
alias kgd='kubectl get deployments'
alias kdp='kubectl describe pod'
alias kl='kubectl logs'
alias klf='kubectl logs -f'
alias kex='kubectl exec -it'
alias kaf='kubectl apply -f'
alias kdf='kubectl delete -f'

# Get non-running pods
alias knotready='kubectl get pods -A | grep -v Running'
```
