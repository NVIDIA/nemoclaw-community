#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Optional CUDA-X path: the rule baseline on cuDF and the related-entity links on cuGraph, checked against the CPU tool.

  python3 utilities/integrity_gpu.py scan [--as-of 2026-06-30] [--top 10]
  python3 utilities/integrity_gpu.py related P001 [--as-of 2026-06-30]
  python3 utilities/integrity_gpu.py parity [--as-of 2026-06-30] [--output FILE]

scan     the baseline of integrity_tool.py computed with cuDF (filter, groupby, peer medians on the device).
related  the related-entity cluster as connected components of a provider-to-attribute graph (provider nodes joined to address,
         bank-account and owner nodes), computed with cuGraph through the nx-cugraph backend, plus the shared entities with the
         highest betweenness centrality in the cluster: the hubs that hold it together.
parity   runs the GPU path and the CPU path (integrity_tool.py), checks that rankings, scores and clusters agree, and records the
         GPU name, library versions and timings. Exits 1 when they disagree.

Needs an NVIDIA GPU visible in the sandbox and the RAPIDS virtual environment (requirements-gpu.txt, built by scripts/install.sh
when NEMOCLAW_SANDBOX_GPU=1); this script switches to that environment by itself. There is no fallback: without a GPU or RAPIDS
it exits 1 with "blocked", and integrity_tool.py stays the CPU path. At 80 providers and about 5,800 claims the GPU is not
faster, because the sample data is far too small to outweigh the device's fixed costs; a speed-up needs a much larger
dataset, which is not tested here. A timing here is not a speed-up claim: it shows the same answers on the device.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import integrity_tool as cpu  # noqa: E402  (the stdlib CPU path, also the parity reference)

VENV = Path(os.environ.get('PBI_RAPIDS_VENV', '/sandbox/rapids-venv'))
DATA = cpu.DATA
VISITS = cpu.VISITS
LINKS = cpu.LINKS


def ensure_environment():
    """Re-run under the RAPIDS virtual environment when this interpreter has no cuDF."""
    try:
        import cudf  # noqa: F401
        return
    except ImportError:
        pass
    python = VENV / 'bin' / 'python'
    if os.environ.get('PBI_RAPIDS_REEXEC') or not python.exists():
        sys.exit(f'blocked: the RAPIDS environment is missing ({python} not found or incomplete). Re-run scripts/install.sh with '
                 'NEMOCLAW_SANDBOX_GPU=1 on a GPU sandbox. Nothing was substituted. Report the GPU path as blocked.')
    os.environ['PBI_RAPIDS_REEXEC'] = '1'
    os.execv(str(python), [str(python), *sys.argv])


def gpu_name():
    try:
        out = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True, text=True, timeout=30)
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def scan_gpu(as_of, top):
    import cudf

    providers = cudf.read_csv(DATA / 'providers.csv')
    claims = cudf.read_csv(DATA / 'claims.csv', dtype={'procedure_code': 'str'})
    claims = claims[claims['claim_date'] <= as_of]
    visits = claims[claims['procedure_code'].isin(VISITS)]
    visits['top'] = (visits['procedure_code'] == '99215').astype('float64')
    share = visits.groupby('provider_id')['top'].mean().rename('top_level_share').reset_index()
    volume = claims.groupby('provider_id').size().rename('claims').reset_index()
    frame = providers[['provider_id', 'specialty']].merge(share, how='left', on='provider_id').merge(volume, how='left', on='provider_id')
    frame['top_level_share'] = frame['top_level_share'].fillna(0.0)
    frame['claims'] = frame['claims'].fillna(0).astype('float64')
    frame['peer_volume_ratio'] = frame['claims'] / frame.groupby('specialty')['claims'].transform('median')
    frame['score'] = frame['top_level_share'] * 0.7 + (frame['peer_volume_ratio'].clip(upper=5) / 5) * 0.3
    rows = frame.sort_values(['score', 'provider_id'], ascending=[False, True]).head(top).to_pandas()
    return [{'provider_id': r.provider_id, 'specialty': r.specialty, 'claims': int(r.claims),
             'top_level_share': round(r.top_level_share, 3),
             'peer_volume_ratio': None if not math.isfinite(r.peer_volume_ratio) else round(r.peer_volume_ratio, 2),
             'score': round(r.score, 4)} for r in rows.itertuples()]


