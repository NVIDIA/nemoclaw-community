# SPDX-License-Identifier: Apache-2.0

"""Per-agent choices from prepared connections, adapted from Paul Roeseler's experiment.

Profiles store only a source/model reference. Credentials remain in the existing
connection inventory. Open Task prefers the API default without overwriting saved Lounge choices.
"""
import model_connections as connections
import runtime_settings as settings
import team_models
import model_catalog

DEFAULT = 'local'  # Historical profile value for an untouched Hiring picker.
EXPLICIT_LOCAL = 'prefer-local'
LEGACY = 'shared'
AUTOMATIC = 'auto'


def automatic_status(state=None):
    """Report the configured NVIDIA route without starting a router or model call."""
    import switchyard_router
    state = state or connections.public()
    api = state['connections']['api']
    result = api.get('automatic') or switchyard_router.availability(connections.profile('api', discovery=False), api.get('models', []))
    if not api.get('ready'):
        result = {**result, 'available': False,
                  'reason': api.get('message') or 'Connect the NVIDIA endpoint in Settings.'}
    return result


def automatic_choice(state=None):
    import switchyard_router
    result = automatic_status(state)
    return {'id': AUTOMATIC, 'label': switchyard_router.LABEL, 'source': 'auto',
            'connected': result['available'],
            'description': switchyard_router.DESCRIPTION,
            'reason': result.get('reason', '')}


def selection(profile):
    return profile.get('model', LEGACY)


def hiring_default():
    # An untouched picker follows the connection default. Only an explicit
    # model choice is pinned, including an explicit Switchyard selection.
    return DEFAULT


def split_ref(value):
    if not isinstance(value, str):
        return None
    parts = value.split('/', 2)
    if len(parts) == 3 and parts[0] == 'api' and parts[1] in ('nvidia', 'openai', 'anthropic') and team_models.valid_model(parts[2]):
        return parts[1], parts[2]
    return None


def validate(value=DEFAULT, *, previous=None, lounge=False):
    from studio import Problem
    if value in (DEFAULT, LEGACY) or (lounge and value == EXPLICIT_LOCAL):
        return value
    if value == AUTOMATIC and (previous == AUTOMATIC or
            any(row['id'] == AUTOMATIC and row['connected'] for row in public()['models'])):
        return value
    if split_ref(value) and (value == previous or any(row['id'] == value for row in public()['models'])):
        return value
    raise Problem('Choose an available model for this agent.')


def public(state=None):
    state = state or connections.public()
    local, api = (state['connections'][key] for key in ('local', 'api'))
    choices = [{'id': DEFAULT, 'label': 'Local' + (' - ' + local['model'] if local.get('model') else ''),
                'source': 'local', 'connected': bool(local['ready'])}]
    if api.get('provider') == 'nvidia':
        choices.insert(0, automatic_choice(state))
    # Only advertise catalog-backed choices. A saved model can remain in its
    # profile without being reintroduced after the live catalog excluded it.
    rows = {row['id']: row for row in model_catalog.filter_rows(
        api.get('models', []),provider=api.get('provider'),context_window=api.get('contextWindow',32768))}
    for model, row in rows.items():
        if not team_models.valid_model(model):
            continue
        choices.append({'id': 'api/' + api['provider'] + '/' + model,
                        'label': row.get('label', model), 'source': 'api',
                        'connected': bool(api['ready']), **model_catalog.public_metadata(row)})
    choices.append({'id': LEGACY, 'label': 'Shared default', 'source': 'shared',
                    'connected': bool(state['loungeSource'])})
    default = effective_selection({'model': DEFAULT}, {'modelConnections': state})
    return {'default': default, 'models': choices}


def effective_selection(profile, runtime, stage='lounge'):
    """Resolve per call, not from the current room, so navigation cannot reroute work."""
    chosen = selection(profile)
    if stage == 'team':
        if profile.get('taskModel'):
            return profile['taskModel']
        if chosen == AUTOMATIC or split_ref(chosen):
            return chosen
    if chosen == AUTOMATIC:
        return chosen
    state = runtime.get('modelConnections')
    if not state:
        return DEFAULT if chosen == EXPLICIT_LOCAL else chosen
    states = state['connections']
    if stage == 'team':
        source = connections.choose('auto', 'team', states)
    elif chosen == EXPLICIT_LOCAL:
        source = connections.choose('local', 'lounge', states)
    elif chosen in (DEFAULT, LEGACY):
        source = state['loungeSource']
    else:
        return chosen  # Preserve explicitly selected Lounge API models.
    if source == 'local':
        return DEFAULT
    if source == 'api':
        api = states['api']
        if api.get('provider') == 'nvidia' and api.get('defaultModel') == AUTOMATIC:
            return AUTOMATIC
        return 'api/' + api['provider'] + '/' + api['model']
    return DEFAULT if chosen == EXPLICIT_LOCAL else chosen


def ready(profile, runtime, stage='lounge'):
    value = effective_selection(profile, runtime, stage)
    if value == LEGACY:
        return bool(runtime.get('ready'))
    if not runtime.get('gateway'):
        return False
    if value == AUTOMATIC:
        return automatic_status(runtime.get('modelConnections'))['available']
    state = runtime.get('modelConnections')
    if not state:
        # Compatibility with pre-inventory local installations.
        return value == DEFAULT and settings.read()['provider'] == 'local' and bool(runtime.get('model'))
    return any(row['id'] == value and row['connected'] for row in public(state)['models'])


def unavailable(profile, stage='lounge'):
    chosen = (profile.get('taskModel') or selection(profile)) if stage == 'team' else selection(profile)
    if chosen == AUTOMATIC:
        return 'Automatic needs Switchyard and the Lightning and Super VL models on the NVIDIA connection. Check Settings or choose a model manually.'
    if stage == 'team' and (profile.get('taskModel') or split_ref(selection(profile))):
        return 'This agent’s selected Open Task model is unavailable. Check its connection or choose Automatic in the model picker.'
    if stage == 'team':
        return 'Open Task needs a connected External Endpoint or Local model in Settings.'
    return ('No model connection is available. Connect Local or an External Endpoint in Settings.'
            if selection(profile) == DEFAULT else
            'This agent\'s model is unavailable. Check its connection in Settings or choose another model in Edit agent.')


def prepare(studio, member, stage='lounge'):
    from studio import Problem
    # Legacy/local-only workspace preparation does not need a model-health probe.
    # Preserve this path before consulting runtime status for stage routing.
    chosen = member.get('taskModel', selection(member)) if stage == 'team' else selection(member)
    if not connections.enabled() and (chosen == LEGACY or chosen == DEFAULT and settings.read()['provider'] == 'local'):
        return
    runtime = studio.runtime_status()
    chosen = effective_selection(member, runtime, stage)
    if chosen == LEGACY:
        if connections.enabled():
            connections.prepare(studio, member, connections.read().get('lounge', 'auto'), 'lounge')
        return
    if not ready(member, runtime, stage):
        raise Problem(unavailable(member, stage), 503)
    if chosen == AUTOMATIC:
        import switchyard_router
        value = connections.profile('api')
        value.update(model=switchyard_router.MODEL, _switchyard=True)
        connections.bind(studio, member, value, 'lounge')
        return
    source = 'local' if chosen == DEFAULT else 'api'
    value = connections.profile(source)
    if source == 'api':
        provider, model = split_ref(chosen)
        if value['_provider'] != provider:
            raise Problem(unavailable(member, stage), 503)
        value['model'] = model
    connections.bind(studio, member, value, 'lounge')
