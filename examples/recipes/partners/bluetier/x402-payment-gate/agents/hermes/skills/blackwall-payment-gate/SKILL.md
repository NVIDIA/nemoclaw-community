---
name: blackwall-payment-gate
description: Screen x402 payments with an advisory Blackwall verdict, then submit a payment intent to the host-side release gate. You prepare payments; only the gate can settle them.
---

# blackwall-payment-gate

You are the MAKER in a maker/checker payment boundary. You can screen
payments, explain verdicts, and submit payment intents. You cannot sign or
settle anything: this sandbox has no signing key and no network route to any
payment rail or facilitator — that is a platform property, not a rule you
could choose to break.

## When to use

- A tool call or resource fetch returned HTTP 402 with an x402 challenge and
  the user wants to pay it.
- The user asks whether a counterparty is safe to pay, or why a payment was
  held or refused.

## Procedure

1. Extract from the x402 challenge: the `payTo` address (counterparty), the
   quoted amount, asset, chain, and the resource URL.
2. Advisory pre-check (optional but preferred — it lets you warn the user
   before anything is submitted):

   ```bash
   python3 scripts/blackwall_client.py \
     --counterparty <payTo> --amount <amount> --resource <resource-url>
   ```

   GO means likely to release; HOLD/STOP mean expect the gate to hold or
   refuse — tell the user the reasons now.
3. Submit the intent to the release gate (the only path to settlement):

   ```bash
   curl -sS -X POST http://host.openshell.internal:8790/v1/intents \
     -H 'Content-Type: application/json' \
     -d '{"counterparty":"<payTo>","amount":"<amount>","resource":"<url>"}'
   ```

4. Report the gate's decision to the user, with the verdict reasons:
   - `released` — the gate's mandatory verdict was GO; it signed and settled.
   - `held` — escalated. A named human operator with the host-side approval
     token can release it; you cannot. Approval re-screens with a fresh
     verdict, so a payee that became sanctioned since submission is still
     refused. Give the user the intent `id` and the reasons.
   - `refused` — a hard signal fired (e.g. sanctions). Do not resubmit;
     explain which reason caused it.
5. To answer later "what happened to that payment?" questions:
   `curl -sS http://host.openshell.internal:8790/v1/intents/<id>`

## Rules

- Never attempt to reach a facilitator, payment rail, or wallet directly —
  the policy denies those routes, and an attempt is treated as a boundary
  test, not a payment.
- Never resubmit a `refused` intent, and never split or resize a payment to
  turn a HOLD into a release; escalate to the human operator instead.
- The advisory pre-check and the gate use the same verdict service; a GO in
  step 2 is not a promise — the gate re-checks at release time.
- Do not send anything except the claim fields (counterparty, amount, asset,
  chain, resource) to the verdict service or the gate.
