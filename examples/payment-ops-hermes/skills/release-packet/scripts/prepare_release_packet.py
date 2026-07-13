#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Prepare a human-approval release packet for a screened payment.

This NEVER releases a payment. It re-runs screening against the ISO 20022
queue and the bundled OFAC fixture; if the payment is cleared, it emits a
packet marked PENDING_HUMAN_APPROVAL for a human checker to act on from the
host. If screening returns HOLD, it refuses to build a packet.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_DIR / "payment-screening" / "scripts"))

try:
    from screen_payment import load_json, parse_iso20022, load_sanctions, screen  # type: ignore
except Exception:  # pragma: no cover
    print(json.dumps({"error": "payment-screening skill not found alongside this skill"}, indent=2))
    raise SystemExit(2)


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare a release packet (no release).")
    ap.add_argument("--queue", required=True, help="ISO 20022 pain.001 JSON")
    ap.add_argument("--sanctions", required=True, help="OFAC SDN snapshot JSON")
    ap.add_argument("--id", required=True, help="payment EndToEndId")
    ap.add_argument("--maker", default="unknown", help="operator preparing the packet")
    args = ap.parse_args()

    payments = parse_iso20022(load_json(args.queue))
    sdn = load_sanctions(args.sanctions)
    payment = next((p for p in payments if p.get("id") == args.id), None)
    if payment is None:
        print(json.dumps({"error": f"payment id '{args.id}' not found"}, indent=2))
        return 1

    result = screen(payment, payments, sdn)
    if result["decision"] != "CLEARED_FOR_REVIEW":
        print(json.dumps({
            "error": "refusing to prepare a release packet",
            "reason": f"payment {args.id} screened as {result['decision']}",
            "screening": result,
        }, indent=2))
        return 1

    packet = {
        "packet_type": "release_request",
        "status": "PENDING_HUMAN_APPROVAL",
        "payment": payment,
        "screening": result,
        "maker": args.maker,
        "checker": None,
        "released": False,
        "note": (
            "Prepared by FinGuard (maker). FinGuard cannot release this payment "
            "— it cannot reach payments-rail.internal. A human checker must run "
            "scripts/approve_release.py on the host to release."
        ),
    }
    print(json.dumps(packet, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
