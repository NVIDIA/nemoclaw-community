# SPDX-License-Identifier: Apache-2.0

"""Scenario-scoped local routing, independent of Lounge and the team API key."""
import json


def connection(studio, owner):
    with studio.db() as db:
        row = db.execute('SELECT value FROM metadata WHERE key=?', ('scenario-model:' + str(owner),)).fetchone()
    import model_connections
    saved = json.loads(row['value']) if row else {'provider': 'auto' if model_connections.enabled() else 'api'}
    if model_connections.enabled():
        state=model_connections.public()
        source=model_connections.choose(saved.get('provider','auto'),'team',state['connections'])
        saved={**saved,'shared':True,'effectiveSource':source,'ready':bool(source),'model':state['connections'][source]['model'] if source else ''}
    return saved


def readiness(studio, owner):
    status = studio.runtime_status()
    saved = connection(studio, owner)
    if saved.get('shared'):
        return {**status,'teamModel':saved['ready'],'teamReady':saved['ready'] and bool(status.get('gateway'))}
    if saved.get('provider') == 'local':
        return {**status, 'teamModel': True, 'teamReady': bool(status.get('gateway'))}
    return status


def local_profile(data):
    import runtime_settings as settings
    import team_models
    from studio import Problem
    _, profile = settings.validate({'provider': 'local', 'baseUrl': data.get('baseUrl', 'http://127.0.0.1:8000/v1'),
                                   'model': data.get('model', ''), 'contextWindow': data.get('contextWindow', 32768)}, False)
    # Never inherit Lounge credentials, even when both use the same endpoint.
    profile.update(apiKey='', requiresKey=False)
    if profile['model'] and not team_models.valid_model(profile['model']):
        raise Problem('Choose a supported local model ID.')
    return profile


def models(data):
    import runtime_settings as settings
    import team_models
    from studio import Problem
    profile = local_profile(data)
    response = settings.request('local', profile, '/models', timeout=10)
    rows = response.get('data') if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise Problem('The local endpoint did not return a model list.', 502)
    return {'models': [{'id': row['id'], 'label': row['id']} for row in rows
                       if isinstance(row, dict) and team_models.valid_model(row.get('id'))]}


def configure(studio, owner, data):
    from studio import Problem
    provider = data.get('provider')
    import model_connections
    if provider not in ('api', 'local', 'auto'):
        raise Problem('Choose API or local for this scenario.')
    # Check before probing, then recheck under the write lock before applying.
    with studio.db() as db:
        studio.require_team_idle(db, owner)
    profile = local_profile(data) if provider == 'local' and not model_connections.enabled() else None
    if profile and profile['model'] not in {row['id'] for row in models(data)['models']}:
        raise Problem('Choose a model returned by the local endpoint. Load models and try again.', 502)
    with studio.db() as db:
        db.execute('BEGIN IMMEDIATE')
        studio.require_team_idle(db, owner)
        row=db.execute('SELECT value FROM metadata WHERE key=?',('scenario-model:'+owner,)).fetchone()
        saved=json.loads(row['value']) if row else {}
        saved={k:v for k,v in saved.items() if k in ('provider','local')}
        saved['provider'] = provider
        if profile:
            saved['local'] = {key: profile[key] for key in ('baseUrl', 'model', 'contextWindow')}
        db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',
                   ('scenario-model:' + owner, json.dumps(saved)))
        resources = db.execute('SELECT native_id FROM crew_resources WHERE owner=?', (owner,)).fetchall()
        for row in resources:
            studio.provisioned.discard(row['native_id'])
    return {'teamConnection': connection(studio,owner)}


def prepare(studio, owner, member):
    saved = connection(studio, owner)
    member['_scenario'] = studio.crew_scenario(owner)
    member.pop('_teamLocal', None)
    member.pop('_connectionConfig', None)
    if saved.get('shared'):
        import model_connections
        model_connections.prepare(studio,member,saved.get('provider','auto'))
        return
    import team_models
    if saved.get('provider') == 'local':
        member['_teamLocal'] = saved['local']
        member['_teamModel'] = team_models.local_provider(member['id']) + '/' + saved['local']['model']
    elif team_models.role_for(member['id']) == 0:
        selected = member.get('_teamModel') or team_models.credentials().get('model') or team_models.default_model(0)
        member['_teamModel'] = 'bac-team/' + selected
