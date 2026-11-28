# SPDX-License-Identifier: Apache-2.0

"""Shared connection inventory and stage preferences. No credentials on disk."""
import copy
import json
import threading
import time
import hashlib
import ops_common as c
import runtime_settings as settings
import session_secrets as secrets
import model_catalog
import provider_keys

_lock = threading.RLock()
_checks = {}
_pending = set()
_discovered = {}


def path():return c.home() / 'model-connections.json'
def enabled():return path().exists()
def read():return c.read_json(path(), {'apiProvider':'nvidia','lounge':'auto','disabled':[]})


def nim_defaults(config, previous=None):
    """An explicit model choice belongs to the NIM endpoint where it was saved."""
    choices = dict(config.get('nimDefaults', {}))
    mode = config.get('apiDefault')
    if mode in ('auto', 'fixed') and config.get('apiProvider') == 'nvidia':
        if previous is None:
            previous = settings.read().get('profiles', {}).get('nvidia', {})
        base = previous.get('baseUrl')
        model = 'auto' if mode == 'auto' else previous.get('model')
        if base and model:
            choices.setdefault(base.rstrip('/'), model)
    return choices


def persist(value):
    path().parent.mkdir(parents=True,exist_ok=True)
    temp=path().with_suffix('.new')
    temp.write_text(json.dumps(value));temp.chmod(0o600);temp.replace(path())


def initialize():
    """Migrate the selected host provider once, without copying credentials."""
    with _lock:
        if enabled():return
        value=read();previous=settings.read();provider=previous.get('provider')
        if provider in settings.PROVIDERS and previous.get('profiles',{}).get(provider):
            value['lounge']='local' if provider=='local' else 'api'
            if provider!='local':value['apiProvider']=provider
        persist(value)


def profile(source, discovery=True):
    import team_models
    saved=read();provider='local' if source=='local' else saved.get('apiProvider','nvidia')
    previous=settings.read().get('profiles',{}).get(provider,{})
    value=copy.deepcopy(previous)
    value.update(secrets.get(settings.secret_key(provider)))
    slot = provider_keys.read().get(provider) if source == 'api' and not value.get('apiKey') else None
    if slot:
        if value.get('baseUrl') != slot['baseUrl']:
            value.pop('model', None)
        value.update(slot)
        if slot['apiKey']:
            value.update(_credentialProvider=provider_keys.route_id(provider, slot['baseUrl']), _keySource='api.json')
    if provider=='nvidia' and not value.get('apiKey'):
        fallback=team_models.credentials()
        if fallback.get('apiKey') and (not value.get('baseUrl') or value['baseUrl'].rstrip('/') == fallback.get('baseUrl')):
            for field in ('apiKey','baseUrl'):value[field]=fallback[field]
            value.setdefault('model',fallback['model'])
            value['_credentialProvider']='team'
    value.setdefault('baseUrl',settings.PROVIDERS[provider]['baseUrl'])
    if provider == 'nvidia':
        choice = nim_defaults(saved, previous).get(value['baseUrl'].rstrip('/'))
        if choice and choice != 'auto':
            value['model'] = choice
    value.setdefault('contextWindow',32768)
    value['_provider']=provider
    value.setdefault('apiKey','')
    if value.get('apiKey') and not value.get('_keySource'):
        stored=team_models.saved_connection() if provider=='nvidia' else {}
        value['_keySource']=stored.get('source','host') if stored.get('apiKey')==value['apiKey'] else 'session'
    if discovery and not value.get('model') and (source == 'local' or slot):
        with _lock:
            detected = _discovered.get((str(path()), signature(value)))
        if detected:
            value.update(detected, _autoDetected=True)
    return value


