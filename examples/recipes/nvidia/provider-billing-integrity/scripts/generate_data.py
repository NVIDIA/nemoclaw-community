#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Generate the synthetic provider-billing dataset in data/ (deterministic, seed 7). Standard library only.

  python3 scripts/generate_data.py

Every name, id and amount is synthetic. Planted structure (the answers the tasks check):
  - Ring A: six providers (P001-P006) share two practice addresses, one bank account and one owner, and upcode:
    most of their office visits are the top-level code 99215, at far above-peer claim volume.
  - Decoy 1: a three-provider group practice (P010-P012) shares an address and bank account but bills like its peers.
  - Decoy 2: P020 is a legitimate high-volume specialist (many claims, normal code mix) with no shared entity.
  - Decoy 3: P030 and P031 share only an address (a medical building); different banks and owners.
Audit findings (the Kumo label) are dated across the whole period; the anchor is 2026-06-30 and the prediction horizon
is 90 days. Ring A has a prior finding before the anchor on two providers and later findings on four more.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / 'skills' / 'provider-billing-integrity' / 'data'
rng = random.Random(7)
START, END = date(2025, 7, 1), date(2026, 9, 30)
STATES = ['TX', 'FL', 'CA', 'OH', 'NY']
SPECIALTIES = ['internal_medicine', 'family_medicine', 'cardiology', 'physical_therapy']
# code, description, typical paid USD
CODES = {'99213': ('Office visit, level 3', 92), '99214': ('Office visit, level 4', 130), '99215': ('Office visit, level 5', 180),
         '97110': ('Therapeutic exercise', 45), '93000': ('Electrocardiogram', 28)}


def write(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / name, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    providers, addresses, banks = [], {}, {}
    ring = [f'P{i:03d}' for i in range(1, 7)]
    group = ['P010', 'P011', 'P012']
    for i in range(1, 81):
        pid = f'P{i:03d}'
        spec = 'internal_medicine' if pid in ring + group else rng.choice(SPECIALTIES)
        addr, bank, owner = f'A{i:03d}', f'B{i:03d}', f'O{i:03d}'
        if pid in ring:
            addr, bank, owner = ('A901' if i <= 3 else 'A902'), 'B901', 'O901'
        elif pid in group:
            addr, bank = 'A910', 'B910'
        elif pid in ('P030', 'P031'):
            addr = 'A930'
        state = rng.choice(STATES)
        addresses.setdefault(addr, {'address_id': addr, 'street': f'{100 + len(addresses) * 7} Synthetic Way', 'state': state})
        banks.setdefault(bank, {'bank_account_id': bank, 'bank_name': f'Synthetic Bank {len(banks) % 5 + 1}'})
        enrolled = date(2025, 1, 1) - timedelta(days=rng.randint(30, 3000))
        if pid in ring:
            enrolled = date(2025, 4, 1) + timedelta(days=i)  # recently enrolled
        providers.append({'provider_id': pid, 'specialty': spec, 'state': addresses[addr]['state'], 'enrolled_date': enrolled.isoformat(),
                          'address_id': addr, 'bank_account_id': bank, 'owner_id': owner})
    beneficiaries = [{'beneficiary_id': f'M{i:04d}', 'age_band': rng.choice(['65-69', '70-79', '80+']), 'state': rng.choice(STATES)}
                     for i in range(1, 701)]
    claims, n = [], 0
    days = (END - START).days
    for p in providers:
        pid = p['provider_id']
        per_day = 0.12
        if pid in ring:
            per_day = 0.55
        elif pid == 'P020':
            per_day = 0.60
        count = int(days * per_day * rng.uniform(0.85, 1.15))
        for _ in range(count):
            n += 1
            if p['specialty'] == 'physical_therapy':
                code = rng.choices(['97110', '99213'], [8, 1])[0]
            elif p['specialty'] == 'cardiology':
                code = rng.choices(['93000', '99214', '99213', '99215'], [5, 3, 2, 0.2])[0]
            elif pid in ring:
                code = rng.choices(['99215', '99214', '99213'], [8, 1.5, 0.5])[0]
            else:
                code = rng.choices(['99213', '99214', '99215'], [5, 4, 0.8])[0]
            paid = round(CODES[code][1] * rng.uniform(0.9, 1.1), 2)
            claims.append({'claim_id': f'C{n:06d}', 'provider_id': pid,
                           'beneficiary_id': rng.choice(beneficiaries)['beneficiary_id'],
                           'claim_date': (START + timedelta(days=rng.randrange(days + 1))).isoformat(),
                           'procedure_code': code, 'paid_usd': paid})
    claims.sort(key=lambda c: (c['claim_date'], c['claim_id']))
    findings, n = [], 0

    def finding(pid, when, usd):
        nonlocal n
        n += 1
        findings.append({'finding_id': f'F{n:04d}', 'provider_id': pid, 'finding_date': when.isoformat(),
                         'finding_type': 'overpayment_recovery', 'recovered_usd': usd})

    for pid, when in [('P001', date(2026, 2, 12)), ('P004', date(2026, 4, 20)), ('P001', date(2026, 7, 28)), ('P002', date(2026, 8, 5)),
                      ('P003', date(2026, 8, 19)), ('P005', date(2026, 9, 2)), ('P006', date(2026, 9, 14))]:
        finding(pid, when, rng.randrange(8000, 40000, 100))
    for pid in ['P012', 'P041', 'P057', 'P066']:  # small background findings; none on P020, so the decoy stays clean
        finding(pid, date(2025, 11, 1) + timedelta(days=rng.randrange(0, 300)), rng.randrange(500, 3000, 50))
    findings.sort(key=lambda f: f['finding_date'])
    write('providers.csv', providers)
    write('addresses.csv', list(addresses.values()))
    write('bank_accounts.csv', list(banks.values()))
    write('beneficiaries.csv', beneficiaries)
    write('claims.csv', claims)
    write('audit_findings.csv', findings)
    print({'providers': len(providers), 'claims': len(claims), 'findings': len(findings)})


if __name__ == '__main__':
    main()
