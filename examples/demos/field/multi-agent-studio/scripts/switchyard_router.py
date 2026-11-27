# SPDX-License-Identifier: Apache-2.0

"""Switchyard model choices and local process lifecycle; no stored credentials."""
import atexit
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import re
import tempfile
import threading
import time

import nvidia_endpoints

VERSION = '0.3.0'
SUPER_VL = 'nvidia/nvidia/nemotron-3.5-super-vl'
LIGHTNING = 'nvidia/nvidia/nemotron-3.5-lightning'
# The same NIM model can have different exact IDs in different catalogs.
MODEL_IDS = {
    LIGHTNING: ('nvidia/nemotron-3.5-lightning-30b-a3b', LIGHTNING, LIGHTNING.removeprefix('nvidia/')),
    SUPER_VL: ('nvidia/nemotron-3.5-super-vl-120b-a12b', SUPER_VL, SUPER_VL.removeprefix('nvidia/')),
}
JUDGE = LIGHTNING
ANSWER_MODELS = (LIGHTNING, SUPER_VL)
MODEL = 'switchyard'
VISION_MODEL = 'switchyard-vision'
VISION_EFFICIENT_MODEL = 'switchyard-vision-efficient'
LOUNGE_MODEL = 'switchyard-lounge'
LABEL = 'Model routing (NeMo Switchyard)'
DESCRIPTION = 'Routes each task to your Efficient or Capable model.'
DEFAULT_MODELS = {'router': LIGHTNING, 'efficient': LIGHTNING, 'capable': SUPER_VL}
CUSTOM_NOTICE = 'Warning: This model combination has not been tested with this demo.'
CONFIG = Path(__file__).with_name('switchyard.toml')
_lock = threading.RLock()
_process = None
_port = None
_process_models = None
_process_base = None
_config_dir = None


def normalize_models(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_MODELS):
        raise ValueError('Choose a model for Router, Efficient and Capable.')
    if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}', v) for v in value.values()):
        raise ValueError('Choose valid model IDs from the NVIDIA catalog.')
    return {key: value[key] for key in DEFAULT_MODELS}


def saved_pools(config, previous_base):
    """Attribute an older installation's single pool to its then-configured endpoint."""
    pools = dict(config.get('switchyardPools', {}))
    if previous_base and 'switchyardModels' in config:
        pools.setdefault(previous_base.rstrip('/'), config['switchyardModels'])
    return pools


def configured_models(base_url=None):
    import model_connections
    import runtime_settings
    previous = runtime_settings.read().get('profiles', {}).get('nvidia', {}).get('baseUrl')
    pools = saved_pools(model_connections.read(), previous)
    endpoint = (base_url or previous or nvidia_endpoints.PUBLIC).rstrip('/')
    return normalize_models(pools.get(endpoint, DEFAULT_MODELS))


def resolve_catalog_models(models, ids):
    # Preserve explicit choices. Translate a known model only when its old ID
    # is absent and this endpoint advertises another exact ID for the same model.
    resolved = dict(models)
    for role, model in models.items():
        if model not in ids:
            aliases = next((group for group in MODEL_IDS.values() if model in group), ())
            resolved[role] = next((alias for alias in aliases if alias in ids), model)
    return resolved


def model_label(model):
    for family, label in ((LIGHTNING, 'Nemotron 3.5 Lightning'), (SUPER_VL, 'Nemotron 3.5 Super VL')):
        if model in MODEL_IDS[family]:
            return label
    return model.split('/')[-1]


def public_config(models=None, defaults=None):
    models = normalize_models(models) if models is not None else configured_models()
    defaults = defaults or DEFAULT_MODELS
    default = models == defaults
    return {'label': LABEL, 'description': DESCRIPTION,
            'models': list(dict.fromkeys(models[k] for k in ('efficient', 'capable'))),
            'defaults': dict(defaults), 'configuration': models,
            'defaultConfiguration': default, 'notice': '' if default else CUSTOM_NOTICE,
            'roles': [{'key': key, 'role': key.title(), 'id': model, 'label': model_label(model)} for key, model in models.items()]}


def prepare_request(payload, state, models=None, *, profile=None, rows=None):
    """Preserve media and bypass classification using a verified answer target."""
    models = models if models is not None else configured_models()
    value = json.loads(payload)
    def has_image(item):
        if isinstance(item, list):return any(has_image(part) for part in item)
        if not isinstance(item, dict):return False
        if item.get('type') in ('image_url', 'image', 'input_image'):return True
        return any(has_image(part) for part in item.values())
    vision = has_image(value.get('messages', []))
    state['mode'] = 'vision' if vision else 'classified'
    state['judgeModel'] = None if vision else models['router']
    if vision:
        import switchyard_vision
        target = switchyard_vision.select_target(models, profile, rows)
        value['model'] = VISION_MODEL if target == 'capable' else VISION_EFFICIENT_MODEL
    if state.get('stage') != 'team':
        value['model'] = value.get('model', MODEL).replace(MODEL, LOUNGE_MODEL, 1)
    return json.dumps(value).encode()


def thinking_options(model, stage):
    """Only send provider-specific options to the two verified NVIDIA models."""
    if model not in MODEL_IDS[LIGHTNING] and model not in MODEL_IDS[SUPER_VL]:
        return {}
    enabled = stage == 'team'
    options = {'chat_template_kwargs': {'enable_thinking': enabled}}
    if enabled and model in MODEL_IDS[LIGHTNING]:
        options['thinking_token_budget'] = 1024
    return options


