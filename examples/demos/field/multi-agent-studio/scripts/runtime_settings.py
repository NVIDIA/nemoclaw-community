# SPDX-License-Identifier: Apache-2.0

"""Host-only provider settings. Keys never enter participant state or model prompts."""
import copy
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import ops_common as c
import session_secrets as secrets
import model_catalog
import nvidia_endpoints
import provider_keys

MAX_OUTPUT_TOKENS = 16384
AGENT_TIMEOUT_SECONDS = 360


def output_token_limit(context_window):
    """Reserve at least half of the configured context for input and tools."""
    return min(MAX_OUTPUT_TOKENS, context_window // 2)


def apply_context_limits(config):
    """Bound fetched excerpts and check growing tool context before another call."""
    tools = config.setdefault('tools', {})
    # Each Studio role has a small allowlist. Expose those tools directly so
    # researchers can call web_search without an extra tool-discovery turn.
    tools.setdefault('toolSearch', False)
    fetch = tools.setdefault('web', {}).setdefault('fetch', {})
    # The native tool clamps even a model-supplied maxChars to maxCharsCap.
    # Preserve stricter host limits, without disabling any access policy.
    fetch['maxCharsCap'] = min(fetch.get('maxCharsCap', 4000), 4000)
    fetch['maxChars'] = min(fetch.get('maxChars', 3000), 3000, fetch['maxCharsCap'])
    compaction = config.setdefault('agents', {}).setdefault('defaults', {}).setdefault('compaction', {})
    compaction['enabled'] = True
    # Native default retains 20k recent tokens, exceeding the 16k input
    # budget of our 32k models. Leave room for summaries, tools and new evidence.
    windows = [32768]
    for provider in config.get('models', {}).get('providers', {}).values():
        for model in provider.get('models', []):
            for key in ('contextWindow', 'contextTokens'):
                value = model.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    windows.append(value)
    compaction['keepRecentTokens'] = min(compaction.get('keepRecentTokens', 8192), min(windows) // 4)
    compaction['midTurnPrecheck'] = {'enabled': True}
    return config

PROVIDERS = {
    'local': {'label': 'Local / on-prem', 'baseUrl': 'http://127.0.0.1:8000/v1', 'api': 'openai-completions'},
    'nvidia': {'label': 'NVIDIA NIM API', 'baseUrl': nvidia_endpoints.PUBLIC, 'api': 'openai-completions'},
    'openai': {'label': 'OpenAI', 'baseUrl': 'https://api.openai.com/v1', 'api': 'openai-responses'},
    'anthropic': {'label': 'Anthropic (Claude)', 'baseUrl': 'https://api.anthropic.com', 'api': 'anthropic-messages'},
}
DEFAULT_LOCATION = {'city': 'Zurich'}
DEFAULT_EVENT = {'region': 'Europe / EMEA', 'city': 'Zurich', 'language': 'English', 'venue': ''}


def path():
    return c.home() / 'host-settings.json'


def secret_key(provider):
    return str(path()) + ":" + provider


def read():
    settings = c.read_json(path(), {'provider': 'local', 'profiles': {}, 'event': DEFAULT_EVENT})
    for profile in settings.get('profiles', {}).values():profile.pop('apiKey', None)
    return settings


def public(lease=None):
    settings = read()
    return {'provider': settings['provider'], 'location': location(), 'event': settings.get('event', DEFAULT_EVENT),
            'providers': PROVIDERS, 'fileKeys': provider_keys.public(), 'profiles': {p: {k:v for k,v in profile.items() if k != 'apiKey'} | {'hasKey': bool(secrets.get(secret_key(p),lease).get('apiKey'))} for p,profile in settings.get('profiles', {}).items()}}


def event():
    return dict(read().get('event', DEFAULT_EVENT))


def location():
    return dict(read().get('location', DEFAULT_LOCATION))


def save_location(studio, data):
    from studio import Problem, ROLES
    import agent_runtime as runtime
    import user_location
    value = data.get('location')
    city = value.get('city') if isinstance(value, dict) else None
    if not isinstance(city, str) or not city.strip() or len(city) > 80 or any(ord(c) < 32 for c in city):
        raise Problem('Enter a city (up to 80 characters).')
    clean = {'city': city.strip()}
    # Do not reset sessions, reprovision agents or interrupt pending missions.
    with studio.db() as db:
        db.execute('BEGIN IMMEDIATE')
        with runtime.config_lock():
            saved = read(); saved['location'] = clean
            persist(saved)
            for row in db.execute('SELECT id FROM agents WHERE deleting=0'):
                for role in (None, *range(len(ROLES))):
                    user_location.sync(studio.workspace(row['id'], role), clean)
    studio.status_cache = (0, {})
    return public()


def selected_model():
    settings = read(); provider = settings['provider']
    profile = settings.get('profiles', {}).get(provider)
    return ('bac-' + provider + '/' + profile['model']) if profile else 'bac-vllm/bac-local'


def validate(data, require_model=True, *, connect_endpoint=False):
    from studio import Problem
    provider = data.get('provider')
    if provider not in PROVIDERS:
        raise Problem('Choose a provider.')
    saved = read().get('profiles', {}).get(provider, {})
    base = data.get('baseUrl')
    if 'baseUrl' not in data:
        slot = provider_keys.read().get(provider, {}) if provider != 'local' else {}
        base = slot.get('baseUrl') or saved.get('baseUrl') or PROVIDERS[provider]['baseUrl']
    if not isinstance(base, str) or len(base)>300:
        raise Problem('Enter a valid endpoint.')
    base = base.rstrip('/')
    try:
        url = urllib.parse.urlsplit(base)
    except ValueError:
        raise Problem('Enter a valid endpoint.') from None
    if url.username or url.password or url.query or url.fragment or any(ord(x)<33 for x in base):
        raise Problem('Use an endpoint without credentials or query parameters.')
    if provider == 'local':
        # Local development can use loopback or an explicitly entered private on-prem IP.
        try: private = ipaddress.ip_address(url.hostname).is_private
        except ValueError: private = url.hostname == 'localhost'
        from agent_runtime import gateway_port
        if url.scheme not in ('http', 'https') or not private or url.path != '/v1' or url.port in (18789, gateway_port()):
            raise Problem('Use a local/private host endpoint ending in /v1 (not the agent gateway).')
    elif provider == 'nvidia':
        if not nvidia_endpoints.valid_config_url(base):
            raise Problem('Enter an HTTPS endpoint ending in /v1.')
        if not connect_endpoint and not nvidia_endpoints.supported(base):
            raise Problem('Connect this endpoint in Settings first.')
    elif base != PROVIDERS[provider]['baseUrl']:
        raise Problem('Use this provider’s supported API endpoint.')
    key = data.get('apiKey', '')
    if not isinstance(key, str) or len(key)>4096 or any(ord(x)<33 or ord(x)>126 for x in key):
        raise Problem('Enter a valid API key.')
    # Never reuse an existing credential at a different destination.
    if not key and base == saved.get('baseUrl'):
        session = secrets.get(secret_key(provider), data.get('_credentialSession','direct'))
        if session.get('baseUrl') == base:
            key = session.get('apiKey', '')
    if not key and provider != 'local':
        raise Problem('Enter an API key for this provider.')
    model = data.get('model', saved.get('model', 'bac-local' if provider == 'local' else ''))
    if not isinstance(model,str) or (require_model and not model) or len(model)>240 or (model and not re.fullmatch(r'[A-Za-z0-9_./:@+-]+',model)):
        raise Problem('Choose or enter a model ID.')
    context = data.get('contextWindow', saved.get('contextWindow', 32768))
    if type(context) is not int or not 8192 <= context <= 2000000:
        raise Problem('Context limit must be between 8,192 and 2,000,000 tokens.')
    return provider, {'baseUrl':base,'apiKey':key,'model':model,'contextWindow':context,'requiresKey':bool(key)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # A key must never follow a redirect to another host.


def provider_opener(provider):
    # Explicit local/private endpoints must not leak keys or requests to a host proxy.
    handlers = [NoRedirect]
    if provider == 'local':
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def provider_error_detail(error, key):
    """Keep only a bounded JSON error message, with credentials redacted."""
    try:
        raw = error.read(16385)
        if len(raw) > 16384:
            return ''
        body = json.loads(raw)
        if not isinstance(body, dict):
            return ''
        detail = body.get('error', body)
        if isinstance(detail, dict):
            detail = detail.get('message') or detail.get('detail') or detail.get('code', '')
        if not isinstance(detail, str):
            return ''
        if key:
            for value in {key, urllib.parse.quote(key, safe='')}:
                detail = detail.replace(value, '[redacted]')
        detail = re.sub(r'(?i)bearer\s+\S+', 'Bearer [redacted]', detail)
        detail = re.sub(r'\b(?:nvapi-|sk-)[A-Za-z0-9_.-]+', '[redacted]', detail)
        detail = re.sub(r'(?i)((?:api[_ -]?key|token|authorization)\s*[:=]\s*)[^\s,;]+', r'\1[redacted]', detail)
        return ' '.join(detail.split())[:400]
    except (OSError, ValueError):
        return ''


def request(provider, profile, suffix, payload=None, timeout=25):
    from studio import Problem
    headers={'Accept':'application/json','Content-Type':'application/json'}
    if provider == 'anthropic':
        headers.update({'x-api-key':profile['apiKey'],'anthropic-version':'2023-06-01'})
    elif profile['apiKey']:
        headers['Authorization']='Bearer '+profile['apiKey']
    req=urllib.request.Request(profile['baseUrl']+suffix,headers=headers,data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with provider_opener(provider).open(req,timeout=timeout) as response:
            raw=response.read(4*1024*1024+1)
            if len(raw)>4*1024*1024: raise Problem('Provider response was too large.')
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        messages={401:'Authentication failed',403:'Access denied',404:'Endpoint or model was not found',429:'Provider rate limit reached'}
        message = '%s (HTTP %s; %s).' % (messages.get(error.code, 'Provider request failed'), error.code, urllib.parse.urlsplit(profile['baseUrl']).hostname)
        detail = provider_error_detail(error, profile.get('apiKey', ''))
        if detail:
            message += ' Provider: ' + detail
        problem = Problem(message,502)
        problem.upstream_status = error.code
        problem.transient = error.code in (408, 429) or 500 <= error.code < 600
        raise problem from None
    except (OSError, ValueError) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        host = urllib.parse.urlsplit(profile['baseUrl']).hostname
        if isinstance(reason, socket.gaierror):
            message = 'DNS lookup failed for %s. Check network DNS or VPN.' % host
        elif isinstance(reason, ssl.SSLCertVerificationError):
            message = 'TLS certificate verification failed for %s. Check the Python trust store or corporate proxy certificate.' % host
        elif isinstance(reason, ssl.SSLError):
            message = 'TLS connection failed for %s.' % host
        elif isinstance(reason, TimeoutError):
            message = 'Request to %s timed out after %s seconds.' % (host, timeout)
        elif isinstance(error, ValueError):
            message = '%s returned an invalid JSON response. Check the API endpoint or sign-in proxy.' % host
        elif isinstance(reason, ConnectionRefusedError):
            message = 'Connection to %s was refused.' % host
        else:
            message = 'Connection to %s failed (%s). Check the network or proxy.' % (host, type(reason).__name__)
        problem = Problem(message,502)
        problem.transient = isinstance(reason, (TimeoutError, ConnectionError)) or (
            isinstance(reason, socket.gaierror) and reason.errno == socket.EAI_AGAIN)
        raise problem from None


def models(data):
    provider,profile=validate(data,False,connect_endpoint=True)
    result=request(provider,profile,'/v1/models?limit=1000' if provider=='anthropic' else '/models')
    rows=result.get('data',[]) if isinstance(result,dict) else None
    if not isinstance(rows,list):
        from studio import Problem
        raise Problem('The endpoint did not return a model list.',502)
    rows=model_catalog.filter_rows(rows,provider=provider,context_window=profile['contextWindow'])
    return {'models':[{'id':x['id'],'name':x.get('display_name',x['id']),**model_catalog.public_metadata(x)} for x in rows],
            'hasMore':bool(result.get('has_more'))}


def connection_catalog(provider, profile):
    """An explicit Connect always makes a fresh request, before replacing settings."""
    from studio import Problem
    result=request(provider,profile,'/v1/models?limit=1000' if provider=='anthropic' else '/models',timeout=25)
    rows=result.get('data') if isinstance(result,dict) else None
    if not isinstance(rows,list):
        raise Problem('The endpoint did not return a model list. Check the API endpoint.',502)
    return model_catalog.filter_rows(rows,provider=provider,context_window=profile['contextWindow'])


def verify_connection(provider, profile):
    from studio import Problem
    rows=connection_catalog(provider,profile)
    if not any(isinstance(item,dict) and item.get('id')==profile['model'] for item in rows):
        raise Problem('The selected model is unavailable or unsuitable for this demo. Choose a conversational model with enough context.',502)
    return rows


def apply_to_config(config, provider, profile):
    ref='bac-'+provider+'/'+profile['model']
    config.setdefault('models',{}).setdefault('providers',{})['bac-'+provider]={
        **secrets.native_route(provider,profile),'api':PROVIDERS[provider]['api'],
        'models':[{'id':profile['model'],'name':profile['model'],'input':['text','image'],'reasoning':False,
                   'contextWindow':profile['contextWindow'],'contextTokens':profile['contextWindow'],'maxTokens':output_token_limit(profile['contextWindow']),
                   'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}}]}
    config['agents']['defaults']['model']={'primary':ref,'fallbacks':[]}
    config['agents']['defaults']['timeoutSeconds']=AGENT_TIMEOUT_SECONDS
    import team_models
    for agent_id,agent in config['agents']['entries'].items():
        if team_models.role_for(agent_id) is not None or agent.get('model', '').startswith('bac-connection-'):continue
        agent['model']=ref;agent['modelPolicy']={'allow':[ref]}
        agent['identity']={'theme':'bac-model-'+str(time.time_ns())}
    return apply_context_limits(team_models.apply(config))


def clean_event(location):
    from studio import Problem
    if not isinstance(location,dict):raise Problem('Enter the event location.')
    clean={}
    for k,default in DEFAULT_EVENT.items():
        value=location.get(k,default)
        if not isinstance(value,str) or len(value)>{'region':80,'city':80,'language':40,'venue':120}[k] or any(ord(x)<32 for x in value) or (k not in ('venue','region') and not value.strip()):
            raise Problem('Enter a valid '+k+'.')
        clean[k]=value.strip()
    return clean


def persist(settings):
    settings=copy.deepcopy(settings)
    for profile in settings.get('profiles',{}).values():profile.pop('apiKey',None)
    path().parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path().with_suffix('.new'),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(settings,f)
    os.chmod(path().with_suffix('.new'),0o600);os.replace(path().with_suffix('.new'),path())


def save(studio, data):
    from studio import Problem
    import agent_runtime as runtime
    if data.get('section') == 'location':
        return save_location(studio, data)
    event_only=data.get('section') == 'event'
    provider,profile=(None,None) if event_only else validate(data)
    clean=clean_event(data.get('event',event()))
    verified=not event_only and data.get('verifyConnection') is True
    if verified:verify_connection(provider,profile)
    with studio.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running','waiting','stopping') LIMIT 1").fetchone():
            raise Problem('Finish or cancel pending missions before changing shared settings.',409)
        if event_only:
            with runtime.config_lock():
                settings=read();settings['event']=clean
                persist(settings)
            studio.status_cache=(0,{})
            return public()
        with runtime.config_lock():
            original=c.read_json(runtime.config_path(),None)
            config=apply_to_config(copy.deepcopy(original or runtime.initial_config()),provider,profile)
            settings=read();settings['provider']=provider;settings['event']=clean;settings.setdefault('profiles',{})[provider]=profile
            runtime.save_config(config)
            try:
                persist(settings)
            except Exception:
                if original is not None:runtime.save_config(original)
                else:runtime.config_path().unlink(missing_ok=True)
                raise
        secrets.put(secret_key(provider),profile,data.get('_credentialSession','direct'))
        if verified:
            global _availability
            _availability=(availability_signature(provider,profile),time.monotonic(),True)
        studio.provisioned.clear();studio.status_cache=(0,{})
        # Model reconnect invalidates native registration. Autonomous agents have
        # no next chat to trigger lazy provisioning, so durably warm them again.
        for row in db.execute('SELECT id,profile FROM agents WHERE deleting=0 AND profile IS NOT NULL').fetchall():
            saved_profile=json.loads(row['profile'])
            if 'radar' in saved_profile.get('skills',[]):
                studio.queue_agent_preparation(db,row['id'],saved_profile)
    studio.signal.set()
    return public()


_start_lock = threading.Lock()
_gateway_process = None


def start_gateway():
    # Settings requests can overlap while a gateway is still binding its port.
    with _start_lock:
        return _start_gateway()


def _start_gateway():
    """Start only this app's installed runtime; never install software from a web request."""
    import agent_runtime as runtime
    from studio import Problem
    try:
        runtime.gateway('/v1/models',timeout=2)
        return {'started':True}
    except RuntimeError:pass
    binary=runtime.root()/'package/node_modules/.bin/openclaw'
    if not binary.exists():raise Problem('Install the agent runtime once: ./bac dev runtime setup',409)
    if not runtime.config_path().exists():raise Problem('Save your model settings first.',409)
    if os.environ.get('BAC_CONTAINER') == '1':
        # The container supervisor owns this process, including restart and shutdown.
        return {'started':True,'message':'Agent runtime is starting. Check Docker logs if it remains unavailable.'}
    if sys.platform == 'linux' and c.systemd_available():
        # Use the same host service as ./bac dev start so stop/logs/reboot remain coherent.
        from ops_runtime import start
        start()
        return {'started':True,'message':'Agent runtime service is starting.'}
    global _gateway_process
    if _gateway_process is not None and _gateway_process.poll() is None:
        return {'started':True,'message':'Agent runtime is starting.'}
    # A bound port could belong to another app; do not try to replace it.
    import socket
    with socket.socket() as sock:
        port=runtime.gateway_port()
        if sock.connect_ex(('127.0.0.1',port))==0:raise Problem(f'Port {port} is already in use by another runtime.',409)
    log=runtime.root()/'gateway.log'
    fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    with os.fdopen(fd,'a') as output:
        # Detached runtimes outlive removable development checkouts. Native tools
        # call process.cwd(), so keep it in the persistent runtime directory.
        _gateway_process = subprocess.Popen([str(binary),'gateway','run'],cwd=runtime.root(),env=runtime.environment(),stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True)
    return {'started':True,'message':'Agent runtime is starting.'}


_availability = (None, 0, False)
def availability_signature(provider,profile):
    import hashlib
    return hashlib.sha256(json.dumps([provider,profile],sort_keys=True).encode()).hexdigest()


def model_available():
    global _availability
    settings=read();provider=settings['provider']
    profile=settings.get('profiles',{}).get(provider,{'baseUrl':PROVIDERS['local']['baseUrl'],'apiKey':'','model':'bac-local'})
    profile={**profile, 'apiKey':secrets.get(secret_key(provider)).get('apiKey','')}
    if (provider!='local' or profile.get('requiresKey')) and not profile['apiKey']:return False
    # Cache success for one minute, but retry transient failures after five seconds.
    signature=availability_signature(provider,profile)
    if _availability[0]==signature and time.monotonic()-_availability[1]<(60 if _availability[2] else 5):return _availability[2]
    started=time.monotonic()
    try:
        response=request(provider,profile,'/v1/models?limit=1000' if provider=='anthropic' else '/models',timeout=3)
        rows=model_catalog.filter_rows(response.get('data',[]),provider=provider,context_window=profile.get('contextWindow',32768))
        available=any(item.get('id')==profile['model'] for item in rows)
    except Exception:available=False
    # A slow background probe must not overwrite a newer successful Connect.
    if _availability[1]<=started:_availability=(signature,time.monotonic(),available)
    elif _availability[0]==signature:return _availability[2]
    return available
