<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# Severity Level Definitions

Detailed criteria for incident severity classification.

## SEV1 - Critical

**Response**: Immediate, all available responders

### Criteria (any one qualifies)

- Complete service outage affecting all users
- Data loss or corruption occurring
- Security breach confirmed or suspected
- Revenue-generating systems completely down
- Legal/compliance exposure
- Safety systems affected

### Examples

- Database cluster down, no reads or writes possible
- Payment processing completely failing
- Authentication service unavailable
- Customer PII exposed
- Primary data center unreachable

### Required Actions

- Page all on-call engineers
- Executive notification within 15 minutes
- Customer communication within 30 minutes
- War room established
- Updates every 15 minutes minimum

---

## SEV2 - High

**Response**: Primary on-call + backup, response within 15 minutes

### Criteria (any one qualifies)

- Major functionality unavailable
- Significant performance degradation (>50% users affected)
- High error rates (>10% of requests failing)
- Critical business process blocked
- Partial data loss risk

### Examples

- Search functionality completely broken
- Checkout flow failing for 50% of users
- API latency 10x normal causing timeouts
- Email notifications not sending
- Mobile app unable to sync

### Required Actions

- Primary and secondary on-call engaged
- Manager notification
- Customer communication within 1 hour
- Updates every 30 minutes

---

## SEV3 - Medium

**Response**: Primary on-call, response within 1 hour

### Criteria

- Partial functionality degraded
- Limited user impact (<10% of users)
- Workaround available
- Non-critical feature unavailable
- Elevated error rates (<10% of requests)

### Examples

- Report generation slow but working
- Image uploads failing, text posts work
- Single region experiencing elevated latency
- Admin dashboard partially broken
- Non-critical background job failing

### Required Actions

- Primary on-call investigates
- Team lead notified
- Fix within business hours acceptable
- No customer communication unless asked

---

## SEV4 - Low

**Response**: Next business day

### Criteria

- Minor issue with easy workaround
- No user impact or cosmetic only
- Single non-critical component affected
- Informational alerts
- Technical debt surfaced

### Examples

- UI misalignment on one page
- Non-blocking warning in logs
- Test environment issues
- Documentation out of date
- Deprecated API still in use

### Required Actions

- Create ticket
- Add to backlog
- Fix during normal work hours

---

## Severity Decision Tree

```
Is there data loss or security breach?
├─ Yes → SEV1
└─ No → Is the service completely unavailable?
        ├─ Yes → SEV1
        └─ No → Are >50% of users affected?
                ├─ Yes → SEV2
                └─ No → Are >10% of users affected?
                        ├─ Yes → SEV3
                        └─ No → Is there a workaround?
                                ├─ No → SEV3
                                └─ Yes → SEV4
```

## Escalation Triggers

Escalate severity UP when:

- Duration exceeds expected resolution time
- Impact spreading to more users/services
- Mitigation attempts failing
- Additional symptoms appearing
- Customer complaints increasing

Escalate severity DOWN when:

- Workaround identified and working
- Impact contained to smaller scope
- Partial mitigation successful
- Root cause identified with fix in progress

## Response Time SLAs

| Severity | Acknowledge | First Update | Resolution Target |
| -------- | ----------- | ------------ | ----------------- |
| SEV1     | 5 min       | 15 min       | ASAP (no target)  |
| SEV2     | 15 min      | 30 min       | 4 hours           |
| SEV3     | 1 hour      | 2 hours      | 24 hours          |
| SEV4     | 8 hours     | Next day     | 1 week            |
