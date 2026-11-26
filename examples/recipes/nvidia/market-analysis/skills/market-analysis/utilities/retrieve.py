#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Retrieve citation-ready policy passages from data/documents/. Standard library only.

  python3 utilities/retrieve.py --query "..." [--top 5] [--candidates 20] [--method nemotron|bm25] [--output FILE]

nemotron (default)  Embeds the chunks and the query with Nemotron embed, keeps the closest chunks by cosine similarity, then
                    reorders them with Nemotron rerank. Hosted calls go through the sandbox egress proxy, which replaces the
                    credential placeholders in NVIDIA_INFERENCE_API_KEY (embed, integrate.api.nvidia.com) and
                    NVIDIA_AI_API_KEY (rerank, ai.api.nvidia.com); the real key is never in the sandbox.
bm25                Offline lexical ranking, for comparison. It is never used automatically: the output names the method.

A failed hosted call exits 1 with "blocked" and nothing is substituted. The policy-evidence answer is then reported as blocked.
JSON goes to stdout (and to --output when given): the method, models, query, and each passage with its ready-made `cite` tag,
document, chunk, scores and text, so an answer can cite exactly what was retrieved. Chunk embeddings are cached in a private per-user directory under the temp directory.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

DOCUMENTS = Path(__file__).resolve().parent.parent / 'data' / 'documents'
EMBED = {'model': 'nvidia/nemotron-3.5-embed-1b', 'url': 'https://integrate.api.nvidia.com/v1/embeddings',
         'key_env': 'NVIDIA_INFERENCE_API_KEY'}
RERANK = {'model': 'nvidia/nemotron-3.5-rerank-8b',
          'url': 'https://ai.api.nvidia.com/v1/retrieval/nvidia/nemotron-3.5-rerank-8b/reranking',
          'key_env': 'NVIDIA_AI_API_KEY', 'fallback_key_env': 'NVIDIA_INFERENCE_API_KEY'}
MAX_CHARS = 1500
ATTEMPTS = 3  # the hosted embedder answered some multi-input batches with HTTP 500, so inputs go one per request


def chunks():
    out = []
    for path in sorted(DOCUMENTS.glob('*.md')):
        buffer, number = '', 0
        for paragraph in path.read_text(encoding='utf-8').split('\n\n'):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if buffer and len(buffer) + len(paragraph) > MAX_CHARS:
                out.append({'document': path.name, 'chunk': number, 'text': buffer})
                number, buffer = number + 1, ''
            buffer = (buffer + '\n\n' + paragraph).strip()
            while len(buffer) > MAX_CHARS:  # one paragraph longer than the limit
                out.append({'document': path.name, 'chunk': number, 'text': buffer[:MAX_CHARS]})
                number, buffer = number + 1, buffer[MAX_CHARS:]
        if buffer:
            out.append({'document': path.name, 'chunk': number, 'text': buffer})
    return out


def credential(config):
    """The key for one endpoint. A sandbox holds placeholders bound to a single host each, so the rerank host needs its own
    variable; the inference key is a fallback only when it is a raw key, which is the case outside a sandbox."""
    key = os.environ.get(config['key_env'])
    if key:
        return key
    other = os.environ.get(config.get('fallback_key_env', ''), '')
    if other and not other.startswith('openshell:resolve:'):
        return other
    hint = ' (restart the sandbox after attaching the provider: nemoclaw <name> stop, then start)' if other else ''
    raise RuntimeError(f"{config['key_env']} is not set{hint}")


def cite(part):
    return f"[{part['document']}, chunk {part['chunk']}]"


def cite_ready(part):
    """Each prose paragraph of the chunk (headings and the source line dropped) with the passage's cite tag after it, plain
    text, so an answer can paste one verbatim: the quote and its tag cannot drift apart."""
    out = []
    for block in part['text'].split('\n\n'):
        block = ' '.join(block.split())
        if block and not block.startswith(('#', 'Source:')):
            out.append(f"{block} {cite(part)}")
    return out


def quote_block(part):
    """The cite_ready lines as one Markdown block quote, to paste as is (one `> ` line per paragraph)."""
    return '\n>\n'.join(f'> {line}' for line in cite_ready(part))


