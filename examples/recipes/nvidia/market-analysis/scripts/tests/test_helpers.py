#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Offline test of the Q1 to Q4 helper scripts against the bundled data. No network.

  python3 scripts/tests/test_helpers.py        (needs pandas, numpy and networkx: use the analysis venv)

Asserts the ground-truth numbers the helpers must reproduce, and that the ACCELERATE_ENGINE receipt is copied into the JSON.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

UTIL = Path(__file__).resolve().parents[2] / 'skills' / 'market-analysis' / 'utilities'
RECEIPT = {'device': 'cpu', 'host_gpu_usable': False, 'settings_gpu': 'auto', 'configured_libraries': {}}


def run(name, *args):
    env = {**os.environ, 'ACCELERATE_ENGINE': json.dumps(RECEIPT)}
    env.pop('AUTO_ONTOLOGY_API_TOKEN', None)
    with tempfile.TemporaryDirectory() as scratch:  # q6_review.py writes work/q6_answer.md into the working directory
        done = subprocess.run([sys.executable, '-I', str(UTIL / name), *args], env=env, capture_output=True, text=True, cwd=scratch)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out['engine_receipt'] == RECEIPT, 'engine receipt not copied'
    return out


def test_blocked_without_receipt():
    env = {k: v for k, v in os.environ.items() if k != 'ACCELERATE_ENGINE'}
    done = subprocess.run([sys.executable, '-I', str(UTIL / 'q3_unusual.py')], env=env, capture_output=True, text=True)
    assert done.returncode != 0 and 'blocked:' in done.stderr and not done.stdout


def close(got, want, tol=5e-5):
    assert abs(got - want) <= tol, f'{got} != {want}'


def test_gpu_off_refused():
    env = {**os.environ, 'ACCELERATE_GPU': 'off'}
    done = subprocess.run([sys.executable, '-I', str(UTIL / 'accelerate.py'), 'run', str(UTIL / 'q3_unusual.py')], env=env,
                          capture_output=True, text=True)
    assert done.returncode != 0 and 'ACCELERATE_GPU=off is not accepted' in done.stderr, done.stderr


def test_q1():
    out = run('q1_inventory.py')  # no token: Auto Ontology is asked anyway and must come back blocked, not skipped
    assert out['auto_ontology']['status'] == 'blocked' and 'AUTO_ONTOLOGY_API_TOKEN' in out['auto_ontology']['message'], out['auto_ontology']
    assert run('q1_inventory.py', '--no-ontology')['auto_ontology'] is None
    assert out['auto_ontology']['trace_markdown'].startswith('**Auto Ontology SQL:** none.'), out['auto_ontology']
    assert out['issuer_count'] == 36 and out['tables']['daily_prices'] == 5976
    c = out['checks']
    assert c['news_after_as_of_close'] == 0 and c['price_rows_after_as_of'] == 0 and c['duplicate_price_keys'] == 0
    assert c['latest_news_published_at'] == '2026-08-31T18:21:00Z'
    med = {k.split(',')[0].split(' ')[0]: v['median_20_session_return'] for k, v in out['sector_median_20_session_return'].items()}
    for sector, want in {'Mining': -0.1544, 'Services': -0.0223, 'Finance': -0.0339, 'Manufacturing': 0.0567, 'Retail': 0.1178,
                         'Transportation': 0.0772}.items():
        close(med[sector], want)


def test_q1_retries_no_sql():
    sys.path.insert(0, str(UTIL))
    import q1_inventory as q1
    calls = []

    def script(*results):
        it = iter(results)
        def fake(timeout):
            calls.append(timeout)
            return {"status": next(it)}
        return fake

    q1.ask_ontology_once = script('no_sql', 'no_sql', 'answered')
    got = q1.ask_ontology()
    assert got['status'] == 'answered' and got['attempts'] == 3 and got['trace_markdown'].endswith('(3 attempts)'), (got, calls)
    calls.clear(); q1.ask_ontology_once = script('no_sql', 'no_sql', 'no_sql', 'answered')
    got = q1.ask_ontology()
    assert got["status"] == "no_sql" and got["attempts"] == 3  # stops at MAX_ATTEMPTS
    calls.clear(); q1.ask_ontology_once = script('blocked', 'answered')
    got = q1.ask_ontology()
    assert got["status"] == "blocked" and got["attempts"] == 1  # blocked is not retried


