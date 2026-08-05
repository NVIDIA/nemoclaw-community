---
name: payment-screening
description: Screen an outbound payment against limits, sanctions/watchlists, and duplicate checks before a human releases it.
---

# payment-screening

Use this skill when an operator asks you to check, validate, or screen an
outbound payment (wire or ACH) before release.

This skill is read-only. It does **not** release, send, or settle anything.
Release requires a human approver — see the `release-packet` skill.

## Inputs

- **Queue:** an ISO 20022 `pain.001` credit-transfer file
  (`data/payment-queue.json`). The screener flattens every
  `CdtTrfTxInf` transaction and screens it by `EndToEndId`.
- **Sanctions:** a bundled, dated **OFAC SDN** public-data fixture
  (`data/ofac-sdn-fixture.json`). It contains three real public SDN records
  selected for deterministic demonstration; it is not a complete sanctions
  list. Only the payments are synthetic.

## Procedure

### 1. Screen the payment

Run the screener against a payment ID from the queue (omit `--id` to screen
the whole batch):

```bash
/usr/bin/python3 /sandbox/.hermes/skills/payment-screening/scripts/screen_payment.py \
  --queue /sandbox/.hermes/skills/payment-screening/data/payment-queue.json \
  --sanctions /sandbox/.hermes/skills/payment-screening/data/ofac-sdn-fixture.json \
  --id WIRE-1007
```

The screener returns structured JSON with a `decision`
(`CLEARED_FOR_REVIEW` or `HOLD`) and a per-check breakdown. Sanctions hits
cite the matched OFAC SDN name and program.

### 2. Report the result

Use this structure:

- **Decision:** CLEARED_FOR_REVIEW or HOLD
- **Checks:** limit · sanctions · duplicate · beneficiary (pass/fail each)
- **Exceptions:** the exact rule that fired, in plain language
- **Next step:** what the human checker should verify before releasing
- **Caveat:** screening is support; the human approver is accountable

### 3. On HOLD

Never recommend overriding a hold. State the rule, and route to the
appropriate human queue (sanctions analyst, treasury, compliance).

## Pitfalls

- Do not claim a payment passed if any check failed.
- Do not invent a sanctions match or clear a real one — report what the
  OFAC SDN fixture returned, with the matched name and program.
- Do not release the payment. You cannot reach the payment rail, and you
  must not imply that you can.
