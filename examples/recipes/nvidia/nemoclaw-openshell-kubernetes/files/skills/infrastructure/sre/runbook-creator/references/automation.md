<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# Runbook Automation

Patterns for automating runbook procedures.

## Automation Principles

1. **Start Manual, Then Automate**: Validate procedures manually first
2. **Partial Automation**: Automate diagnostics, keep remediation manual
3. **Safe Defaults**: Automated actions should be low-risk
4. **Human Oversight**: Critical actions require approval

## Automation Levels

| Level | Description | Example |
|-------|-------------|---------|
| L0 | Fully manual | SSH in, run commands |
| L1 | Documented steps | Copy-paste from runbook |
| L2 | Script-assisted | Run diagnostic script |
| L3 | Semi-automated | Script suggests actions, human approves |
| L4 | Fully automated | Self-healing, no human needed |

## Diagnostic Scripts

### Service Health Check Script

```bash
#!/bin/bash
# diagnose-service.sh - Quick service diagnostics

SERVICE=$1
NAMESPACE=${2:-production}

echo "=== Diagnosing $SERVICE in $NAMESPACE ==="

echo -e "\n--- Pod Status ---"
kubectl get pods -n $NAMESPACE -l app=$SERVICE

echo -e "\n--- Recent Events ---"
kubectl get events -n $NAMESPACE --field-selector involvedObject.name=$SERVICE --sort-by='.lastTimestamp' | tail -10

echo -e "\n--- Resource Usage ---"
kubectl top pods -n $NAMESPACE -l app=$SERVICE 2>/dev/null || echo "Metrics not available"

echo -e "\n--- Recent Logs (errors only) ---"
kubectl logs -l app=$SERVICE -n $NAMESPACE --tail=50 2>/dev/null | grep -i error | tail -10

echo -e "\n--- Deployment Status ---"
kubectl rollout status deployment/$SERVICE -n $NAMESPACE --timeout=5s 2>/dev/null

echo -e "\n=== Diagnosis Complete ==="
```

### Database Connection Check

```bash
#!/bin/bash
# check-db-connections.sh - Database connection diagnostics

DB_HOST=$1
DB_PORT=${2:-5432}
DB_NAME=${3:-postgres}

echo "=== Database Connection Check ==="

# Connection count
echo -e "\n--- Connection Summary ---"
psql -h $DB_HOST -p $DB_PORT -d $DB_NAME -c "
SELECT state, count(*) 
FROM pg_stat_activity 
GROUP BY state 
ORDER BY count DESC;
"

# Top connection consumers
echo -e "\n--- Top Connection Consumers ---"
psql -h $DB_HOST -p $DB_PORT -d $DB_NAME -c "
SELECT application_name, count(*) as connections
FROM pg_stat_activity 
WHERE application_name != ''
GROUP BY application_name 
ORDER BY connections DESC
LIMIT 10;
"

# Long-running queries
echo -e "\n--- Long Running Queries (>1 min) ---"
psql -h $DB_HOST -p $DB_PORT -d $DB_NAME -c "
SELECT pid, now() - query_start AS duration, left(query, 80) as query
FROM pg_stat_activity
WHERE state = 'active' AND query_start < now() - interval '1 minute'
ORDER BY duration DESC
LIMIT 5;
"

echo -e "\n=== Check Complete ==="
```

## Semi-Automated Remediation

### Safe Restart Script

