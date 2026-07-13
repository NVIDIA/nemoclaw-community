#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Offline smoke test: screen the bundled queue and assert expected outcomes.

Runs entirely on the host with no sandbox or network. Verifies the screener
fires each control correctly against the ISO 20022 queue and the bundled OFAC
snapshot. Exit code is non-zero if any expectation fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "skills" / "payment-screening" / "data"
sys.path.insert(0, str(ROOT / "skills" / "payment-screening" / "scripts"))

from screen_payment import load_json, parse_iso20022, load_sanctions, screen  # type: ignore

EXPECTED = {
    "WIRE-1007": ("CLEARED_FOR_REVIEW", []),
    "WIRE-1008": ("HOLD", ["limit"]),
    "ACH-2003": ("HOLD", ["sanctions"]),
    "ACH-2004": ("HOLD", ["beneficiary"]),
    "WIRE-1011": ("HOLD", ["duplicate"]),
    "WIRE-1012": ("HOLD", ["duplicate"]),
}


def main() -> int:
    payments = parse_iso20022(load_json(str(DATA / "payment-queue.json")))
    sdn = load_sanctions(str(DATA / "ofac-sdn-fixture.json"))
    failures = 0
    for p in payments:
        result = screen(p, payments, sdn)
        fired = sorted(c["name"] for c in result["checks"] if not c["passed"])
        exp_decision, exp_fired = EXPECTED.get(p["id"], (None, None))
        ok = result["decision"] == exp_decision and fired == sorted(exp_fired)
        flag = "ok  " if ok else "FAIL"
        print(f"  [{flag}] {p['id']:9} {result['decision']:18} holds={fired or '-'}")
        if not ok:
            failures += 1
            print(f"         expected {exp_decision} holds={exp_fired}")
    print(f"\n{len(payments) - failures}/{len(payments)} payments screened as expected.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
