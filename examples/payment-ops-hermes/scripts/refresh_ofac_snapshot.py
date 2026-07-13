#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Build a dated, normalized snapshot of the OFAC SDN list for the demo.

This is a HOST/developer tool, not something the sandboxed agent runs. It
fetches the public OFAC Specially Designated Nationals (SDN) list and writes
a compact JSON snapshot the payment screener reads offline at the booth.

OFAC data is published by the U.S. Department of the Treasury and is in the
public domain. Source:
  https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV

Usage:
  python3 scripts/refresh_ofac_snapshot.py --as-of 2026-06-08
  python3 scripts/refresh_ofac_snapshot.py --from-file /tmp/ofac_sdn.csv --as-of 2026-06-08
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

SDN_CSV_URL = (
    "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
)
DEFAULT_OUT = (
    Path(__file__).resolve().parents[1]
    / ".tmp" / "ofac-sdn-snapshot.json"
)
# Legacy SDN.csv has no header row. Column order is fixed by OFAC.
COLUMNS = [
    "ent_num", "name", "type", "program", "title", "call_sign",
    "vessel_type", "tonnage", "grt", "vessel_flag", "vessel_owner", "remarks",
]


def clean(value: str | None) -> str | None:
    """OFAC uses '-0-' for null; normalize to None and strip whitespace."""
    if value is None:
        return None
    v = value.strip()
    return None if v in ("", "-0-") else v


def fetch_csv(from_file: str | None) -> str:
    if from_file:
        return Path(from_file).read_text(encoding="utf-8", errors="replace")
    req = urllib.request.Request(SDN_CSV_URL, headers={"User-Agent": "payment-ops-hermes demo"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="replace")


def normalize(raw_csv: str) -> list[dict]:
    out: list[dict] = []
    reader = csv.reader(io.StringIO(raw_csv))
    for row in reader:
        if not row or len(row) < 4:
            continue
        rec = dict(zip(COLUMNS, row))
        name = clean(rec.get("name"))
        if not name:
            continue
        sdn_type = clean(rec.get("type")) or "entity"
        out.append({
            "ent_num": clean(rec.get("ent_num")),
            "name": name,
            "type": sdn_type.lower(),
            "programs": clean(rec.get("program")),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a normalized OFAC SDN snapshot.")
    ap.add_argument("--from-file", help="use a local SDN.CSV instead of fetching")
    ap.add_argument("--as-of", required=True, help="snapshot date (YYYY-MM-DD)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output JSON path")
    args = ap.parse_args()

    entries = normalize(fetch_csv(args.from_file))
    snapshot = {
        "source": "OFAC Specially Designated Nationals (SDN) List",
        "source_url": SDN_CSV_URL,
        "retrieved": args.as_of,
        "license": "U.S. Government work, public domain",
        "record_count": len(entries),
        "note": (
            "Developer-generated full snapshot for local evaluation only. "
            "It is ignored by Git and must not be committed or used for production screening."
        ),
        "entries": entries,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(entries):,} SDN entries to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
