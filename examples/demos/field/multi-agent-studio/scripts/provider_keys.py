# SPDX-License-Identifier: Apache-2.0

"""Install-local API keys, bound to the provider and destination in api.json."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

import nvidia_endpoints
import ops_common as ops


class InvalidProviderEntries(ValueError):
    """Other entries were imported; these providers were disabled."""


def parse(path):
    import runtime_settings as settings
    with path.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('api.json is too large.')
    slots = json.loads(raw)
    if not isinstance(slots, dict) or set(slots) - {'nvidia', 'openai', 'anthropic'}:
        raise ValueError('Unknown provider or invalid api.json structure.')
    result = {}
    invalid = []
    for provider, slot in slots.items():
        if not isinstance(slot, dict) or set(slot) - {'baseUrl', 'apiKey'}:
            invalid.append(provider)
            continue
        key = slot.get('apiKey', '')
        default = settings.PROVIDERS[provider]['baseUrl']
        url = slot.get('baseUrl', default)
        if provider == 'nvidia':
            valid = nvidia_endpoints.valid_config_url(url)
        else:
            valid = isinstance(url, str) and url.rstrip('/') == default
        if not valid:
            invalid.append(provider)
            continue
        if not isinstance(key, str) or len(key) > 4096 or any(not 33 <= ord(c) <= 126 for c in key):
            invalid.append(provider)
            continue
        if key or url.rstrip('/') != default:
            result[provider] = {'baseUrl': url.rstrip('/'), 'apiKey': key}
    return result, invalid


def private_path():
    return ops.home() / 'credentials' / 'providers.json'


def install(path):
    slots, invalid = parse(path)
    ops.initialize()
    target = private_path()
    target.parent.mkdir(mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=target.parent, prefix=target.name + '.', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(slots, stream)
            stream.flush()
            if os.geteuid() == 0 and os.environ.get('BAC_CONTAINER') == '1':
                os.chown(target.parent, 10001, 10001)
                os.fchown(stream.fileno(), 10001, 10001)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    if invalid:
        raise InvalidProviderEntries('Disabled invalid provider entries in api.json: ' + ', '.join(invalid))


def read():
    try:
        return json.loads(private_path().read_text())
    except FileNotFoundError:
        return {}


def public():
    return {p: {'baseUrl': value['baseUrl'], 'hasKey': bool(value['apiKey'])} for p, value in read().items()}


def route_id(provider, url):
    return 'file-' + provider + '-' + hashlib.sha256(url.encode()).hexdigest()[:24]


def resolve_route(route):
    _, provider, _ = route.split('-', 2)
    slot = read().get(provider)
    if slot and slot.get('apiKey') and route == route_id(provider, slot['baseUrl']):
        return provider, slot
    return provider, {}
