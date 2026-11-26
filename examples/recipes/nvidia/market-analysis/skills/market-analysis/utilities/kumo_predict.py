#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Rank the 12 most liquid issuers by the probability of a positive five-session return, with NVIDIA Kumo (Question 5).

  python3 utilities/kumo_predict.py [--output FILE]
  python3 utilities/kumo_predict.py --frames-only        # build the graph tables and print their sizes; no network

Builds Kumo's relational graph from data/*.csv as it stood at the 2026-08-24 close (nothing dated after the anchor enters
any table), then asks Kumo Relational whether each issuer's return over the next five sessions is positive (the PQL below)
through the official `kumo-relational-client` package. The service is the hosted NVIDIA API Catalog model
`nvidia/kumo-relational`. THE GRAPH TABLES ARE SENT TO THAT SERVICE: the issuer, price and news rows (synthetic in this
recipe). The hosted route differs from the path the client expects, so a loopback adapter inside this process on 127.0.0.1
translates `/v1/predictions` to the hosted path and adds the credential. In a sandbox that credential is the
NVIDIA_AI_API_KEY placeholder, which the egress proxy replaces on the way to ai.api.nvidia.com; the real key is never in
the sandbox.

Needs pandas and `kumo-relational-client[relational]`, which `scripts/install.sh` installs into the analysis virtual
environment (default /sandbox/analysis-venv, override with ANALYSIS_VENV); this script re-runs itself with that interpreter
when needed. A failed call exits 1 with "blocked" and nothing is substituted: Question 5 is then answered as blocked. JSON
goes to stdout, and the full receipt (all issuers, the PQL, package version, graph sizes and fingerprint, HTTP timings) to
--output when given.
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / 'data'
VENV = Path(os.environ.get('ANALYSIS_VENV', '/sandbox/analysis-venv'))
ENDPOINT = 'https://ai.api.nvidia.com/v1/structured-data/nvidia/kumo-relational'
MODEL = 'kumo-relational'
KEY_ENV = 'NVIDIA_AI_API_KEY'
FALLBACK_KEY_ENV = 'NVIDIA_INFERENCE_API_KEY'
TIMEOUT_SECONDS = 300
DROPPED_COLUMNS = []
ANCHOR = '2026-08-24T21:00:00+00:00'
ANCHOR_DATE = '2026-08-24'
HORIZON_SESSIONS = 5
# Positive return over the five sessions after the anchor close: the sum of daily log returns over the next 7 calendar days
# (from the Monday 2026-08-24 close: the closes of 08-25 to 08-31, five sessions) is above zero, which is the same as a
# positive compound return. Training windows near a market holiday hold four sessions instead.
PQL = 'PREDICT SUM(price_events.log_return_1d, 0, 7, days) > 0 FOR EACH asset_entities.asset_id'
TABLES = {'asset_entities': {'primary_key': 'asset_id'},
          'price_events': {'primary_key': 'price_id', 'time_column': 'observed_at', 'links_to_entity': 'asset_id'},
          'news_events': {'primary_key': 'news_id', 'time_column': 'published_at', 'links_to_entity': 'asset_id'}}




def ensure_environment():
    """Re-run under the analysis virtual environment when this interpreter lacks pandas or the client."""
    try:
        import pandas  # noqa: F401
        import kumo_relational_client  # noqa: F401
        return
    except ImportError:
        pass
    python = VENV / 'bin' / 'python'
    if os.environ.get('MA_KUMO_REEXEC') or not python.exists():
        sys.exit(f'blocked: the analysis environment is missing ({python} not found or incomplete). Run scripts/install.sh. '
                 'Nothing was substituted. Report Question 5 as blocked.')
    os.environ['MA_KUMO_REEXEC'] = '1'
    os.execv(str(python), [str(python), *sys.argv])


def credential():
    key = os.environ.get(KEY_ENV)
    if key:
        return key
    other = os.environ.get(FALLBACK_KEY_ENV, '')
    if other and not other.startswith('openshell:resolve:'):
        return other  # a raw key, as outside a sandbox
    hint = ' (restart the sandbox after attaching the provider: nemoclaw <name> stop, then start)' if other else ''
    raise RuntimeError(f'{KEY_ENV} is not set{hint}')


POPULATION_SIZE = 12


def population_at_anchor(assets, prices):
    """The 12 most liquid issuers using only sessions on or before the anchor date (median daily dollar volume, ties by
    asset_id), among issuers listed on that date. assets.csv's liquidity_rank is computed through 2026-08-31, so using it
    would let rows after the anchor choose who is asked about."""
    live = assets[(assets['first_session'] <= ANCHOR_DATE) & (assets['last_session'] >= ANCHOR_DATE)]
    window = prices[prices['asset_id'].isin(live['asset_id']) & (prices['trading_date'] <= ANCHOR_DATE)]
    ranked = (window.groupby('asset_id')['dollar_volume'].median().reset_index()
              .sort_values(['dollar_volume', 'asset_id'], ascending=[False, True]))
    return ranked['asset_id'].head(POPULATION_SIZE).tolist()


