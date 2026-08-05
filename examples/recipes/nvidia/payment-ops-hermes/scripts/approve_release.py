#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Human-checker release tool for the FinGuard demo — runs on the HOST.

This is the OTHER half of maker-checker. FinGuard (the maker, inside the
sandbox) prepares and screens a payment but cannot reach the rail. A human
approver runs THIS tool on the host to release a CLEARED payment. It:

  1. re-screens the payment (defence in depth — never release a HOLD),
  2. POSTs to the mock rail with the approver's identity.

The point of the demo: this step is impossible from inside the sandbox.
Only a human on the host can release.

Run:  python3 scripts/approve_release.py --id WIRE-1007 --approver "Jane Ops"
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "skills" / "payment-screening" / "data"
sys.path.insert(0, str(ROOT / "skills" / "payment-screening" / "scripts"))

from screen_payment import load_json, parse_iso20022, load_sanctions, screen  # type: ignore


def main() -> int:
    ap = argparse.ArgumentParser(description="Release a cleared payment (human checker).")
    ap.add_argument("--id", required=True, help="payment EndToEndId")
    ap.add_argument("--approver", required=True, help="name of the human approver")
    ap.add_argument("--rail-url", default="http://127.0.0.1:8780", help="mock rail base URL")
    ap.add_argument("--queue", default=str(DATA / "payment-queue.json"))
    ap.add_argument("--sanctions", default=str(DATA / "ofac-sdn-fixture.json"))
    args = ap.parse_args()

    payments = parse_iso20022(load_json(args.queue))
    sdn = load_sanctions(args.sanctions)
    payment = next((p for p in payments if p.get("id") == args.id), None)
    if payment is None:
        print(f"ERROR: payment {args.id} not found")
        return 1

    result = screen(payment, payments, sdn)
    if result["decision"] != "CLEARED_FOR_REVIEW":
        print(f"REFUSED: {args.id} screened as {result['decision']} — not releasing.")
        return 1

    body = json.dumps({"payment_id": args.id, "amount": payment["amount"],
                       "beneficiary_name": payment["beneficiary_name"]}).encode("utf-8")
    req = urllib.request.Request(f"{args.rail_url}/release", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "X-Approver": args.approver})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            out = json.loads(resp.read())
        print(f"RELEASED: {args.id} by {args.approver} → {out.get('status')}")
        return 0
    except Exception as exc:  # rail unreachable or refused
        print(f"ERROR releasing {args.id}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
