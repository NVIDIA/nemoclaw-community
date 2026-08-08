#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Live walkthrough of the Blackwall verdict gate: GO, HOLD, and STOP.

Runs four payment scenarios against the free public Blackwall instance
(override with BLACKWALL_URL) and checks each verdict against what the
signals should produce:

  1. Warm counterparty at its fair market price      -> GO    (sign)
  2. Same counterparty quoted ~3.5x its median price  -> HOLD  (escalate)
  3. Unknown counterparty (cold start)                -> HOLD  (escalate)
  4. OFAC-sanctioned counterparty                     -> STOP  (refuse)

The warm/sanctioned addresses come from Blackwall's committed seed corpus
(public Base USDC history + the published OFAC list). If the corpus is
refreshed and a scenario's expectation drifts, the script says which one
and why rather than failing silently.

The first request may take up to ~60s: the free instance spins down when
idle and cold-starts on demand.
"""

from __future__ import annotations

import sys

from blackwall_client import forecast_payment, should_sign

# A payee from Blackwall's committed reputation seed (100+ settled x402
# payments on Base, 0% disputes). Its recorded median price for this
# resource class is ~0.014 USDC.
WARM_PAYEE = "0x02c2fcafce36b4aadb39625866bc6b1699d83043"
FAIR_PRICE = "0.014"
GOUGED_PRICE = "0.05"

# No on-chain history at all -> cold-start HOLD.
UNKNOWN_PAYEE = "0x0000000000000000000000000000000000000001"

# From the published OFAC SDN digital-currency list baked into the service.
SANCTIONED_PAYEE = "0x0330070fd38ec3bb94f58fa55d40368271e9e54a"

SCENARIOS = [
    ("warm payee, fair price", WARM_PAYEE, FAIR_PRICE, "GO", "sign"),
    ("warm payee, gouged price", WARM_PAYEE, GOUGED_PRICE, "HOLD", "escalate"),
    ("unknown payee (cold start)", UNKNOWN_PAYEE, FAIR_PRICE, "HOLD", "escalate"),
    ("sanctioned payee", SANCTIONED_PAYEE, FAIR_PRICE, "STOP", "refuse"),
]


def main() -> int:
    failures = 0
    for label, payee, amount, want_verdict, want_action in SCENARIOS:
        verdict = forecast_payment(payee, amount)
        got_verdict = verdict.get("verdict", "<error: %s>" % verdict.get("error"))
        got_action = should_sign(verdict)
        ok = got_verdict == want_verdict and got_action == want_action
        print("%s  %-28s  %s %s -> %s (gate: %s)"
              % ("PASS" if ok else "DRIFT", label, payee[:10] + "...",
                 amount, got_verdict, got_action))
        for reason in verdict.get("reasons", [])[:3]:
            print("       - %s" % reason)
        if not ok:
            failures += 1
            print("       expected %s (gate: %s) -- the seed corpus may have "
                  "been refreshed since this demo was written; pick a fresh "
                  "warm payee from the service's discovery endpoint or re-run "
                  "later" % (want_verdict, want_action))
        print()
    if failures:
        print("%d of %d scenarios drifted from their expected verdict."
              % (failures, len(SCENARIOS)))
        return 1
    print("All %d scenarios matched their expected verdicts." % len(SCENARIOS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
