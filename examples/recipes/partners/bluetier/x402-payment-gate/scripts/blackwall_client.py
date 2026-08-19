#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Minimal stdlib client for the Blackwall x402 payment-verdict service.

Blackwall answers one question before an agent signs an x402 payment:
should this payment happen? It returns GO / HOLD / STOP from counterparty
reputation, price-anomaly, OFAC sanctions, and Sybil/graph signals.

This client is stdlib-only (urllib) so it runs unmodified inside an
OpenShell sandbox with no package installs. The sandbox network policy
(../policy.yaml) restricts it to exactly the verdict endpoints it needs.

Usage as a library:

    from blackwall_client import forecast_payment, should_sign
    verdict = forecast_payment("0xPayee...", "0.014")
    action = should_sign(verdict)   # "sign" | "escalate" | "refuse"

Usage from a shell:

    python3 blackwall_client.py --counterparty 0xPayee... --amount 0.014
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = os.environ.get(
    "BLACKWALL_URL", "https://blackwall-free.onrender.com"
)
# The free instance spins down when idle; the first request is a slow cold
# start (up to ~60s). Later requests are fast.
DEFAULT_TIMEOUT = 90

# Outcomes the /v1/report-outcome endpoint accepts (ledger vocabulary).
VALID_OUTCOMES = (
    "settled", "delivered",              # good: counts toward reputation
    "underdelivered", "disputed", "refunded",  # bad: counts toward disputes
    "abandoned",                         # neutral: GO issued but never paid
)


def should_sign(verdict: dict) -> str:
    """Map a Blackwall verdict to the agent's next action.

    Pure decision function -- no I/O. Returns one of:
      "sign"     -- GO: proceed to sign the x402 payment.
      "escalate" -- HOLD (or anything unrecognized): do NOT sign; surface the
                    verdict's `reasons` to a human or a higher-trust policy.
      "refuse"   -- STOP or hard_stop: never sign; the counterparty is
                    sanctioned or the payload does not match the claim.

    Unknown/malformed verdicts map to "escalate", never "sign": the gate
    fails toward human review, not toward moving money.
    """
    if not isinstance(verdict, dict):
        return "escalate"
    if verdict.get("hard_stop") or verdict.get("verdict") == "STOP":
        return "refuse"
    if verdict.get("verdict") == "GO":
        return "sign"
    return "escalate"


def _post_json(url: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 4xx/5xx bodies are JSON error objects; surface them instead of a stack.
        try:
            detail = json.loads(e.read().decode("utf-8"))
        except Exception:
            detail = {"error": str(e)}
        detail.setdefault("http_status", e.code)
        return detail


def forecast_payment(counterparty: str, amount: str, asset: str = "USDC",
                     chain: str = "base", resource: str | None = None,
                     payer: str | None = None,
                     base_url: str = DEFAULT_BASE_URL,
                     timeout: int = DEFAULT_TIMEOUT) -> dict:
    """POST /v1/forecast-payment -- ask for a verdict BEFORE signing.

    Required: counterparty (the x402 payTo address), amount (positive decimal
    string, e.g. "0.014"), asset, chain. Optional: resource (the URL being
    paid for -- enables the per-category price baseline), payer (the agent's
    own wallet, binds settlement confirmation to this agent).

    Returns the verdict dict: verdict (GO/HOLD/STOP), hard_stop, score,
    reasons[], signals{}, confidence{}, receipt_id, report_token.
    """
    body = {"counterparty": counterparty, "amount": amount,
            "asset": asset, "chain": chain}
    if resource:
        body["resource"] = resource
    if payer:
        body["payer"] = payer
    return _post_json(base_url.rstrip("/") + "/v1/forecast-payment",
                      body, timeout)


def report_outcome(receipt_id: str, report_token: str, outcome: str,
                   base_url: str = DEFAULT_BASE_URL,
                   timeout: int = DEFAULT_TIMEOUT) -> dict:
    """POST /v1/report-outcome -- close the loop on a prior verdict.

    After the payment settles (or fails), report what actually happened so
    the counterparty's reputation reflects real outcomes. `outcome` must be
    one of VALID_OUTCOMES; `report_token` came back with the verdict and is
    the capability that authorizes reporting on that receipt_id.
    """
    return _post_json(base_url.rstrip("/") + "/v1/report-outcome",
                      {"receipt_id": receipt_id, "report_token": report_token,
                       "outcome": outcome}, timeout)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Ask Blackwall for a GO/HOLD/STOP verdict on an x402 payment.")
    p.add_argument("--counterparty", required=True,
                   help="x402 payTo address the agent is about to pay")
    p.add_argument("--amount", required=True,
                   help='positive decimal string, e.g. "0.014"')
    p.add_argument("--asset", default="USDC")
    p.add_argument("--chain", default="base")
    p.add_argument("--resource", default=None,
                   help="URL of the resource being paid for (optional)")
    p.add_argument("--payer", default=None,
                   help="the agent's own wallet address (optional)")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = p.parse_args(argv)

    verdict = forecast_payment(args.counterparty, args.amount,
                               asset=args.asset, chain=args.chain,
                               resource=args.resource, payer=args.payer,
                               base_url=args.base_url)
    print(json.dumps(verdict, indent=2))
    action = should_sign(verdict)
    print("\naction: %s" % action, file=sys.stderr)
    # Exit code mirrors the gate so shell callers can branch on it:
    # 0 = sign, 1 = escalate, 2 = refuse.
    return {"sign": 0, "escalate": 1, "refuse": 2}[action]


if __name__ == "__main__":
    raise SystemExit(main())