def test_q1_status_needs_rows():
    sys.path.insert(0, str(UTIL))
    import importlib
    import q1_inventory as q1
    q1 = importlib.reload(q1)  # the retry test replaced ask_ontology_once on the cached module

    def fake(answer):
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=json.dumps(answer), stderr='')

    real = q1.subprocess.run
    try:
        q1.subprocess.run = fake({'sql': 'SELECT 1', 'answered_with_sql': False, 'rows': None})
        assert q1.ask_ontology_once(10)['status'] == 'no_rows'
        q1.subprocess.run = fake({'sql': '', 'answered_with_sql': False})
        assert q1.ask_ontology_once(10)['status'] == 'no_sql'
        q1.subprocess.run = fake({'sql': 'SELECT 1', 'answered_with_sql': True, 'rows': []})
        assert q1.ask_ontology_once(10)['status'] == 'answered'
        calls = []
        q1.ask_ontology_once = lambda timeout: (calls.append(timeout) or {'status': 'no_rows'})
        assert q1.ask_ontology()['attempts'] == 3 and len(calls) == 3  # SQL without rows is retried like no SQL
    finally:
        q1.subprocess.run = real


def test_kumo_population_uses_rows_up_to_the_anchor():
    import shutil
    sys.path.insert(0, str(UTIL))
    import kumo_predict as kp
    import pandas as pd

    def population(data):
        kp.DATA = data
        return sorted(kp.build_frames()['asset_entities']['asset_id'])

    original = kp.DATA
    try:
        base = population(original)
        assert len(base) == 12, base
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            for f in original.glob('*.csv'):
                shutil.copy(f, data / f.name)
            prices = pd.read_csv(data / 'daily_prices.csv')
            outsider = next(a for a in prices.asset_id.unique() if a not in base)
            later = (prices.asset_id == outsider) & (prices.trading_date > '2026-08-24')
            prices.loc[later, 'dollar_volume'] = 1e15  # huge, but only after the anchor
            prices.to_csv(data / 'daily_prices.csv', index=False)
            assert population(data) == base, 'rows after the anchor changed the Kumo population'
            earlier = (prices.asset_id == outsider) & (prices.trading_date <= '2026-08-24')
            prices.loc[earlier, 'dollar_volume'] = 1e15  # the same change before the anchor must count
            prices.to_csv(data / 'daily_prices.csv', index=False)
            assert outsider in population(data), 'rows before the anchor did not change the Kumo population'
            # a delisted or not yet listed issuer is never selected, however liquid it was before the anchor
            assets = pd.read_csv(data / 'assets.csv')
            for column, value in (('last_session', '2026-08-20'), ('first_session', '2026-08-25')):
                shifted = assets.copy()
                shifted.loc[shifted.asset_id == outsider, column] = value
                shifted.to_csv(data / 'assets.csv', index=False)
                assert outsider not in population(data), f'an issuer with {column}={value} was selected'
            assets.to_csv(data / 'assets.csv', index=False)
            # ties are broken by asset_id, ascending
            prices = pd.read_csv(data / 'daily_prices.csv')
            listed = assets[(assets.first_session <= '2026-08-24') & (assets.last_session >= '2026-08-24')].asset_id
            others = sorted(a for a in listed if a not in base)[:3]
            tops = sorted(base)[:10]
            before = prices.trading_date <= '2026-08-24'
            prices.loc[before & prices.asset_id.isin(tops), 'dollar_volume'] = 2e15
            prices.loc[before & prices.asset_id.isin(others), 'dollar_volume'] = 1e15  # three tied for two places
            prices.to_csv(data / 'daily_prices.csv', index=False)
            assert population(data) == sorted(tops + others[:2]), 'ties were not broken by ascending asset_id'
    finally:
        kp.DATA = original


def test_q2():
    out = run('q2_leaders.py')
    rows = {r['asset_id']: r for r in out['ranking_strongest_first']}
    assert len(rows) == 12 and out['ranking_strongest_first'][0]['asset_id'] == 'PEAX'
    assert out['ranking_strongest_first'][-1]['asset_id'] == 'CLOS'
    for asset, ret in {'PEAX': 0.357, 'GIST': 0.2695, 'GIOR': 0.2453, 'CLAE': -0.1623, 'CLOS': -0.2167}.items():
        close(rows[asset]['return_20_sessions'], ret)
    close(rows['PEAX']['daily_volatility'], 0.0275)
    close(rows['CLOS']['daily_volatility'], 0.0367)
    assert all(r['window_sessions'] == 20 and r['window_last'] == '2026-08-31' and r['window_first'] == '2026-08-04' for r in rows.values())
    t = out['news_label_table_top12_issuers']
    assert [t[k]['items_with_forward_return'] for k in ('positive', 'neutral', 'negative')] == [123, 87, 85]
    close(t['negative']['mean_5_session_forward_return'], 0.0110)
    close(t['neutral']['mean_5_session_forward_return'], 0.0203)
    close(t['positive']['mean_5_session_forward_return'], 0.0196)


