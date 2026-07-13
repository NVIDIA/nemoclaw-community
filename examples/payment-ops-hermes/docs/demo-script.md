# Demo Script — FinGuard Payment Operations

Audience: payment-operations, treasury, and risk/compliance leaders.
KPI: visitor leaves asking *"can we run this against our payment flow?"*
Time: 90 seconds standing, 5 minutes seated.

## The frame

> "Every bank wants to put AI on the payment-ops desk to clear the queue
> faster. And every bank's CISO says the same thing: *not if it can move
> money.* This is FinGuard on NVIDIA NeMo Claw. It screens payments and
> prepares them — but it physically cannot release one. A human always
> does. And that's not a prompt rule; it's enforced by the sandbox."

## 1. Show the boundary in the policy (30s)

```bash
sed -n '1,220p' policy.yaml
```

Talking point: "Screening uses a bundled read-only sanctions fixture. The payment rail
is **not** in this policy. Deny-by-default means FinGuard cannot reach it."

## 2. Screen the queue (45s)

```bash
openshell sandbox exec --name payment-ops -- /usr/bin/python3 \
  /sandbox/.hermes/skills/payment-screening/scripts/screen_payment.py \
  --queue /sandbox/.hermes/skills/payment-screening/data/payment-queue.json \
  --sanctions /sandbox/.hermes/skills/payment-screening/data/ofac-sdn-fixture.json
```

Talking point: "One clears. The rest hold — over-limit, a duplicate pair, a
missing beneficiary IBAN, and a real **OFAC sanctions** hit on `BANK
ROSSIYA`. That positive control is a real public Treasury SDN record in a
small, dated demo fixture—not a complete or production sanctions list."

## 3. The money shot — release is blocked (30s)

Ask FinGuard to release the cleared payment, or run the rail call directly:

```bash
openshell sandbox exec --name payment-ops -- /usr/bin/curl -sS -X POST \
  https://payments-rail.internal/release -d '{"payment_id":"WIRE-1007"}'
# -> policy denied: payments-rail.internal not in network_policies
```

Talking point: "It tried. The platform dropped it before it left the
sandbox. This is the whole demo: the agent is the maker, and the maker
cannot also be the checker."

## 4. A human releases (30s)

```bash
python3 scripts/approve_release.py --id WIRE-1007 --approver "Jane Ops"
python3 scripts/approve_release.py --id ACH-2003 --approver "Jane Ops"  # refused: HOLD
```

Talking point: "The human approver, on the host, releases the cleared
payment — and the tool still refuses to release a held one. In production
this is your existing payment system and its approval step; NeMo Claw just
keeps the agent on the maker side of that line."

## 5. Close

> "Same desk, same queue. What changes is that the AI can prepare
> everything and move nothing. Want to try it against your own payment
> flow? Let's set up a session."

## What to avoid saying

- ❌ "FinGuard decides not to release." → It doesn't decide. The sandbox
  makes the rail unreachable.
- ❌ "It's a payment product." → It's a reference deployment showing
  platform-enforced maker-checker.
- ❌ Treating the synthetic payments or the dated OFAC fixture as live.

## Likely questions

| Question | Short answer |
|----------|--------------|
| "Is the sanctions data real?" | The positive control is a real public OFAC SDN record in a three-record fixture. Production must use a complete maintained list or screening service. |
| "Where do the payments come from?" | Synthetic, ISO 20022 `pain.001` shaped. No real payment data. |
| "Could a prompt jailbreak it into releasing?" | No — release egress is denied at the sandbox, independent of the prompt or model. |
| "How does this fit our rail?" | The agent never touches the rail. Your existing approval step stays the human checker. |