def build_frames():
    """The three tables Kumo sees, as of the anchor (nothing later enters any of them)."""
    import numpy as np
    import pandas as pd

    assets = pd.read_csv(DATA / 'assets.csv')
    prices = pd.read_csv(DATA / 'daily_prices.csv', parse_dates=['trading_date'])
    news = pd.read_csv(DATA / 'company_news.csv', parse_dates=['published_at'])
    anchor = pd.Timestamp(ANCHOR)
    entities = assets[assets['asset_id'].isin(population_at_anchor(assets, prices))][
        ['asset_id', 'company_name', 'sector', 'industry', 'exchange']]
    prices = prices[prices['asset_id'].isin(entities['asset_id'])].sort_values(['asset_id', 'trading_date'], ignore_index=True)
    close = pd.Timedelta(hours=21)
    previous = prices.groupby('asset_id')['adjusted_close'].shift(1)
    prices['log_return_1d'] = np.log(prices['adjusted_close'] / previous).fillna(0.0)  # from the previous close only
    price_events = prices[prices['trading_date'] <= ANCHOR_DATE].assign(
        observed_at=lambda f: (f['trading_date'] + close).dt.tz_localize('UTC'))[
        ['price_id', 'asset_id', 'observed_at', 'adjusted_close', 'volume', 'total_return_1d', 'log_return_1d']]
    news = news[news['primary_asset_id'].isin(entities['asset_id']) & (news['published_at'] <= anchor)]
    news_events = news.rename(columns={'primary_asset_id': 'asset_id'})[
        ['news_id', 'asset_id', 'published_at', 'event_type', 'sentiment_label']]
    return {'asset_entities': entities.reset_index(drop=True), 'price_events': price_events.reset_index(drop=True),
            'news_events': news_events.reset_index(drop=True)}


def fingerprint(frames):
    digest = hashlib.sha256()
    for name in sorted(frames):
        digest.update(name.encode() + frames[name].to_csv(index=False).encode())
    return digest.hexdigest()


class _Handler(BaseHTTPRequestHandler):
    """Translate the client's deployment-local routes to the API Catalog route."""

    def log_message(self, *args):
        return

    def _send(self, status, body, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/v1/health/ready':
            self._send(200, b'{"status": "ready"}')  # synthetic: not evidence that the hosted service is ready
        elif self.path == '/v1/models':
            self._send(200, b'{"data": [{"id": "kumo-relational"}]}')
        else:
            self._send(404, b'{"detail": "unsupported loopback route"}')

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        if self.path != '/v1/predictions' or not 0 < length <= self.server.max_bytes:
            self._send(404 if self.path != '/v1/predictions' else 413, b'{"detail": "unsupported or oversized request"}')
            return
        payload = self.rfile.read(length)
        try:
            body_json = json.loads(payload)
            inference = body_json.get('inference')
            if isinstance(inference, dict) and inference.get('inference_config'):
                # The hosted NIM reserves inference_config and rejects a non-empty one, while the engine's default request
                # carries its defaults there (num_estimators 1, no shuffling). Omit it and record that in the receipt.
                del inference['inference_config']
                payload = json.dumps(body_json).encode()
                if 'dropped inference.inference_config (reserved by the hosted NIM)' not in self.server.patches:
                    self.server.patches.append('dropped inference.inference_config (reserved by the hosted NIM)')
        except ValueError:
            pass  # forward as is; the service reports its own error
        request = urllib.request.Request(self.server.hosted_url + '/predictions', payload, method='POST',
                                         headers={'Authorization': f'Bearer {self.server.api_key}', 'Accept': 'application/json',
                                                  'Content-Type': 'application/json'})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.server.timeout) as response:
                body, status, kind = response.read(), response.status, response.headers.get('Content-Type', 'application/json')
        except urllib.error.HTTPError as error:
            body, status, kind = error.read(), error.code, error.headers.get('Content-Type', 'application/json')
        except (urllib.error.URLError, OSError):
            self.server.calls.append({'status': 502})
            self._send(502, b'{"detail": "hosted Kumo transport failure"}')
            return
        self.server.calls.append({'status': status, 'seconds': round(time.monotonic() - started, 3)})
        self._send(status, body, kind)


