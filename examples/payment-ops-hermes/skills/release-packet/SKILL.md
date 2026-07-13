---
name: release-packet
description: Prepare a human-approval release packet for a screened payment. Does not release funds — release requires a human checker.
---

# release-packet

Use this skill after `payment-screening` returns `CLEARED_FOR_REVIEW`, when
an operator wants the payment prepared for a human approver.

This skill prepares a packet marked `PENDING_HUMAN_APPROVAL`. It does **not**
contact the payment rail. FinGuard cannot reach `payments-rail.internal` —
that egress is denied by the sandbox policy. Only a human approver on the
host can release.

## Procedure

### 1. Re-screen, then prepare the packet

```bash
/usr/bin/python3 /sandbox/.hermes/skills/release-packet/scripts/prepare_release_packet.py \
  --queue /sandbox/.hermes/skills/payment-screening/data/payment-queue.json \
  --sanctions /sandbox/.hermes/skills/payment-screening/data/ofac-sdn-fixture.json \
  --id WIRE-1007 \
  --maker "$USER"
```

The packet includes the payment, the screening result, the maker identity,
and `status: PENDING_HUMAN_APPROVAL`.

### 2. Hand off to a human checker

Tell the operator, explicitly, that release is a human action:

> "Release packet prepared for WIRE-1007, status PENDING_HUMAN_APPROVAL.
> I cannot release this — a human approver must run the release on the host."

### 3. If asked to release anyway

Do not attempt it. If you try to POST to the payment rail, the sandbox
drops the connection (deny-by-default). That is by design: maker-checker is
enforced by the platform. Restate that a human approver is required.

## Pitfalls

- Never set `status` to anything implying the payment was sent.
- Never claim funds moved.
- Do not prepare a packet for a payment that screened as `HOLD`.