def signature(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def catalog(rows,provider='nvidia',context_window=None):
    import team_models
    return [{'id':row['id'],'label':row.get('display_name') or row.get('label') or dict(zip(team_models.MODELS,team_models.LABELS)).get(row['id'],row['id']),
             **model_catalog.public_metadata(row)}
            for row in model_catalog.filter_rows(rows,provider=provider,context_window=context_window)
            if team_models.valid_model(row.get('id'))]


def probe(source,value):
    key=signature(value)
    automatic = (source == 'local' or value.get('_keySource') == 'api.json') and (
        not value.get('model') or value.get('_autoDetected'))
    with _lock:
        # A queued probe may start after Settings changed. Never associate an old
        # endpoint's catalogue with the new endpoint's discovery baseline.
        if automatic and signature(profile(source)) != key:
            _pending.discard(key)
            return {'ready':False, 'message':'Connection settings changed. Checking again.', 'checkedAt':time.time()}
        baseline = profile(source, discovery=False) if automatic else None
        discovery_key = (str(path()), signature(baseline)) if automatic else None
    detected = None
    verified_at = None
    try:
        provider=value['_provider']
        result=settings.request(provider,value,'/v1/models?limit=1000' if provider=='anthropic' else '/models',timeout=8)
        rows=result.get('data',[]) if isinstance(result,dict) else []
        rows=model_catalog.filter_rows(rows,provider=provider,context_window=value.get('contextWindow',32768))
        message = None
        if automatic:
            valid_ids = {model['id'] for model in catalog(rows,provider=provider)}
            candidates = {row['id']:row for row in rows if isinstance(row, dict) and row.get('id') in valid_ids}
            if source == 'api':
                import team_models
                # Only NIM has known defaults. Other providers need an explicit choice when ambiguous.
                model = team_models.host_default_model(set(candidates)) if provider == 'nvidia' else (
                    next(iter(candidates)) if len(candidates) == 1 else None)
                if model:
                    detected = {'model': model}
                    value = {**baseline, **detected, '_autoDetected': True}
                else:
                    message = 'Choose a model in Settings.' if candidates else 'No supported models found.'
            elif len(candidates) == 1:
                model, row = next(iter(candidates.items()))
                limit = row.get('max_model_len')
                context = baseline['contextWindow']
                if type(limit) is int:
                    context = min(context, limit)
                if context >= 8192:
                    detected = {'model':model, 'contextWindow':context}
                    value = {**baseline, **detected, '_autoDetected':True}
                else:
                    message = 'Local model context is below the supported 8,192-token minimum.'
            else:
                message = ('Multiple local models found. Choose one in Settings.' if candidates else
                           'No local model is available yet.')
        ready=not message and any(isinstance(row,dict) and row.get('id')==value.get('model') for row in rows)
        state={'ready':ready,'message':message or ('Ready' if ready else 'Selected model is not available.'),
               'checkedAt':time.time(),'models':catalog(rows,provider=provider,context_window=value.get('contextWindow',32768))}
        if ready:
            verified_at = time.monotonic()
    except Exception as error:
        from studio import Problem
        state={'ready':False,'message':str(error) if isinstance(error,Problem) else 'Connection check failed.','checkedAt':time.time()}
        # A catalogue outage need not stop a working inference connection. Keep
        # only the same API profile's recent verification, never extending it
        # with repeated failures. Authentication/permissions and explicit disable
        # still fail immediately; inference itself remains fully authenticated.
        if source == 'api' and getattr(error, 'transient', False):
            with _lock:
                previous = _checks.get(key)
            if previous and previous[1].get('ready'):
                last_success = previous[2] if len(previous) > 2 else previous[0]
                if last_success is not None and time.monotonic() - last_success < 90:
                    verified_at = last_success
                    state = {**previous[1], 'checkedAt':time.time(),
                             'message':'Connection check delayed; using recent verification.'}
    with _lock:
        if automatic and signature(profile(source, discovery=False)) == discovery_key[1]:
            # Discovery is runtime-only; explicit settings and routing stay intact.
            if detected:
                _discovered[discovery_key] = detected
            elif 'models' in state:
                _discovered.pop(discovery_key, None)
            _checks[discovery_key[1]] = (time.monotonic(), state)
            _checks[signature(value)] = (time.monotonic(), state)
        _checks[key]=(time.monotonic(),state,verified_at);_pending.discard(key)
    return state


def status(source,refresh=False):
    value=profile(source);key=signature(value)
    basic={'provider':value['_provider'],'model':value.get('model',''),'baseUrl':value['baseUrl'],'contextWindow':value['contextWindow'],'keySource':value.get('_keySource'),'enabled':source not in read().get('disabled',[])}
    if source in read().get('disabled',[]):return {**basic,'ready':False,'message':'Disabled'}
    if (source=='api' and (not value.get('apiKey') or (not value.get('model') and value.get('_keySource') != 'api.json'))) or (source=='local' and not value.get('model') and not enabled()):
        return {**basic,'ready':False,'message':'Not configured'}
    with _lock:
        cached=_checks.get(key)
        if refresh or not cached or time.monotonic()-cached[0]>30:
            if key not in _pending:
                _pending.add(key)
                threading.Thread(target=probe,args=(source,value),daemon=True,name='model-connection-check').start()
        state=cached[1] if cached and time.monotonic()-cached[0]<90 else {'ready':False,'message':'Checking…'}
        if cached and state.get('ready'):
            verified_at = cached[2] if len(cached) > 2 else cached[0]
            if verified_at is None or time.monotonic() - verified_at >= 90:
                state = {'ready':False,'message':'Checking…'}
    return {**basic,**state}


def choose(preference,stage,states):
    preferred=('local' if stage=='lounge' else 'api') if preference=='auto' else preference
    other='api' if preferred=='local' else 'local'
    return preferred if states[preferred]['ready'] else other if states[other]['ready'] else None


def public(refresh=False):
    states={s:status(s,refresh) for s in ('local','api')}
    import switchyard_router
    api=states['api']
    api['automatic']=switchyard_router.availability(profile('api',discovery=False),api.get('models',[]))
    saved=read()
    api['defaultModel']=api['model']
    if api['provider']=='nvidia':
        choice=nim_defaults(saved).get(api['baseUrl'].rstrip('/'))
        if choice or api['automatic']['available'] or 'models' not in api:
            api['defaultModel']=choice or 'auto'
    api['defaultLabel']=switchyard_router.LABEL if api['defaultModel']=='auto' else api['defaultModel']
    lounge=saved.get('lounge','auto')
    return {'connections':states,'loungePreference':lounge,
            'loungeSource':choose(lounge,'lounge',states),'enabled':enabled()}


def resolve(preference='auto',stage='team'):
    state=public();source=choose(preference,stage,state['connections'])
    return source,profile(source) if source else None


def captain_model(connection):
    """Resolve the user's connection default to the single model Casey will call."""
    chosen = connection.get('defaultModel') or connection.get('model')
    if chosen == 'auto' and connection.get('provider') == 'nvidia':
        return connection['automatic']['configuration']['capable']
    return chosen


def idle(studio,db):
    from studio import Problem
    # Standby Shell prepares its protected workspace without using a model connection.
    if db.execute("""
        SELECT 1 FROM jobs
        WHERE status IN ('queued','running','waiting','stopping')
          AND NOT (kind='prepare' AND COALESCE(json_extract(payload,'$.shellWarmup'),0)=1)
        LIMIT 1
    """).fetchone():
        raise Problem('Finish or stop active work before changing model connections.',409)


def configure(studio,data):
    from studio import Problem
    source=data.get('source')
    if source not in ('local','api'):raise Problem('Choose Local model or API.')
    with studio.db() as db:idle(studio,db)
    provider=data.get('provider') if source=='api' else 'local'
    if provider not in ('nvidia','openai','anthropic') and source=='api':raise Problem('Choose an API provider.')
    request={**data,'provider':provider}
    request=with_saved_key(request)
    use_default=provider=='nvidia' and not data.get('model')
    routing_models = None
    import switchyard_router
    provider,value=settings.validate(request, require_model=not use_default, connect_endpoint=True)
    if use_default:
        value['model']=nim_defaults(read()).get(value['baseUrl'], 'auto')
    automatic=source=='api' and value['model']=='auto'
    if automatic and provider != 'nvidia':
        raise Problem(switchyard_router.LABEL+' requires the NVIDIA endpoint.')
    if automatic:
        rows=settings.connection_catalog(provider,value)
        eligible=catalog(rows,provider=provider,context_window=value['contextWindow'])
        if 'routingModels' in data:
            try:routing_models=switchyard_router.normalize_models(data['routingModels'])
            except ValueError as error:raise Problem(str(error))
        availability=switchyard_router.availability({**value,'_provider':provider},eligible,routing_models)
        if not availability['available']:raise Problem(availability['reason'],503)
        routing_models=availability['configuration']
        value['model']=routing_models['capable']
    else:
        rows=settings.verify_connection(provider,value)
    with _lock,studio.db() as db:
        db.execute('BEGIN IMMEDIATE');idle(studio,db)
        saved=settings.read()
        previous_nim=saved.get('profiles',{}).get('nvidia',{})
        config=read()
        choices=nim_defaults(config,previous_nim)
        if provider=='nvidia':
            choices[value['baseUrl']]='auto' if automatic else value['model']
        if choices:config['nimDefaults']=choices
        config.pop('apiDefault',None)
        saved.setdefault('profiles',{})[provider]=value;settings.persist(saved)
        if request.get('_usingFileKey'):
            # Keep the file authoritative after rotation or removal.
            secrets.remove(settings.secret_key(provider))
        else:
            secrets.put(settings.secret_key(provider),value,data.get('_credentialSession','direct'))
        config['disabled']=[s for s in config.get('disabled',[]) if s!=source]
        if source=='api':
            config['apiProvider']=provider
        pools=switchyard_router.saved_pools(config,previous_nim.get('baseUrl'))
        routing_changed=False
        if routing_models is not None:
            routing_changed=pools.get(value['baseUrl']) != routing_models
            pools[value['baseUrl']]=routing_models
        if pools:config['switchyardPools']=pools
        config.pop('switchyardModels',None)
        persist(config)
        if routing_changed:switchyard_router.stop()
        checked=profile(source)
        _checks[signature(checked)]=(time.monotonic(),{'ready':True,'message':'Ready','checkedAt':time.time(),
                                                    'models':catalog(rows,provider=provider,context_window=value['contextWindow'])})
        studio.provisioned.clear();studio.status_cache=(0,{})
    return public()


def preferences(studio,data,owner=None,participant=None):
    from studio import Problem
    preference=data.get('lounge')
    if 'lounge' in data and preference not in ('auto','local','api'):raise Problem('Choose Auto, Local model or API.')
    team=data.get('team')
    if team is not None and team not in ('auto','local','api'):raise Problem('Choose Auto, Local model or API.')
    scenarios=data.get('scenarios',{})
    if not isinstance(scenarios,dict) or any(k != 'plan' or v not in ('auto','local','api') for k,v in scenarios.items()):raise Problem('Choose a valid connection for each scenario.')
    if scenarios and not participant:raise Problem('Open your Settings before changing scenarios.')
    owners={key:studio.crew_owner(participant,key) for key in scenarios}
    with _lock,studio.db() as db:
        db.execute('BEGIN IMMEDIATE');idle(studio,db)
        saved=read()
        if preference is not None:saved['lounge']=preference
        if 'disable' in data:
            source=data['disable']
            if source not in ('local','api'):raise Problem('Choose a connection.')
            saved['disabled']=list(set(saved.get('disabled',[]))|{source})
        if 'enable' in data:
            source=data['enable']
            if source not in ('local','api'):raise Problem('Choose a connection.')
            saved['disabled']=[s for s in saved.get('disabled',[]) if s!=source]
        if team is not None and owner:
            db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',('scenario-model:'+owner,json.dumps({'provider':team})))
        for key,scenario_owner in owners.items():
            db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',('scenario-model:'+scenario_owner,json.dumps({'provider':scenarios[key]})))
        persist(saved);studio.provisioned.clear();studio.status_cache=(0,{})
    result=public()
    if owner:
        from scenario_models import connection
        result['teamConnection']=connection(studio,owner)
    return result


def native(value):
    provider=value['_provider'];credential=value.get('_credentialProvider',provider)
    if value.get('_switchyard'):
        import switchyard_router
        context = min(value['contextWindow'], 32768)
        return {**secrets.native_route(credential,value),'api':'openai-completions',
                'models':[{'id':switchyard_router.MODEL,'name':switchyard_router.LABEL,
                           'input':['text','image'],
                           'compat':{'requiresReasoningContentOnAssistantMessages':True},
                           'reasoning':False,'contextWindow':context,'contextTokens':context,
                           'maxTokens':settings.output_token_limit(context),
                           'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}}]}
    return {**secrets.native_route(credential,value),'api':settings.PROVIDERS[provider]['api'],
            'models':[{'id':value['model'],'name':value['model'],'input':value.get('_inputModalities', ['text']),'reasoning':False,
                       'contextWindow':value['contextWindow'],'contextTokens':value['contextWindow'],
                       'maxTokens':settings.output_token_limit(value['contextWindow']),
                       'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}}]}


def prepare(studio,member,preference='auto',stage='team'):
    from studio import Problem
    source,value=resolve(preference,stage)
    if not value:raise Problem('Model not connected. Configure a Local model or API in Settings.',503)
    import team_models
    captain = stage == 'team' and team_models.role_for(member['id']) == 0
    selected = member.get('_teamModel') if stage == 'team' else None
    if captain and selected == 'auto':
        selected = None
    if source == 'api' and value['_provider'] == 'nvidia':
        api = public()['connections']['api']
        effective = selected or api.get('defaultModel')
        if captain and not selected:
            value['model'] = captain_model(api)
            if effective == 'auto':
                from switchyard_vision import catalog_support
                row = next((row for row in api.get('models', []) if row['id'] == value['model']), None)
                if row is None:
                    raise Problem('Casey’s Capable model is unavailable. Choose an available Capable model in Settings.', 503)
                # Preserve image delivery for NIM catalogs that omit modality metadata.
                if catalog_support(row) is not False:
                    value['_inputModalities'] = ['text', 'image']
        elif effective == 'auto':
            routing = api['automatic']
            import switchyard_router
            if not routing['available']:
                raise Problem(routing['reason'], 503)
            value.update(model=switchyard_router.MODEL, _switchyard=True)
        elif selected:
            row = next((row for row in api.get('models', []) if row['id'] == selected), None)
            if row is None:
                raise Problem('This agent’s selected model is unavailable on the current API connection. Choose another model for this agent.',503)
            value['model'] = selected
            if captain:
                from switchyard_vision import catalog_support
                support = catalog_support(row)
                if support is True or (support is None and selected == api['automatic']['configuration']['capable']):
                    value['_inputModalities'] = ['text', 'image']
    elif selected == 'auto' and not (preference == 'local' and source == 'local'):
        raise Problem('Automatic needs Switchyard on the NVIDIA connection. Choose a fixed model.', 503)
    bind(studio,member,value,stage)
    return source,value


def bind(studio,member,value,stage='team'):
    provider=native(value)
    if stage=='lounge':provider['models'][0]['input']=['text','image']
    member['_connectionConfig']=provider
    if value.get('_switchyard'):
        member['_switchyard'] = True
    else:
        member.pop('_switchyard', None)
    stamp=(signature(provider), bool(value.get('_switchyard')))
    routes=studio.__dict__.setdefault('_connection_routes',{})
    if routes.get(member['id'])!=stamp:studio.provisioned.discard(member['id']);routes[member['id']]=stamp


def is_automatic(studio,agent_id):
    return studio.__dict__.get('_connection_routes',{}).get(agent_id,(None,False))[1]


def provider_id(agent):
    return 'bac-connection-'+hashlib.sha256(agent.encode()).hexdigest()[:24]


def with_saved_key(data):
    # Private flags are derived here, never accepted from the browser.
    data = {k:v for k,v in data.items() if k != '_usingFileKey'}
    provider = data.get('provider')
    if provider not in ('nvidia', 'openai', 'anthropic') or data.get('apiKey'):
        return data
    session = secrets.get(settings.secret_key(provider), data.get('_credentialSession', 'direct'))
    slot = provider_keys.read().get(provider, {})
    saved = settings.read().get('profiles', {}).get(provider, {})
    base = data.get('baseUrl', session.get('baseUrl') or slot.get('baseUrl') or saved.get('baseUrl')
                    or settings.PROVIDERS[provider]['baseUrl'])
    if not isinstance(base, str):
        return data
    base = base.rstrip('/')
    if session.get('apiKey') and base == session.get('baseUrl'):
        return {**data, 'baseUrl':base, 'apiKey':session['apiKey']}
    if slot.get('apiKey') and base == slot['baseUrl']:
        return {**data, 'baseUrl':base, 'apiKey':slot['apiKey'], '_usingFileKey':True}
    if provider == 'nvidia':
        import team_models
        fallback = team_models.credentials()
        if not slot.get('apiKey') and base == fallback.get('baseUrl'):
            return {**data, 'baseUrl':base, 'apiKey':fallback.get('apiKey','')}
    return data


def models(data):
    request=with_saved_key(data)
    result=settings.models(request)
    if data.get('provider')=='nvidia':
        import switchyard_router
        provider,value=settings.validate(request,False,connect_endpoint=True)
        result['automatic']=switchyard_router.availability({**value,'_provider':provider},result['models'])
        result['defaultModel']=nim_defaults(read()).get(value['baseUrl'],
            'auto' if result['automatic']['available'] else '')
    return result



def scenario_preferences(studio,participant):
    result={}
    for key in ('plan',):
        owner=studio.existing_crew_owner(participant,key)
        with studio.db() as db:
            row=db.execute('SELECT value FROM metadata WHERE key=?',('scenario-model:'+owner,)).fetchone() if owner else None
        result[key]=json.loads(row['value']).get('provider','auto') if row else 'auto'
    return result


def public_for(studio,participant):
    return {**public(),'scenarioPreferences':scenario_preferences(studio,participant)}