```bash
#!/bin/bash
# safe-restart.sh - Restart with pre-flight checks

SERVICE=$1
NAMESPACE=${2:-production}

echo "=== Pre-flight Checks for $SERVICE ==="

# Check current state
READY_PODS=$(kubectl get pods -n $NAMESPACE -l app=$SERVICE -o jsonpath='{.items[*].status.conditions[?(@.type=="Ready")].status}' | tr ' ' '\n' | grep -c True)
TOTAL_PODS=$(kubectl get pods -n $NAMESPACE -l app=$SERVICE --no-headers | wc -l)

echo "Current state: $READY_PODS/$TOTAL_PODS pods ready"

if [ "$READY_PODS" -eq 0 ]; then
    echo "WARNING: No pods currently ready. Restart may cause outage."
    read -p "Continue anyway? (yes/no): " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "Aborted."
        exit 1
    fi
fi

# Check if there's a recent deployment in progress
ROLLOUT_STATUS=$(kubectl rollout status deployment/$SERVICE -n $NAMESPACE --timeout=5s 2>&1)
if echo "$ROLLOUT_STATUS" | grep -q "waiting"; then
    echo "WARNING: Deployment already in progress."
    exit 1
fi

echo -e "\n=== Executing Restart ==="
read -p "Proceed with restart? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

kubectl rollout restart deployment/$SERVICE -n $NAMESPACE

echo -e "\n=== Monitoring Rollout ==="
kubectl rollout status deployment/$SERVICE -n $NAMESPACE

echo -e "\n=== Post-Restart Verification ==="
sleep 10
kubectl get pods -n $NAMESPACE -l app=$SERVICE
```

## ChatOps Integration

### Slack Slash Command Handler

```python
# slack_runbook_handler.py
from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

ALLOWED_COMMANDS = {
    'diagnose': {
        'script': './scripts/diagnose-service.sh',
        'args': ['service', 'namespace'],
        'safe': True
    },
    'restart': {
        'script': './scripts/safe-restart.sh', 
        'args': ['service', 'namespace'],
        'safe': False,
        'requires_approval': True
    }
}

@app.route('/runbook', methods=['POST'])
def handle_command():
    data = request.form
    user = data.get('user_name')
    text = data.get('text', '').split()
    
    if not text:
        return jsonify({'text': 'Usage: /runbook <command> <args>'})
    
    command = text[0]
    args = text[1:]
    
    if command not in ALLOWED_COMMANDS:
        return jsonify({'text': f'Unknown command: {command}'})
    
    cmd_config = ALLOWED_COMMANDS[command]
    
    # Check if approval needed
    if cmd_config.get('requires_approval') and not is_approved(user, command):
        return jsonify({
            'text': f'Command requires approval. Use /approve {command} to approve.'
        })
    
    # Execute script
    try:
        result = subprocess.run(
            [cmd_config['script']] + args,
            capture_output=True,
            text=True,
            timeout=60
        )
        return jsonify({
            'text': f'```\n{result.stdout}\n```',
            'response_type': 'in_channel'
        })
    except subprocess.TimeoutExpired:
        return jsonify({'text': 'Command timed out'})
    except Exception as e:
        return jsonify({'text': f'Error: {str(e)}'})
```

## Kubernetes Operators

### Simple Self-Healing Controller

```yaml
# self-healing-policy.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: self-healing-rules
data:
  rules.yaml: |
    rules:
      - name: restart-on-oom
        condition:
          type: event
          reason: OOMKilled
        action:
          type: restart
          maxRestarts: 3
          cooldown: 5m
          
      - name: scale-on-high-cpu
        condition:
          type: metric
          query: avg(cpu_usage) > 0.8
          duration: 5m
        action:
          type: scale
          replicas: "+2"
          maxReplicas: 10
```

## Best Practices

### Do Automate

- Diagnostic information gathering
- Health checks
- Metric collection
- Log aggregation
- Notifications

### Be Careful Automating

- Service restarts
- Scaling decisions
- Failovers
- Cache clears

### Don't Automate (Keep Manual)

- Data deletion
- Production database changes
- Security-sensitive operations
- Irreversible actions

## Testing Automation

```bash
#!/bin/bash
# test-runbook.sh - Test runbook scripts in staging

SCRIPT=$1
TEST_ENV="staging"

echo "=== Testing $SCRIPT in $TEST_ENV ==="

# Run with dry-run if supported
if grep -q "DRY_RUN" "$SCRIPT"; then
    DRY_RUN=true bash "$SCRIPT" test-service $TEST_ENV
else
    echo "WARNING: Script doesn't support dry-run"
    read -p "Run in staging anyway? (yes/no): " CONFIRM
    if [ "$CONFIRM" = "yes" ]; then
        bash "$SCRIPT" test-service $TEST_ENV
    fi
fi
```
