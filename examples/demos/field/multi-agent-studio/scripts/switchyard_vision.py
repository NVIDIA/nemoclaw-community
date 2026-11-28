# SPDX-License-Identifier: Apache-2.0

"""Confirm image input support without sending a user's image to a probe.

NVIDIA's catalog currently omits modalities. Unknown models receive one tiny
synthetic-image request, cached per endpoint, credential and model. A failed
connection is unknown, never proof that a model is text-only.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import struct
import threading
import time
import zlib

_lock = threading.Lock()
_cache = {}
_pending = {}
PROBE_TIMEOUT = 12
CACHE_SECONDS = 900


class ImageRoutingError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def catalog_support(row):
    if not isinstance(row, dict):return None
    if type(row.get('supports_vision')) is bool:return row['supports_vision']
    modalities = row.get('input_modalities')
    if isinstance(modalities, list) and modalities and all(isinstance(m, str) for m in modalities):
        return 'image' in {m.lower() for m in modalities}
    return None


def probe_image():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 32, 32, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress((b'\0' + b'\xff\0\0' * 32) * 32)) + chunk(b'IEND', b''))
    return 'data:image/png;base64,' + base64.b64encode(png).decode()


def _probe(model, profile):
    import runtime_settings as settings
    payload = {'model': model, 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'Name the color of this square in one word.'},
        {'type': 'image_url', 'image_url': {'url': probe_image()}}]}], 'max_tokens': 32}
    try:
        result = settings.request('nvidia', profile, '/chat/completions', payload, timeout=PROBE_TIMEOUT)
        if isinstance(result, dict) and any(isinstance(c, dict) and isinstance(c.get('message'), dict)
                                           for c in result.get('choices', [])):
            return True
    except Exception as error:
        # Only an explicit modality rejection establishes unsupported input.
        # Rate limits, authentication, timeouts and other 400s remain unknown.
        if getattr(error, 'upstream_status', None) in (400, 422) and re.search(
                r'(?:does not support|unsupported|not supported)[^.\n]{0,100}(?:image|vision)'
                r'|(?:image|vision)[^.\n]{0,100}(?:not supported|unsupported|only supported)'
                r'|only supports? text|not a multimodal model', str(error), re.I):
            return False
    return None


def supports_image(model, profile, row=None):
    advertised = catalog_support(row)
    if advertised is not None:return advertised
    key = hashlib.sha256(json.dumps([profile.get('baseUrl'), profile.get('apiKey'), model]).encode()).hexdigest()
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:return cached[1]
        event = _pending.get(key)
        owner = event is None
        if owner:event = _pending[key] = threading.Event()
    if not owner:
        event.wait(PROBE_TIMEOUT + 1)
        with _lock:return _cache.get(key, (0, None))[1]
    result = None
    try:
        result = _probe(model, profile)
        return result
    finally:
        with _lock:
            if len(_cache) >= 256:
                for old in sorted(_cache, key=lambda k: _cache[k][0])[:64]:_cache.pop(old, None)
            _cache[key] = (time.monotonic() + (CACHE_SECONDS if result is not None else 5), result)
            _pending.pop(key, None)
            event.set()


def select_target(models, profile=None, rows=None):
    import model_connections
    profile = profile if profile is not None else model_connections.profile('api', discovery=False)
    if rows is None:rows = model_connections.status('api').get('models', [])
    by_id = {row['id']: row for row in rows if isinstance(row, dict) and isinstance(row.get('id'), str)}
    ids = list(dict.fromkeys(models[role] for role in ('capable', 'efficient')))
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='image-support') as pool:
        checks = list(pool.map(lambda model: supports_image(model, profile, by_id.get(model)), ids))
    supported = dict(zip(ids, checks))
    # Both support images: retain the capable preference. The classifier never
    # receives image content, even if its own model happens to support vision.
    for role in ('capable', 'efficient'):
        if supported[models[role]] is True:return role
    if any(value is None for value in checks):
        raise ImageRoutingError('Image support could not be verified for the selected routing models. Try again or choose an image-capable model in Settings.', 503)
    raise ImageRoutingError('Neither selected answer model supports image input. Choose an image-capable Efficient or Capable model in Settings.')
