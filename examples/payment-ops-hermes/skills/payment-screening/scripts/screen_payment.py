#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Read-only payment screener for the FinGuard payment-operations example.

Reads an ISO 20022 pain.001 credit-transfer queue and a bundled OFAC SDN
fixture, then prints a structured JSON verdict per payment. It NEVER
releases a payment: it only reads fixtures and reports a decision for a human.

Checks:
  - limit       : amount within the per-payment limit for its rail
  - sanctions   : beneficiary / beneficiary bank not on the OFAC SDN list
  - duplicate   : no other payment with same beneficiary+amount+value date
  - beneficiary : required beneficiary fields present (name, IBAN, bank)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Per-payment limits by rail (synthetic demo values, in USD).
RAIL_LIMITS = {
    "WIRE": 1_000_000.00,
    "ACH": 250_000.00,
    "SWIFT": 5_000_000.00,
}


def load_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm(text: str | None) -> str:
    return " ".join(str(text or "").strip().lower().split())


def parse_iso20022(doc: dict) -> list[dict]:
    """Flatten an ISO 20022 pain.001 document into normalized payment dicts."""
    initn = doc.get("Document", {}).get("CstmrCdtTrfInitn", {})
    pmt_infs = initn.get("PmtInf", [])
    if isinstance(pmt_infs, dict):
        pmt_infs = [pmt_infs]
    payments: list[dict] = []
    for pi in pmt_infs:
        value_date = pi.get("ReqdExctnDt", {}).get("Dt", "")
        txs = pi.get("CdtTrfTxInf", [])
        if isinstance(txs, dict):
            txs = [txs]
        for tx in txs:
            cdtr = tx.get("Cdtr", {})
            cdtr_agt = tx.get("CdtrAgt", {}).get("FinInstnId", {})
            amt = tx.get("Amt", {}).get("InstdAmt", {})
            payments.append({
                "id": tx.get("PmtId", {}).get("EndToEndId"),
                "rail": tx.get("PmtTpInf", {}).get("SvcLvl", {}).get("Prtry", "WIRE"),
                "amount": float(amt.get("value", 0) or 0),
                "currency": amt.get("Ccy"),
                "beneficiary_name": cdtr.get("Nm", ""),
                "beneficiary_account": tx.get("CdtrAcct", {}).get("Id", {}).get("IBAN", ""),
                "beneficiary_bank": cdtr_agt.get("Nm", "") or cdtr_agt.get("BICFI", ""),
                "beneficiary_country": cdtr.get("PstlAdr", {}).get("Ctry", ""),
                "value_date": value_date,
            })
    return payments


def load_sanctions(path: str) -> list[dict]:
    """Load the bundled OFAC fixture; pre-tokenize names for safe matching."""
    snap = load_json(path)
    entries = snap.get("entries", []) if isinstance(snap, dict) else snap
    out = []
    for e in entries:
        n = norm(e.get("name"))
        if n:
            out.append({"name": e.get("name"), "norm": n, "tokens": set(n.split()),
                        "type": e.get("type"), "programs": e.get("programs")})
    return out


def sanctions_hits(target: str, sdn: list[dict]) -> list[dict]:
    """Token-safe match: exact normalized equality, or all SDN tokens present
    for a multi-token SDN name (avoids single common-word false positives)."""
    t = norm(target)
    if not t:
        return []
    ttokens = set(t.split())
    hits = []
    for e in sdn:
        if e["norm"] == t or (len(e["tokens"]) >= 2 and e["tokens"] <= ttokens):
            hits.append({"matched_field": target, "sdn_name": e["name"],
                         "type": e["type"], "programs": e["programs"]})
    return hits


def check_limit(p: dict) -> dict:
    rail = str(p.get("rail", "")).upper()
    amount = float(p.get("amount", 0) or 0)
    limit = RAIL_LIMITS.get(rail)
    if limit is None:
        return {"name": "limit", "passed": False, "detail": f"unknown rail '{rail}'"}
    if amount > limit:
        return {"name": "limit", "passed": False,
                "detail": f"amount {amount:,.2f} exceeds {rail} limit {limit:,.2f}"}
    return {"name": "limit", "passed": True,
            "detail": f"amount {amount:,.2f} within {rail} limit {limit:,.2f}"}


def check_sanctions(p: dict, sdn: list[dict]) -> dict:
    hits = sanctions_hits(p.get("beneficiary_name"), sdn) + \
        sanctions_hits(p.get("beneficiary_bank"), sdn)
    if hits:
        return {"name": "sanctions", "passed": False,
                "detail": f"{len(hits)} OFAC SDN match(es)", "hits": hits}
    return {"name": "sanctions", "passed": True, "detail": "no OFAC SDN match"}


def check_duplicate(p: dict, payments: list[dict]) -> dict:
    key = (norm(p.get("beneficiary_name")), float(p.get("amount", 0) or 0),
           str(p.get("value_date", "")))
    dupes = [q["id"] for q in payments if q.get("id") != p.get("id") and
             (norm(q.get("beneficiary_name")), float(q.get("amount", 0) or 0),
              str(q.get("value_date", ""))) == key]
    if dupes:
        return {"name": "duplicate", "passed": False,
                "detail": f"possible duplicate of {', '.join(dupes)}"}
    return {"name": "duplicate", "passed": True, "detail": "no duplicate found"}


def check_beneficiary(p: dict) -> dict:
    required = {"beneficiary_name": "name", "beneficiary_account": "IBAN",
               "beneficiary_bank": "bank"}
    missing = [label for f, label in required.items() if not str(p.get(f, "")).strip()]
    if missing:
        return {"name": "beneficiary", "passed": False,
                "detail": f"missing fields: {', '.join(missing)}"}
    return {"name": "beneficiary", "passed": True, "detail": "beneficiary fields present"}


def screen(payment: dict, payments: list[dict], sdn: list[dict]) -> dict:
    checks = [check_limit(payment), check_sanctions(payment, sdn),
              check_duplicate(payment, payments), check_beneficiary(payment)]
    cleared = all(c["passed"] for c in checks)
    return {
        "payment_id": payment.get("id"),
        "rail": payment.get("rail"),
        "amount": payment.get("amount"),
        "currency": payment.get("currency"),
        "beneficiary_name": payment.get("beneficiary_name"),
        "decision": "CLEARED_FOR_REVIEW" if cleared else "HOLD",
        "checks": checks,
        "release_note": (
            "Cleared for HUMAN review. FinGuard cannot release this payment; "
            "a human approver must release it (see the release-packet skill)."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Screen an outbound payment (read-only).")
    ap.add_argument("--queue", required=True, help="ISO 20022 pain.001 JSON")
    ap.add_argument("--sanctions", required=True, help="OFAC SDN snapshot JSON")
    ap.add_argument("--id", help="payment EndToEndId to screen; omit to screen all")
    args = ap.parse_args()

    payments = parse_iso20022(load_json(args.queue))
    sdn = load_sanctions(args.sanctions)

    if args.id:
        payment = next((p for p in payments if p.get("id") == args.id), None)
        if payment is None:
            print(json.dumps({"error": f"payment id '{args.id}' not found"}, indent=2))
            return 1
        print(json.dumps(screen(payment, payments, sdn), indent=2))
    else:
        results = [screen(p, payments, sdn) for p in payments]
        print(json.dumps({"sanctions_source": "OFAC SDN (curated public-data fixture)",
                          "screened": len(results), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