def related_gpu(provider, as_of, hubs=3):
    import cudf
    import networkx as nx

    providers = cudf.read_csv(DATA / 'providers.csv')
    providers = providers[providers['enrolled_date'] <= as_of].to_pandas()
    edges = [(row.provider_id, f'{column}:{getattr(row, column)}') for row in providers.itertuples() for column in LINKS
             if getattr(row, column) == getattr(row, column) and getattr(row, column) != '']
    graph = nx.Graph(edges)
    component = next((c for c in nx.connected_components(graph, backend='cugraph') if provider in c), None)
    if component is None:
        raise SystemExit(f'unknown provider {provider}')
    cluster = sorted(n for n in component if not any(n.startswith(f'{c}:') for c in LINKS))
    shared = sorted(n for n in component if any(n.startswith(f'{c}:') for c in LINKS) and graph.degree(n) > 1)
    sub = graph.subgraph(component)
    centrality = nx.betweenness_centrality(sub, backend='cugraph') if len(component) > 2 else {}
    ranked = sorted(((n, c) for n, c in centrality.items() if n in shared), key=lambda x: (-x[1], x[0]))[:hubs]
    return {'provider': provider, 'cluster': cluster, 'size': len(cluster), 'shared_entities': shared,
            'hub_entities': [{'entity': n, 'betweenness': round(float(c), 4)} for n, c in ranked]}


def timed(fn, *args):
    started = time.perf_counter()
    out = fn(*args)
    return out, round(time.perf_counter() - started, 3)


def parity(as_of, output):
    import cudf
    import networkx

    cpu_scan, cpu_scan_s = timed(cpu.scan, as_of, 80)
    scan_gpu(as_of, 1)  # warm the CUDA context and kernels so the timing is not dominated by start-up
    gpu_scan, gpu_scan_s = timed(scan_gpu, as_of, 80)
    cpu_scores = {r['provider_id']: r['score'] for r in cpu_scan}
    gpu_scores = {r['provider_id']: r['score'] for r in gpu_scan}
    # Every score must agree and the top ten must come in the same order; ties further down may order differently.
    scores_match = (cpu_scores.keys() == gpu_scores.keys() and all(abs(cpu_scores[k] - gpu_scores[k]) < 1e-3 for k in cpu_scores)
                    and [r['provider_id'] for r in cpu_scan[:10]] == [r['provider_id'] for r in gpu_scan[:10]])
    clusters = {}
    for pid in ('P001', 'P010', 'P020', 'P030'):
        c, c_s = timed(cpu.related, pid, as_of)
        related_gpu(pid, as_of)  # warm
        g, g_s = timed(related_gpu, pid, as_of)
        clusters[pid] = {'cpu_cluster': c['cluster'], 'gpu_cluster': g['cluster'], 'match': c['cluster'] == g['cluster'],
                         'hub_entities': g['hub_entities'], 'cpu_seconds': c_s, 'gpu_seconds': g_s}
    try:
        import nx_cugraph
        nx_cugraph_version = nx_cugraph.__version__
    except Exception:
        nx_cugraph_version = None
    result = {'as_of': as_of, 'gpu': gpu_name(), 'cudf': cudf.__version__, 'nx_cugraph': nx_cugraph_version,
              'networkx': networkx.__version__,
              'scan': {'rankings_and_scores_match': scores_match, 'cpu_seconds': cpu_scan_s, 'gpu_seconds': gpu_scan_s,
                       'top_six': [r['provider_id'] for r in gpu_scan[:6]]},
              'clusters': clusters, 'all_match': scores_match and all(v['match'] for v in clusters.values())}
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['scan', 'related', 'parity'])
    ap.add_argument('provider', nargs='?')
    ap.add_argument('--as-of', type=cpu.iso_date, default='2026-06-30')
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--output', type=Path, help='parity only: also write the receipt here')
    a = ap.parse_args()
    if a.command == 'related' and not a.provider:
        ap.error('related needs a provider id')
    try:
        if a.command == 'scan':
            out = scan_gpu(a.as_of, a.top)
        elif a.command == 'related':
            out = related_gpu(a.provider, a.as_of)
        else:
            out = parity(a.as_of, a.output)
    except SystemExit:
        raise
    except Exception as exc:  # no GPU, a driver or library mismatch, an out-of-memory device: blocked, never a CPU result
        ap.exit(1, f'blocked: the GPU path did not run ({type(exc).__name__}: {exc}); nothing was substituted. '
                   'Report the GPU result as blocked. integrity_tool.py remains the CPU path.\n')
    json.dump(out, sys.stdout, indent=2, allow_nan=False)
    print()
    return 0 if a.command != 'parity' or out['all_match'] else 1


if __name__ == '__main__':
    ensure_environment()
    sys.exit(main())