class HostedRouteAdapter:
    """Loopback adapter for the API Catalog path and Bearer authentication; the credential stays in this process."""

    def __init__(self, api_key, hosted_url, timeout=TIMEOUT_SECONDS, max_bytes=64 * 1024 * 1024):
        parsed = urlparse(hosted_url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname:
            raise ValueError('The hosted Kumo URL must be absolute')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self.server.daemon_threads = True
        self.server.api_key, self.server.hosted_url = api_key, hosted_url.rstrip('/')
        self.server.timeout, self.server.max_bytes, self.server.calls = timeout, max_bytes, []
        self.server.patches = []

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    @property
    def calls(self):
        return self.server.calls

    @property
    def patches(self):
        return self.server.patches

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def predict(frames):
    import importlib.metadata
    import logging
    import warnings

    import pandas as pd
    from kumo_relational_client import RelationalClient, relational

    logging.disable(logging.INFO)  # keep the engine's INFO lines out of the output (its logger level alone did not)

    graph = relational.Graph.from_data(frames, edges=[], verbose=False)
    for name, table in TABLES.items():
        graph[name].primary_key = table['primary_key']
        if 'time_column' in table:
            graph[name].time_column = table['time_column']
        if 'links_to_entity' in table:
            graph.link(name, table['links_to_entity'], 'asset_entities')
    ids = sorted(frames['asset_entities']['asset_id'])
    started = time.monotonic()
    key = credential()
    os.environ['KUMO_RELATIONAL_DISABLE_SESSIONS'] = '1'  # the API Catalog serves one-shot predictions only
    # The client talks to the in-process adapter on loopback. A sandbox sets an egress proxy for everything else, and some
    # shells lack a loopback entry in no_proxy, which sends that call to the proxy and gets it denied.
    for name in ('NO_PROXY', 'no_proxy'):
        current = os.environ.get(name, '')
        if '127.0.0.1' not in current:
            os.environ[name] = f'{current},127.0.0.1,localhost' if current else '127.0.0.1,localhost'
    # The engine warns, for example, that the anchor is later than the newest row. Those warnings are facts about the data,
    # not failures, so they go into the receipt instead of stderr, where a reader could mistake them for an error.
    with warnings.catch_warnings(record=True) as caught, HostedRouteAdapter(key, ENDPOINT) as route:
        warnings.simplefilter('always')
        with RelationalClient(timeout=TIMEOUT_SECONDS, max_retries=0, url=route.url) as client:
            frame = client.relational(graph).predict(PQL, ids, anchor_time=pd.Timestamp(ANCHOR), run_mode='fast',
                                                     num_retries=0, verbose=False)
        calls = list(route.calls)
        patches = list(route.patches)
    rows = [{'asset_id': str(a), 'probability': float(p)} for a, p in zip(frame['ENTITY'], frame['TRUE_PROB'], strict=True)]
    return {'tool': 'kumo_relational', 'service': 'nvidia-api-catalog', 'endpoint': ENDPOINT, 'model': MODEL,
            'package_version': importlib.metadata.version('kumo-relational-client'), 'pql': PQL, 'anchor': ANCHOR,
            'horizon_sessions': HORIZON_SESSIONS, 'population': ids,
            'population_rule': 'the 12 issuers with the highest median daily dollar volume over sessions on or before the anchor date',
            'graph': {name: {'rows': len(f),
                             'latest': str(max(f[TABLES[name]['time_column']])) if 'time_column' in TABLES[name] else None}
                      for name, f in frames.items()},
            'graph_fingerprint': fingerprint(frames), 'columns_dropped': DROPPED_COLUMNS, 'engine_warnings': sorted({f'{w.category.__name__}: {w.message}' for w in caught}), 'adapter_request_patches': patches, 'http_calls': calls, 'elapsed_seconds': round(time.monotonic() - started, 2),
            'predictions': sorted(rows, key=lambda r: -r['probability']),
            'trace_markdown': ('**Kumo PQL** (model `%s`, kumo-relational-client %s, anchor %s, %d issuers)\n\n```\n%s\n```'
                               % (MODEL, importlib.metadata.version('kumo-relational-client'), ANCHOR, len(ids), PQL))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--output', type=Path, help='write the full receipt here')
    ap.add_argument('--frames-only', action='store_true', help='build the graph tables and print their sizes; no network')
    args = ap.parse_args()
    frames = build_frames()
    if args.frames_only:
        print(json.dumps({name: len(f) for name, f in frames.items()}))
        return 0
    try:
        result = predict(frames)
    except Exception as exc:
        ap.exit(1, f'blocked: Kumo prediction not performed ({type(exc).__name__}: {exc}); nothing was substituted. '
                   'Report Question 5 as blocked.\n')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    shown = {k: v for k, v in result.items() if k != 'predictions'}
    shown['predictions'] = [{**r, 'probability': round(r['probability'], 4)} for r in result['predictions']]
    print(json.dumps(shown, indent=2))
    return 0


if __name__ == '__main__':
    ensure_environment()
    sys.exit(main())