def binary():
    configured = os.environ.get('BAC_SWITCHYARD_BIN') or shutil.which('switchyard-server')
    path = Path(configured) if configured else Path.home() / '.cache/bacdemo/switchyard' / VERSION / 'bin/switchyard-server'
    return str(path) if path.is_file() and os.access(path, os.X_OK) else None


def availability(profile, rows, models=None):
    ids = {row['id'] for row in (rows or []) if isinstance(row, dict) and isinstance(row.get('id'), str)}
    defaults = resolve_catalog_models(DEFAULT_MODELS, ids)
    base_url = profile.get('baseUrl') if isinstance(profile, dict) else None
    models = resolve_catalog_models(models if models is not None else configured_models(base_url), ids)
    reason = None
    if not isinstance(profile, dict) or profile.get('_provider') != 'nvidia':
        reason = 'Automatic routing requires an NVIDIA connection.'
    elif not nvidia_endpoints.valid_config_url(base_url):
        reason = 'Model routing requires a supported NVIDIA NIM API endpoint.'
    elif not profile.get('apiKey') or profile['apiKey'] == 'session-only':
        reason = 'Connect NVIDIA NIM API first.'
    else:
        missing = [role.title() for role, model in models.items() if model not in ids]
        if missing:
            reason = 'Choose available NVIDIA models for ' + ', '.join(missing) + '.'
        elif not binary():
            reason = 'Install switchyard-server 0.3.0 to use Automatic routing.'
    return {**public_config(models, defaults), 'available': reason is None, 'reason': reason}


def render_config(models, base_url=None):
    """Use the shipped route policy with safe, catalog-validated model IDs."""
    models = normalize_models(models)
    template = CONFIG.read_text()
    if base_url is not None:
        template = re.sub(r'^base_url = .*$', lambda _: 'base_url = ' + json.dumps(base_url.rstrip('/')), template, flags=re.M)
    stages = []
    for stage in ('team', 'lounge'):
        text = template
        for key, model in models.items():
            pattern = r'(\[targets\.' + key + r'\]\n)(.*?)(?=\n\[|\Z)'
            def replace(match):
                body = re.sub(r'^id = .*$', 'id = ' + json.dumps(model), match[2], flags=re.M)
                body = re.sub(r'^extra_body = .*\n?', '', body, flags=re.M)
                options = thinking_options(model, stage)
                if options:
                    enabled = str(options['chat_template_kwargs']['enable_thinking']).lower()
                    extra = 'chat_template_kwargs = { enable_thinking = ' + enabled + ' }'
                    if 'thinking_token_budget' in options:
                        extra += ', thinking_token_budget = 1024'
                    body = body.rstrip() + '\nextra_body = { ' + extra + ' }\n\n'
                return match[1] + body
            text = re.sub(pattern, replace, text, flags=re.S)
        if stage == 'lounge':
            # Native 0.3.0 shares options by model ID within each client/route.
            # Separate route families retain both stage settings in one process.
            text = re.sub(r'^schema_version = .*\n', '', text, flags=re.M)
            text = text.replace('[llm_clients.hub]', '[llm_clients.lounge]')
            text = text.replace('llm_client = "hub"', 'llm_client = "lounge"')
            text = re.sub(r'\[targets\.(\w+)\]', r'[targets.lounge_\1]', text)
            text = re.sub(r'^(\w*target = ")(\w+)(")', r'\1lounge_\2\3', text, flags=re.M)
            text = re.sub(r'\[routes\.(\w+)\]', r'[routes.lounge_\1]', text)
            text = text.replace('id = "switchyard', 'id = "switchyard-lounge')
        stages.append(text)
    return '\n'.join(stages)


def stop():
    global _process, _port, _process_models, _process_base, _config_dir
    with _lock:
        if _process is not None and _process.poll() is None:
            _process.terminate()
            try:
                _process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _process.kill()
                _process.wait(timeout=2)
        _process, _port = None, None
        _process_models = None
        _process_base = None
        if _config_dir is not None:
            _config_dir.cleanup()
            _config_dir = None


def endpoint(models=None, *, base_url=None):
    """Start one loopback proxy lazily; credentials are forwarded per request."""
    global _process, _port, _process_models, _process_base, _config_dir
    models = normalize_models(models) if models is not None else configured_models()
    with _lock:
        if _process is not None and _process.poll() is None:
            if _process_models == models and _process_base == base_url:return f'http://127.0.0.1:{_port}/v1'
        stop()
        executable = binary()
        if not executable:
            raise RuntimeError('Install switchyard-server 0.3.0 to use Automatic routing.')
        try:
            version = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=5, check=True)
            if version.stdout.strip() != 'switchyard-server ' + VERSION:
                raise ValueError('Unexpected Switchyard version')
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                _port = listener.getsockname()[1]
            _config_dir = tempfile.TemporaryDirectory(prefix='bac-switchyard-')
            config = Path(_config_dir.name) / 'routes.toml'
            config.write_text(render_config(models, base_url));config.chmod(0o600)
            _process_models = dict(models)
            _process_base = base_url
            _process = subprocess.Popen([executable, '--config', str(config), '--host', '127.0.0.1', '--port', str(_port)],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 5
            while _process.poll() is None and time.monotonic() < deadline:
                try:
                    with socket.create_connection(('127.0.0.1', _port), timeout=.1):
                        return f'http://127.0.0.1:{_port}/v1'
                except OSError:
                    time.sleep(.05)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        stop()
        raise RuntimeError('Switchyard 0.3.0 could not start. Check the proxy binary and configuration.')


atexit.register(stop)
