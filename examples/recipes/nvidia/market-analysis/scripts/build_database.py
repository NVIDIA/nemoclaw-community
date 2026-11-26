#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Build a SQLite database from data/*.csv, the structured source a host-side Auto Ontology ingests for Question 1.

  python3 scripts/build_database.py --out /path/to/market.sqlite

Standard library only. Tables, keys and column types are declared here, so Auto Ontology sees real primary and foreign
keys instead of inferring them. The database holds exactly the CSV rows: nothing is added, and the file is not
committed (point Auto Ontology's connection string at it, e.g. sqlite:////path/to/market.sqlite).
"""
import argparse
import csv
import sqlite3
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / 'skills' / 'market-analysis' / 'data'
TABLES = {
    'assets': {'pk': 'asset_id', 'fk': {}, 'integer': {'sic_code', 'sessions', 'liquidity_rank'}, 'real': {'median_dollar_volume'}},
    'trading_sessions': {'pk': 'session_id', 'fk': {}, 'integer': {'symbols'}, 'real': set()},
    'daily_prices': {'pk': 'price_id', 'fk': {'asset_id': 'assets(asset_id)'}, 'integer': {'volume'},
                     'real': {'open', 'high', 'low', 'close', 'adjusted_close', 'dollar_volume', 'total_return_1d'}},
    'company_news': {'pk': 'news_id', 'fk': {'primary_asset_id': 'assets(asset_id)'}, 'integer': set(), 'real': set()},
    'asset_relationships': {'pk': 'relationship_id', 'fk': {'source_asset_id': 'assets(asset_id)', 'target_asset_id': 'assets(asset_id)'},
                            'integer': {'peer_rank'}, 'real': set()},
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True, help='SQLite file to create (must not exist)')
    out = ap.parse_args().out
    if out.exists():
        ap.error('Use a fresh output path')
    con = sqlite3.connect(out)
    for name, spec in TABLES.items():
        with open(DATA / f'{name}.csv', newline='') as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)

        def kind(col):
            return 'INTEGER' if col in spec['integer'] else 'REAL' if col in spec['real'] else 'TEXT'

        cols = [f'"{c}" {kind(c)}' + (' PRIMARY KEY' if c == spec['pk'] else '') for c in header]
        cols += [f'FOREIGN KEY ("{c}") REFERENCES {ref}' for c, ref in spec['fk'].items()]
        con.execute(f'CREATE TABLE "{name}" ({", ".join(cols)})')
        con.executemany(f'INSERT INTO "{name}" VALUES ({", ".join("?" for _ in header)})',
                        [[(None if r[c] == '' else (int(r[c]) if kind(c) == 'INTEGER' else float(r[c]) if kind(c) == 'REAL' else r[c]))
                          for c in header] for r in rows])
        print(f'{name}: {len(rows)} rows')
    con.commit()
    con.close()


if __name__ == '__main__':
    main()