def post(config, body):
    key = credential(config)
    request = urllib.request.Request(config['url'], json.dumps(body).encode(), {
        'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def embed_one(text, input_type):
    for attempt in range(ATTEMPTS):
        try:
            result = post(EMBED, {'model': EMBED['model'], 'input': [text], 'input_type': input_type,
                                  'encoding_format': 'float', 'truncate': 'END'})
            return result['data'][0]['embedding']
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == ATTEMPTS - 1:
                raise
            time.sleep(2)


def cache_dir():
    """A private per-user directory (mode 700, owned by us) so another local user cannot plant or read vectors."""
    path = Path(tempfile.gettempdir()) / f'ma-embed-cache-{os.getuid()}'
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError(f'{path} is not a private directory')
    return path


def valid_vectors(vectors, count):
    return (isinstance(vectors, list) and len(vectors) == count
            and all(isinstance(v, list) and v and len({len(w) for w in vectors}) == 1
                    and all(isinstance(x, (int, float)) for x in v) for v in vectors))


def cached_vectors(parts):
    digest = hashlib.sha256(json.dumps([EMBED['model']] + [p['text'] for p in parts]).encode()).hexdigest()[:16]
    try:
        path = cache_dir() / f'{digest}.json'
    except OSError:
        path = None  # no safe cache: embed every time rather than trust a shared file
    if path is not None and path.exists():
        try:
            vectors = json.loads(path.read_text(encoding='utf-8'))
            if valid_vectors(vectors, len(parts)):
                return vectors, True
        except (ValueError, OSError):
            pass  # a damaged cache is rebuilt, never trusted
    vectors = [embed_one(p['text'], 'passage') for p in parts]
    if path is not None:
        try:
            temporary = path.with_suffix(f'.{os.getpid()}.tmp')
            temporary.write_text(json.dumps(vectors), encoding='utf-8')
            os.replace(temporary, path)  # atomic, so a reader never sees half a file
        except OSError:
            pass  # a cache that cannot be written only costs time
    return vectors, False


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def rerank_order(response, count):
    """The reranker's ordering as [(index, score)], best first."""
    items = response.get('results') or response.get('rankings') or response.get('data') or []
    scored = [(item['index'], item.get('relevance_score', item.get('logit', item.get('score')))) for item in items]
    if not scored or any(i not in range(count) or s is None for i, s in scored):
        raise ValueError('unrecognized rerank response')
    return sorted(scored, key=lambda pair: -pair[1])


def nemotron(query, top, candidates):
    parts = chunks()
    vectors, cached = cached_vectors(parts)
    query_vector = embed_one(query, 'query')
    nearest = sorted(range(len(parts)), key=lambda i: -cosine(query_vector, vectors[i]))[:candidates]
    result = post(RERANK, {'model': RERANK['model'], 'query': {'text': query},
                           'passages': [{'text': parts[i]['text']} for i in nearest]})
    order = rerank_order(result, len(nearest))[:top]
    return {'method': 'nemotron_embed_rerank', 'embed_model': EMBED['model'], 'rerank_model': RERANK['model'],
            'query': query, 'chunks_indexed': len(parts), 'embeddings_cached': cached, 'candidates': len(nearest),
            'passages': [{'rank': r + 1, 'cite': cite(parts[nearest[i]]),
                          'document': parts[nearest[i]]['document'], 'chunk': parts[nearest[i]]['chunk'],
                          'rerank_score': score, 'embed_similarity': round(cosine(query_vector, vectors[nearest[i]]), 6),
                          'text': parts[nearest[i]]['text'],
                          'cite_ready': cite_ready(parts[nearest[i]]),
                          'quote_block': quote_block(parts[nearest[i]])} for r, (i, score) in enumerate(order)]}


def tokens(text):
    return re.findall(r'[a-z0-9]+', text.lower())


def bm25(query, top, k1=1.5, b=0.75):
    parts = chunks()
    docs = [tokens(p['text']) for p in parts]
    average = sum(len(d) for d in docs) / len(docs)
    frequency = Counter(t for d in docs for t in set(d))
    scores = []
    for i, d in enumerate(docs):
        counts = Counter(d)
        score = 0.0
        for term in set(tokens(query)):
            if term in counts:
                idf = math.log(1 + (len(docs) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                score += idf * counts[term] * (k1 + 1) / (counts[term] + k1 * (1 - b + b * len(d) / average))
        scores.append(score)
    order = sorted(range(len(parts)), key=lambda i: -scores[i])[:top]
    return {'method': 'bm25_offline', 'query': query, 'chunks_indexed': len(parts),
            'passages': [{'rank': r + 1, 'cite': cite(parts[i]),
                          'document': parts[i]['document'], 'chunk': parts[i]['chunk'],
                          'bm25_score': round(scores[i], 4), 'text': parts[i]['text'],
                          'cite_ready': cite_ready(parts[i]), 'quote_block': quote_block(parts[i])} for r, i in enumerate(order)]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--query', required=True)
    ap.add_argument('--top', type=int, default=5)
    ap.add_argument('--candidates', type=int, default=20)
    ap.add_argument('--method', choices=['nemotron', 'bm25'], default='nemotron')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    try:
        result = bm25(args.query, args.top) if args.method == 'bm25' else nemotron(args.query, args.top, args.candidates)
    except Exception as exc:
        ap.exit(1, f'blocked: retrieval not performed ({type(exc).__name__}: {exc}); nothing was substituted. '
                   'Report the policy-evidence answer as blocked.\n')
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    sys.stdout.write(text)


if __name__ == '__main__':
    main()
