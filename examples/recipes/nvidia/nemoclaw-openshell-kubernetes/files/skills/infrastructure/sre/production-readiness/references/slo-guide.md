<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# SLO Design Guide

How to define and implement Service Level Objectives.

## SLO Fundamentals

### Key Concepts

| Term             | Definition                                           | Example               |
| ---------------- | ---------------------------------------------------- | --------------------- |
| **SLI**          | Service Level Indicator - metric measuring service   | Request success rate  |
| **SLO**          | Service Level Objective - target for the SLI         | 99.9% success rate    |
| **SLA**          | Service Level Agreement - contract with consequences | Refund if < 99.9%     |
| **Error Budget** | Allowed unreliability (100% - SLO)                   | 0.1% = 43.8 min/month |

### Common SLIs

**Availability**:

```
availability = successful_requests / total_requests
```

**Latency**:

```
latency_sli = requests_under_threshold / total_requests
# e.g., % of requests completing in < 200ms
```

**Error Rate**:

```
error_rate = failed_requests / total_requests
```

**Throughput**:

```
throughput = requests_processed / time_period
```

## Choosing SLOs

### Step 1: Identify User Journeys

Map the critical paths users take:

```
Critical User Journeys:
1. User login
2. Search products
3. Add to cart
4. Checkout
5. View order status
```

### Step 2: Define SLIs for Each Journey

```
Journey: User Login
SLIs:
- Availability: Login requests that succeed
- Latency: Time to complete login
- Error Rate: Login failures (auth errors excluded)
```

### Step 3: Set Targets

Start with these defaults if you're unsure:

| Service Type     | Availability | Latency (p99) | Error Rate |
| ---------------- | ------------ | ------------- | ---------- |
| User-facing API  | 99.9%        | < 500ms       | < 0.1%     |
| Internal API     | 99.5%        | < 1s          | < 0.5%     |
| Batch processing | 99%          | N/A           | < 1%       |
| Data pipeline    | 99%          | < 1h lag      | < 0.1%     |

### Step 4: Calculate Error Budget

```
Monthly Error Budget Calculation:

SLO: 99.9% availability
Error Budget: 0.1%

Minutes in month: 30 days × 24 hours × 60 min = 43,200 min
Allowed downtime: 43,200 × 0.001 = 43.2 minutes

Error Budget: 43.2 minutes of downtime per month
```

## Error Budget Policy

Define what happens as error budget is consumed:

```
Error Budget Policy:

Budget Remaining | Actions
-----------------|--------
> 50%            | Normal development velocity
25-50%           | Increase testing, slower rollouts
10-25%           | Freeze non-critical changes
< 10%            | All hands on reliability
0%               | Feature freeze until budget recovers
```

## SLO-Based Alerting

### Burn Rate Alerting

Instead of threshold alerts, alert on error budget burn rate:

```
Burn Rate = (Error Rate / Error Budget) × Window

Example:
- Error Budget: 0.1% (30-day)
- Current Error Rate: 1%
- Burn Rate: (1% / 0.1%) = 10x

At 10x burn rate, you'll exhaust 30-day budget in 3 days.
```

### Alert Windows

| Alert       | Burn Rate | Window | Budget Consumed |
| ----------- | --------- | ------ | --------------- |
| Page (SEV2) | 14.4x     | 1h     | 2% in 1h        |
| Page (SEV1) | 14.4x     | 5m     | 0.17% in 5m     |
| Ticket      | 6x        | 3d     | 10% in 3d       |
| Ticket      | 1x        | 30d    | 100% (on track) |

### Prometheus Alert Example

```yaml
groups:
  - name: slo-alerts
    rules:
      - alert: HighErrorBudgetBurn
        expr: |
          (
            sum(rate(http_requests_total{status=~"5.."}[1h]))
            /
            sum(rate(http_requests_total[1h]))
          ) > (14.4 * 0.001)  # 14.4x burn rate on 99.9% SLO
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: 'High error budget burn rate'
          description: 'Burning error budget at 14.4x rate'
```

## SLO Documentation Template

```markdown
# [Service Name] SLOs

## Overview

Brief description of service and its users.

## SLO Definitions

### Availability

- **SLI**: Proportion of successful HTTP requests
- **SLO**: 99.9%
- **Measurement**: (200-499 responses) / (all responses)
- **Window**: Rolling 30 days

### Latency

- **SLI**: Proportion of requests faster than threshold
- **SLO**: 99% of requests < 200ms (p99 < 500ms)
- **Measurement**: Request duration histogram
- **Window**: Rolling 30 days

## Error Budget

- Monthly budget: 43.2 minutes
- Current consumption: [link to dashboard]

## Error Budget Policy

[Link to policy document]

## Alerting

- Page: >14.4x burn rate for 5 minutes
- Ticket: >6x burn rate for 3 days

## Dashboards

- [SLO Dashboard](link)
- [Error Budget Dashboard](link)

## Owners

- Team: Platform Engineering
- Oncall: [rotation link]
```

## Common Mistakes

### Setting SLOs Too High

**Problem**: 99.99% SLO leaves only 4.3 minutes/month error budget.

**Reality Check**:

- 99.99% = Google-level engineering investment
- Most teams should start at 99.5% or 99.9%
- Raise SLO only when consistently meeting it

### No User-Centric SLIs

**Problem**: Measuring server CPU instead of user experience.

**Fix**: Focus on what users care about:

- Can they complete their task? (availability)
- How long does it take? (latency)
- Did they get the right result? (correctness)

### Alerting on SLO Instead of Burn Rate

**Problem**: Alert fires immediately at any degradation.

**Fix**: Use multi-window burn rate alerting:

- Short window (5m, 1h) for severe issues
- Long window (1d, 3d) for slow burns
- Alert when both windows show elevated burn rate