def test_q3():
    out = run('q3_unusual.py')
    top = out['top_ten']
    assert out['issuers'] == 36 and len(top) == 10
    assert [(r['asset_id'], r['trading_date']) for r in top[:5]] == [
        ('FLON', '2026-08-13'), ('KASI', '2026-08-26'), ('FLON', '2026-07-27'), ('PEAX', '2026-08-25'), ('TISL', '2026-08-18')]
    close(top[0]['score'], 32.14, 0.005)
    assert top[0]['dominant_feature'] == 'volume' and top[0]['same_day_news']
    assert len({r['asset_id'] for r in top}) < 10, 'must not be one row per issuer'


def test_q6():
    out = run('q6_review.py')
    assert out['status'] == 'PROPOSED_FOR_REVIEW' and len(out['table_12_issuers']) == 12
    first = out['review_first']
    assert [r['asset_id'] for r in first][:2] == ['KASI', 'PEAX'], first
    kasi = next(t for t in out['table_12_issuers'] if t['asset_id'] == 'KASI')
    close(kasi['return_20_sessions'], -0.1209, 5e-4)
    assert kasi['pagerank_rank'] == 5 and kasi['unusual_sessions_in_top_ten'][0]['trading_date'] == '2026-08-26'
    assert all(r['reasons_to_look'] for r in first)
    assert 'KASI' in out['answer_block_markdown'] and all(x in out['answer_block_markdown'] for r in first for x in r['reasons_to_look'])


def test_cite_ready_deadline():
    env = {k: v for k, v in os.environ.items() if k != 'AUTO_ONTOLOGY_API_TOKEN'}
    done = subprocess.run([sys.executable, '-I', str(UTIL / 'retrieve.py'), '--method', 'bm25', '--query',
                           'deadline to file a Form 8-K Item 1.05 report', '--top', '3'], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    ready = [line for p in json.loads(done.stdout)['passages'] for line in p['cite_ready']]
    want = ('A report pursuant to Item 1.05 is to be filed within four business days after the registrant determines that it '
            'has experienced a material cybersecurity incident. [form-8k-item-1-05.md, chunk 0]')
    assert want in ready, ready[:3]
    assert not any(line.startswith(('#', 'Source:')) or '**' in line for line in ready)
    blocks = [p['quote_block'] for p in json.loads(done.stdout)['passages']]
    assert '> ' + want in '\n'.join(blocks), blocks[:1]


def test_q4():
    out = run('q4_peers.py')
    pairs = out['pairs_by_abs_correlation']
    assert out['pair_count'] == 27 and len({p['pair'] for p in pairs}) == 27
    assert [p['pair'] for p in pairs[:5]] == ['TARI-THAE', 'PRAL-STON', 'CHEA-HARE', 'FIOR-THOM', 'LEAN-SIOS']
    for p, want in zip(pairs[:5], (0.6763, 0.6121, 0.4478, 0.4428, 0.4192)):
        close(p['abs_correlation'], want)
    assert [p['abs_correlation'] for p in pairs] == sorted((p['abs_correlation'] for p in pairs), reverse=True)
    md = out['pairs_table_markdown'].splitlines()
    assert len(md) == 2 + 27 and md[2].startswith('| 1 | TARI-THAE | +0.6763 |'), md[:3]
    assert len(out['pagerank_top10_table_markdown'].splitlines()) == 12
    pr = out['pagerank']
    assert [r['asset_id'] for r in pr[:6]] == ['KOUN', 'STIO', 'VENS', 'NEMP', 'KASI', 'SHUI']
    for r, want in zip(pr[:6], (0.0409, 0.0388, 0.0358, 0.0350, 0.0332, 0.0330)):
        close(r['pagerank'], want)


if __name__ == '__main__':
    for fn in (test_blocked_without_receipt, test_gpu_off_refused, test_q1, test_q1_retries_no_sql, test_q1_status_needs_rows, test_kumo_population_uses_rows_up_to_the_anchor, test_q2, test_q3, test_q4, test_q6, test_cite_ready_deadline):
        fn()
        print(f'ok {fn.__name__}')
