# SPDX-License-Identifier: Apache-2.0

"""Dedicated NVIDIA models with a host-persisted Stage 3 credential."""
import copy
import json
import os
import re
import tempfile
import model_catalog
import nvidia_endpoints

BASE_URL = nvidia_endpoints.PUBLIC
CAPTAIN_MODEL = 'nvidia/nvidia/nemotron-3-ultra-nvfp4'
ANALYST_MODEL = CAPTAIN_MODEL
MODELS = ('nvidia/nvidia/nemotron-3.5-super-vl', 'nvidia/nvidia/nemotron-3.5-lightning', CAPTAIN_MODEL)
LABELS = ('Nemotron 3.5 Super VL', 'Nemotron 3.5 Lightning', 'Nemotron 3 Ultra')
_catalog = [{'id':m,'label':label} for m,label in zip(MODELS,LABELS)]


def credential_path():
    import ops_common as c
    return c.home() / 'credentials' / 'stage3.json'


def saved_connection():
    try:
        value = json.loads(credential_path().read_text())
        if isinstance(value, dict) and value.get('source', 'host') == 'host':
            return value
        return {}
    except (OSError, ValueError):
        return {}


def host_default_model(ids):
    """Choose a known team model or the sole eligible model advertised by the endpoint."""
    from switchyard_router import MODEL_IDS
    for model in MODELS:
        for alias in MODEL_IDS.get(model, (model, model.removeprefix('nvidia/'))):
            if alias in ids:
                return alias
    return next(iter(ids)) if len(ids) == 1 else None


def credentials():
    import runtime_settings as settings
    import session_secrets as secrets
    saved = saved_connection()
    key = saved.get('apiKey')
    if isinstance(key, str) and key and nvidia_endpoints.host_configured(saved.get('baseUrl')):
        return {'baseUrl': saved['baseUrl'], 'apiKey': key,
                'model': saved.get('model') or MODELS[0]}
    return secrets.get(settings.secret_key('team'))


def save_connection(key, models, source=None, base_url=None, model=None):
    previous = saved_connection()
    base_url = base_url or (previous.get('baseUrl') if previous.get('apiKey') == key else BASE_URL)
    if not nvidia_endpoints.host_configured(base_url):
        raise ValueError('Choose a supported NVIDIA API endpoint.')
    base_url = base_url.rstrip('/')
    credential_source = source or (previous.get('source') if previous.get('apiKey') == key else None) or 'host'
    path = credential_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.stage3-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'apiKey': key, 'baseUrl': base_url, 'models': models, 'model': model or MODELS[0], 'source': credential_source}, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)

def valid_model(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}',value))


def role_for(agent):
    match = re.fullmatch(r'bac-[0-9a-f]{24}-r([0-9])', agent)
    return int(match[1]) if match else None


def default_model(role):
    # Ultra for coordination, review and analysis; Super VL for research, code and UX.
    if role in (0, 4):return CAPTAIN_MODEL
    if role == 6:return ANALYST_MODEL
    return MODELS[0 if role in (5, 7, 8, 9) else 1]


def local_provider(agent):
    return 'bac-team-local-' + agent.split('-')[1] if role_for(agent) is not None else None


def model_for(agent, selected=None):
    role = role_for(agent)
    if role is None:return None
    from model_connections import provider_id
    if isinstance(selected,str) and selected.startswith(provider_id(agent)+'/'):return selected
    prefix = local_provider(agent) + '/'
    if isinstance(selected, str) and selected.startswith(prefix) and valid_model(selected[len(prefix):]):
        return selected
    if isinstance(selected,str) and selected.startswith('bac-team/'):
        selected=selected[len('bac-team/'):]
        if valid_model(selected):return 'bac-team/'+selected
    if valid_model(selected) and selected in {m['id'] for m in _catalog}:return 'bac-team/'+selected
    return 'bac-team/'+default_model(role)


def public():
    models = saved_connection().get('models', _catalog)
    models = [{'id': m['id'], 'label': dict(zip(MODELS, LABELS)).get(m['id'], m.get('label', m['id'])),
               **model_catalog.public_metadata(m)}
              for m in model_catalog.filter_rows(models if isinstance(models,list) else _catalog,
                                                 provider='nvidia',context_window=32768)
              if valid_model(m.get('id'))]
    return {'connected':bool(credentials().get('apiKey')), 'models':models}


def available_models():
    import model_connections
    if model_connections.enabled():
        state=model_connections.status('api')
        if state['provider']=='nvidia' and state['ready']:
            rows = state.get('models',[])
            import personal_models
            automatic = personal_models.automatic_choice()
            return ([automatic] if automatic['connected'] else []) + rows
    return public()['models']


