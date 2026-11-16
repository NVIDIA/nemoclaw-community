#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""CPU tools for provider-billing integrity: a rule baseline and related-entity expansion. standard library only.

  python3 utilities/integrity_tool.py scan [--as-of 2026-06-30] [--top 10]
  python3 utilities/integrity_tool.py related P001 [--as-of 2026-06-30]
  python3 utilities/integrity_tool.py cluster-exposure P001 [--as-of 2026-06-30]

scan      ranks providers by a transparent rule score: share of office visits billed at the top level (99215) and
          claim volume against the specialty peer median. It is the baseline the Kumo ranking is compared with.
related   expands one provider to everyone linked through a shared address, bank account or owner, with the reason for
          each link and the transitive closure (a link chain counts, not only direct neighbours).
cluster-exposure  paid dollars and claim counts for the related cluster, per provider and in total.
Everything is computed from data/*.csv restricted to dates on or before --as-of; the output is JSON on stdout.
"""
import argparse
import json
import sys
import csv
from datetime import date
import statistics
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / 'data'
LINKS = ['address_id', 'bank_account_id', 'owner_id']
VISITS = ['99213', '99214', '99215']


def read(name):
    with open(DATA / name, newline='') as f:
        return list(csv.DictReader(f))


def load(as_of):
    providers = read('providers.csv')
    claims = [c for c in read('claims.csv') if c['claim_date'] <= as_of]
    return providers, claims


def scan(as_of, top):
    providers, claims = load(as_of)
    volume = defaultdict(int)
    visits = defaultdict(list)
    for c in claims:
        volume[c['provider_id']] += 1
        if c['procedure_code'] in VISITS:
            visits[c['provider_id']].append(c['procedure_code'] == '99215')
    by_specialty = defaultdict(list)
    for p in providers:
        by_specialty[p['specialty']].append(volume[p['provider_id']])
    median = {s: statistics.median(v) for s, v in by_specialty.items()}
    rows = []
    for p in providers:
        pid = p['provider_id']
        v = visits[pid]
        share = sum(v) / len(v) if v else 0.0
        n = volume[pid]
        m = median[p['specialty']]
        ratio = n / m if m else (float('inf') if n else 0.0)
        score = round(share * 0.7 + (min(ratio, 5) / 5) * 0.3, 4)
        rows.append({'provider_id': pid, 'specialty': p['specialty'], 'claims': n,
                     'top_level_share': round(share, 3), 'peer_volume_ratio': None if ratio == float('inf') else round(ratio, 2),
                     'score': score})
    rows.sort(key=lambda r: (-r['score'], r['provider_id']))
    return rows[:top]


def components(providers):
    parent = {p['provider_id']: p['provider_id'] for p in providers}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    reasons = {}
    for column in LINKS:
        shared = defaultdict(list)
        for p in providers:
            if p[column]:
                shared[p[column]].append(p['provider_id'])
        for value, group in sorted(shared.items()):
            ids = sorted(group)
            for other in ids[1:]:
                parent[find(other)] = find(ids[0])
            if len(ids) > 1:
                reasons[(column, value)] = ids
    groups = {}
    for p in parent:
        groups.setdefault(find(p), []).append(p)
    return groups, reasons


def related(provider, as_of):
    providers, _ = load(as_of)
    providers = [p for p in providers if p['enrolled_date'] <= as_of]
    groups, reasons = components(providers)
    cluster = next((sorted(g) for g in groups.values() if provider in g), None)
    if cluster is None:
        raise SystemExit(f'unknown provider {provider}')
    links = [{'shared': column, 'value': value, 'providers': ids} for (column, value), ids in sorted(reasons.items())
             if set(ids) <= set(cluster)]
    return {'provider': provider, 'cluster': cluster, 'size': len(cluster), 'links': links}


def exposure(provider, as_of):
    cluster = related(provider, as_of)['cluster']
    _, claims = load(as_of)
    count = defaultdict(int)
    paid = defaultdict(float)
    for c in claims:
        if c['provider_id'] in cluster:
            count[c['provider_id']] += 1
            paid[c['provider_id']] += float(c['paid_usd'])
    per = {p: {'claims': count[p], 'paid_usd': round(paid[p], 2)} for p in sorted(count)}
    return {'cluster': cluster, 'total_claims': sum(r['claims'] for r in per.values()),
            'total_paid_usd': round(sum(r['paid_usd'] for r in per.values()), 2), 'per_provider': per}


def iso_date(text):
    """--as-of must be a real YYYY-MM-DD date: dates are compared as strings, so a loose form such as
    2026-7-1 would sort after 2026-06-30 and let later claims into every figure."""
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'{text!r} is not a YYYY-MM-DD date')
    if parsed.isoformat() != text:
        raise argparse.ArgumentTypeError(f'{text!r} is not a YYYY-MM-DD date')
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['scan', 'related', 'cluster-exposure'])
    ap.add_argument('provider', nargs='?')
    ap.add_argument('--as-of', type=iso_date, default='2026-06-30')
    ap.add_argument('--top', type=int, default=10)
    a = ap.parse_args()
    if a.command == 'scan':
        out = scan(a.as_of, a.top)
    elif not a.provider:
        ap.error(f'{a.command} needs a provider id')
    else:
        out = (related if a.command == 'related' else exposure)(a.provider, a.as_of)
    json.dump(out, sys.stdout, indent=2, allow_nan=False)
    print()


if __name__ == '__main__':
    main()