def apply(config, selected=None, local=None, agent_id=None, base_url=None):
    import runtime_settings as settings
    import session_secrets as secrets
    ids=set(MODELS)
    if selected != 'auto' and valid_model(selected) and not selected.startswith('bac-team-local-'):ids.add(selected.removeprefix('bac-team/'))
    for agent,entry in config.get('agents',{}).get('entries',{}).items():
        model=model_for(agent,entry.get('model'))
        if model and model.startswith('bac-team/'):ids.add(model.removeprefix('bac-team/'))
    config.setdefault('models',{}).setdefault('providers',{})['bac-team']={
        'baseUrl':secrets.proxy_url('team',base_url or credentials().get('baseUrl',BASE_URL)),'apiKey':'session-only','api':'openai-completions',
        'models':[{'id':m,'name':m,'input':['text'],'reasoning':False,'contextWindow':32768,
                   'contextTokens':32768,'maxTokens':settings.MAX_OUTPUT_TOKENS,
                   'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}} for m in sorted(ids)]}
    if local is not None and local_provider(agent_id):
        context = local['contextWindow']
        config['models']['providers'][local_provider(agent_id)] = {
            **secrets.native_route('local',local), 'api': 'openai-completions',
            'models': [{'id': local['model'], 'name': local['model'], 'input': ['text'], 'reasoning': False,
                        'contextWindow': context, 'contextTokens': context, 'maxTokens': settings.output_token_limit(context),
                        'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}]}
    for agent,entry in config.get('agents',{}).get('entries',{}).items():
        model=model_for(agent,entry.get('model'))
        if model:entry.update(model=model,modelPolicy={'allow':[model]})
    return config


def configure(studio,data):
    global _catalog
    import agent_runtime as runtime
    import runtime_settings as settings
    import session_secrets as secrets
    import ops_common as c
    from studio import Problem
    request = {'provider':'nvidia', 'model':MODELS[0], 'apiKey':data.get('apiKey',''),
               '_credentialSession':data.get('_credentialSession')}
    if 'baseUrl' in data:
        request['baseUrl'] = data['baseUrl']
    provider,profile=settings.validate(request)
    if not data.get('apiKey'):raise Problem('Enter the dedicated Multi-Agent Demo API key.')
    available=settings.request(provider,profile,'/models',timeout=25)
    rows=model_catalog.filter_rows(available.get('data',[]),provider=provider,context_window=32768)
    by_id={row['id']:row for row in rows if valid_model(row.get('id'))}
    ids=set(by_id)
    if not set(MODELS).issubset(ids):raise Problem('The dedicated API key must provide the configured Nemotron models.',502)
    with studio.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running','waiting','stopping') LIMIT 1").fetchone():
            raise Problem('Finish or cancel pending missions before changing team models.',409)
        _catalog=[{'id':m,'label':dict(zip(MODELS,LABELS)).get(m,m),
                   **model_catalog.public_metadata(by_id[m])} for m in sorted(ids)]
        with runtime.config_lock():
            config=copy.deepcopy(c.read_json(runtime.config_path(),None) or runtime.initial_config())
            runtime.save_config(apply(config,base_url=profile['baseUrl']))
        save_connection(profile['apiKey'], _catalog, base_url=profile['baseUrl'])
        secrets.remove(settings.secret_key('team'))
        studio.provisioned.clear();studio.status_cache=(0,{})
    return public()


def selections(studio, owner, scenario=None):
    from studio import CREW_CATALOG
    with studio.db() as db:
        saved={r['role']:r['model'] for r in db.execute('SELECT role,model FROM crew_resources WHERE owner=?',(owner,))}
    import model_connections
    shared_default = None
    shared = model_connections.enabled()
    if shared:
        from scenario_models import connection
        route = connection(studio, owner)
        state = model_connections.public()['connections']
        source = route.get('effectiveSource')
        connection_state = state[source] if source else {}
        specialist_connection = state[source or 'api']
        shared_default = specialist_connection.get('defaultModel') or specialist_connection.get('model')
        if source != 'api' or connection_state.get('provider') != 'nvidia':
            saved.pop(0, None)
    choices = [{'id': saved.get(role) if valid_model(saved.get(role)) else
                   (shared_default if shared else default_model(role)),
             'role': role, 'inherited': shared and not valid_model(saved.get(role))}
            for role in range(len(CREW_CATALOG))]
    captain_default = model_connections.captain_model(connection_state) if shared else credentials().get('model') or default_model(0)
    choices[0].update(defaultId=captain_default, inherited=not valid_model(saved.get(0)))
    if choices[0]['inherited']:
        choices[0]['id'] = captain_default
    return choices


def select(studio, owner, data):
    from studio import Problem, CREW_CATALOG
    role,model=data.get('role'),data.get('model')
    eligible = {i for i,m in enumerate(CREW_CATALOG) if m.get('planEligible',True)}
    if type(role) is not int or role not in eligible:
        raise Problem('Choose a team member and an available model.')
    restore = role == 0 and 'model' in data and model is None
    if role == 0 and model == 'auto':
        raise Problem('Choose a specific model for Casey or use the Open Task default.')
    if not restore and (not valid_model(model) or model not in {m['id'] for m in available_models()}):
        raise Problem('Choose a team member and an available model.')
    if role == 0 and not restore:
        import model_connections
        from scenario_models import connection
        route = connection(studio, owner)
        if route.get('shared'):
            editable = route.get('effectiveSource') == 'api' and model_connections.status('api')['provider'] == 'nvidia'
        else:
            editable = route['provider'] == 'api'
        if not editable:
            raise Problem('Choose an NVIDIA connection in Open Task to change Casey’s model.', 409)
    with studio.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM agents WHERE id=? AND kind='crew' AND deleting=0",(owner,)).fetchone():
            raise Problem('Team not found.',404)
        studio.require_bac_not_resetting(db,owner)
        studio.require_team_idle(db,owner)
        if db.execute("SELECT 1 FROM jobs WHERE owner=? AND status IN ('queued','running','waiting','stopping')",(owner,)).fetchone():
            raise Problem('Wait for the current team task to finish before changing models.',409)
        resource=db.execute('SELECT native_id FROM crew_resources WHERE owner=? AND role=?',(owner,role)).fetchone()
        if not resource:raise Problem('Team member not found.',404)
        db.execute('UPDATE crew_resources SET model=? WHERE owner=? AND role=?',(model,owner,role))
        # Provisioning applies the preference before the next request; no idle
        # native agent, container or credential is created by a model selection.
        studio.provisioned.discard(resource['native_id'])
    return {'teamSelections':selections(studio,owner)}
