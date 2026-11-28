# SPDX-License-Identifier: Apache-2.0

"""Short-lived, process-memory credentials. No filesystem persistence."""
import copy
from contextlib import contextmanager
import hashlib
import re
import secrets
import socket
import ssl
import errno
import logging
import switchyard_vision
import json
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TTL = 90
_lock = threading.RLock()
_values = {}
_closed = {}
_proxy = None
_local_routes = {}
_routing = {}
_routing_marker = re.compile(r'\[\[bac-route:([a-f0-9]{32})\]\]\n')


@contextmanager
def routing(prompt, identity, *, stage=None, weather_answer=False):
    """Carry an immutable task identity through OpenClaw, never to the model."""
    state = {'id': identity, 'model': None, 'stage': 'team' if stage == 'team' else 'lounge'}
    if weather_answer and stage == 'lounge':
        state['weatherAnswer'] = True
    if identity is None and stage is None:
        yield prompt, state
        return
    key = secrets.token_hex(16)
    with _lock:_routing[key] = state
    try:
        yield '[[bac-route:' + key + ']]\n' + prompt, state
    finally:
        with _lock:_routing.pop(key, None)


def routing_request(payload, *, chat_completions=False):
    if not payload:return payload, None
    value = json.loads(payload)
    if not isinstance(value, dict):return payload, None
    keys, latest_keys = [], []
    def clean(text):
        if not isinstance(text, str):return text
        keys.extend(_routing_marker.findall(text))
        return _routing_marker.sub('', text)
    # OpenClaw can append user-role context after the tagged prompt. Consecutive
    # user messages before the same answer belong to the same input batch.
    adjacent_user = False
    for message in value.get('messages', []):
        if not isinstance(message, dict) or message.get('role') != 'user':
            adjacent_user = False
            continue
        first = len(keys)
        content = message.get('content')
        if isinstance(content, str):message['content'] = clean(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'text':part['text'] = clean(part.get('text'))
        message_keys = keys[first:]
        if message_keys or not adjacent_user:
            latest_keys = message_keys
        adjacent_user = True
    state = None
    with _lock:current = _routing.get(latest_keys[-1]) if latest_keys else None
    if value.get('model') == 'switchyard':
        state = current if latest_keys else {'id': None, 'model': None, 'stage': 'lounge'}
        if state is None:raise ValueError('The routing request has ended.')
    elif current is not None:
        # A fixed model keeps its selection; only the captured stage is carried.
        state = current
    # Only the current, server-tagged Lounge turn can have verified weather data.
    # No more tools are needed to phrase its reply. Keep instructions and history intact.
    if chat_completions and current and current.get('weatherAnswer'):
        for field in ('tools', 'tool_choice', 'parallel_tool_calls'):
            value.pop(field, None)
    return json.dumps(value).encode() if keys else payload, state


def put(key, value, lease):
    with _lock:
        if lease in _closed:
            from studio import Problem
            raise Problem('This credential session has ended. Refresh and reconnect.',409)
        _values[str(key)] = (copy.deepcopy(value), lease, time.monotonic() + TTL)


def get(key, lease=None):
    with _lock:
        item = _values.get(str(key))
        if not item:return {}
        value, owner, expires = item
        if expires <= time.monotonic():
            _values.pop(str(key), None);return {}
        if lease is not None and owner != lease:return {}
        return copy.deepcopy(value)


def renew(lease):
    with _lock:
        for key,(value,owner,expires) in list(_values.items()):
            if expires <= time.monotonic():_values.pop(key,None)
            elif owner == lease:_values[key]=(value,owner,time.monotonic()+TTL)


def release(lease):
    with _lock:
        _closed[lease]=time.monotonic()+300
        for key,(_,owner,_) in list(_values.items()):
            if owner == lease:_values.pop(key,None)


def remove(key, lease=None):
    with _lock:
        item = _values.get(str(key))
        if item and (lease is None or item[1] == lease):
            _values.pop(str(key), None)


def _reap():
    while True:
        time.sleep(5)
        with _lock:
            for lease,expires in list(_closed.items()):
                if expires <= time.monotonic():_closed.pop(lease,None)
            for key,(_,_,expires) in list(_values.items()):
                if expires <= time.monotonic():_values.pop(key,None)
threading.Thread(target=_reap,daemon=True,name='credential-expiry').start()


class CredentialExpired(ValueError):
    pass


TRANSPORT_MESSAGES = {
    'model-credential-expired': 'The model API session credential has expired. Reconnect the model API.',
    'model-dns-failed': 'The host could not resolve the model API address. Check network, DNS and VPN connectivity.',
    'model-connection-timeout': 'The model API connection timed out. The network or model service may be slow; an internet outage is not confirmed.',
    'model-tls-failed': 'The secure connection to the model API failed. Check certificates and any network proxy.',
    'model-network-unreachable': 'The host network could not reach the model API. Check the internet connection and VPN.',
    'model-connection-failed': 'The host could not establish or maintain its connection to the model API. Check network, VPN and service availability.',
    'model-proxy-failed': 'The local model API connection failed. Check the host runtime logs.',
}


def connection_failure(error):
    """Fixed, credential-free diagnostics for the model transport only."""
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    status,code=502,'model-proxy-failed'
    if isinstance(error, CredentialExpired):status,code=401,'model-credential-expired'
    elif isinstance(reason, socket.gaierror):code='model-dns-failed'
    elif isinstance(reason, (TimeoutError, socket.timeout)):status,code=504,'model-connection-timeout'
    elif isinstance(reason, ssl.SSLError):code='model-tls-failed'
    elif isinstance(reason, OSError) and reason.errno in (errno.ENETUNREACH, errno.ENETDOWN, errno.EHOSTUNREACH):code='model-network-unreachable'
    elif isinstance(reason, ConnectionError) or isinstance(error, urllib.error.URLError):code='model-connection-failed'
    return status,code,TRANSPORT_MESSAGES[code]


class Proxy(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):self.forward()
    def do_POST(self):self.forward()
    def forward(self):
        import runtime_settings as settings
        # No credentials from the gateway are forwarded. Destinations come only from validated profiles.
        sent=False
        collector=None
        complete=False
        try:
            if self.headers.get('Authorization')!='Bearer session-only' and self.headers.get('x-api-key')!='session-only':raise ValueError()
            _, prefix, provider, suffix = self.path.split('/',3)
            with _lock:local_base = _local_routes.get(provider)
            if prefix!='provider':raise ValueError()
            if local_base:
                # Endpoint-bound routes for explicitly configured keyless local
                # servers. Never fall back here when a credential expires.
                profile={'baseUrl':local_base,'apiKey':''}
                provider='local'
            elif provider.startswith('file-'):
                import provider_keys
                provider, profile = provider_keys.resolve_route(provider)
            elif provider == 'team':
                from team_models import credentials
                profile = credentials()
            elif provider in settings.PROVIDERS:
                profile=get(settings.secret_key(provider))
            else:
                raise ValueError()
            provider = 'nvidia' if provider == 'team' else provider
            if not profile:raise CredentialExpired()
            base=urllib.parse.urlsplit(profile['baseUrl'])
            path='/'+suffix
            if not path.startswith(base.path.rstrip('/')+'/'):raise ValueError()
            relative=path[len(base.path):]
            if relative.split('?')[0] not in ['/models','/chat/completions','/responses','/v1/models','/v1/messages','/v1/messages/count_tokens']:raise ValueError()
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=8*1024*1024:raise ValueError()
            payload=self.rfile.read(size) if size else None
            import model_reasoning
            payload,collector=model_reasoning.request(payload,provider,base_url=profile['baseUrl'])
            payload,routing_state=routing_request(payload, chat_completions=relative.split('?')[0] == '/chat/completions')
            headers={'Content-Type':'application/json','Accept':self.headers.get('Accept','application/json')}
            if provider=='anthropic':
                headers['x-api-key']=profile['apiKey'];headers['anthropic-version']=self.headers.get('anthropic-version','2023-06-01')
                if self.headers.get('anthropic-beta'):headers['anthropic-beta']=self.headers['anthropic-beta']
            elif profile['apiKey']:headers['Authorization']='Bearer '+profile['apiKey']
            destination=profile['baseUrl']+relative
            opener=settings.provider_opener(provider)
            automatic = routing_state is not None and json.loads(payload).get('model') == 'switchyard'
            if automatic:
                import switchyard_router
                if provider != 'nvidia' or not switchyard_router.nvidia_endpoints.supported(profile['baseUrl']):
                    raise ValueError('Switchyard requires a supported NVIDIA NIM API endpoint.')
                import model_connections
                inventory = model_connections.status('api')
                rows = inventory.get('models', []) if inventory.get('baseUrl') == profile['baseUrl'] else []
                routing_models = switchyard_router.resolve_catalog_models(
                    switchyard_router.configured_models(profile['baseUrl']), {row['id'] for row in rows})
                payload=switchyard_router.prepare_request(payload,routing_state,routing_models,profile=profile,rows=rows)
                destination=switchyard_router.endpoint(routing_models,base_url=profile['baseUrl'])+relative
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                if routing_state['id']:headers['x-switchyard-session-id']=routing_state['id']
            elif provider == 'nvidia' and payload and relative.split('?')[0] == '/chat/completions':
                import switchyard_router
                if switchyard_router.nvidia_endpoints.supported(profile['baseUrl']):
                    value = json.loads(payload)
                    options = switchyard_router.thinking_options(value.get('model'), (routing_state or {}).get('stage'))
                    if options:
                        value['chat_template_kwargs'] = {**value.get('chat_template_kwargs', {}), **options['chat_template_kwargs']}
                        value.pop('thinking_token_budget', None)
                        value.update({k:v for k,v in options.items() if k != 'chat_template_kwargs'})
                        payload = json.dumps(value).encode()
            request=urllib.request.Request(destination,data=payload,headers=headers,method=self.command)
            with opener.open(request,timeout=180) as response:
                if automatic:
                    selected=response.headers.get('x-model-router-selected-model')
                    if selected in (routing_models['efficient'],routing_models['capable']):
                        routing_state['model']=selected
                        if collector:collector.routed_to(selected, routing_state['mode'])
                if collector:collector.streaming='text/event-stream' in response.headers.get('Content-Type','')
                self.send_response(200);self.send_header('Content-Type',response.headers.get('Content-Type','application/json'));self.send_header('Connection','close');self.end_headers();sent=True
                while chunk := response.read1(65536):
                    self.wfile.write(chunk);self.wfile.flush()
                    if collector:collector.feed(chunk)
                complete=True
                self.close_connection=True
        except switchyard_vision.ImageRoutingError as error:
            body = json.dumps({'error': {'message': str(error)}}).encode()
            self.send_response(error.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers();self.wfile.write(body)
        except urllib.error.HTTPError as error:
            if sent:
                self.close_connection=True
                return
            # Preserve actionable provider failures instead of calling every 400/429
            # an expired credential. Never expose its raw body or headers.
            detail = settings.provider_error_detail(error, profile.get('apiKey',''))
            message = 'Model provider returned HTTP %s.' % error.code
            if detail:message += ' ' + detail
            body = json.dumps({'error':{'message':message}}).encode()
            try:
                self.send_response(error.code)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            except OSError:pass
            finally:error.close()
        except Exception as error:
            # Never log exception text: URLs and headers may contain credentials.
            status,code,message=connection_failure(error)
            logging.warning('Model transport failure: %s (%s)',code,type(error).__name__)
            if sent:
                self.close_connection=True
                return
            body=json.dumps({'error':{'code':code,'message':code+': '+message}}).encode()
            try:
                self.send_response(status);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            except OSError:pass
        finally:
            if collector:collector.finish(complete)


def proxy_url(provider, base_url, *, keyless=False):
    global _proxy
    with _lock:
        if keyless:
            if provider!='local':raise ValueError('Only local endpoints may be keyless.')
            provider='local-'+hashlib.sha256(base_url.encode()).hexdigest()[:24]
            _local_routes[provider]=base_url
        if _proxy is None:
            _proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
            threading.Thread(target=_proxy.serve_forever,daemon=True,name='credential-proxy').start()
        return 'http://127.0.0.1:%d/provider/%s%s' % (_proxy.server_port,provider,urllib.parse.urlsplit(base_url).path)


def native_route(provider, profile):
    """Use the same observation path for keyed APIs and configured local servers."""
    if provider=='local' and not profile.get('apiKey') and not profile.get('requiresKey'):
        return {'baseUrl':proxy_url(provider,profile['baseUrl'],keyless=True),'apiKey':'session-only'}
    if profile.get('apiKey') or (provider=='local' and profile.get('requiresKey')):
        return {'baseUrl':proxy_url(provider,profile['baseUrl']),'apiKey':'session-only'}
    return {'baseUrl':profile['baseUrl'],'apiKey':'local-only'}


def observes(base_url):
    """Only our own live relay can remove a transport marker before inference."""
    parsed=urllib.parse.urlsplit(base_url or '')
    return bool(_proxy and parsed.hostname=='127.0.0.1' and parsed.port==_proxy.server_port
                and parsed.path.startswith('/provider/'))


def purge_legacy(home):
    """Remove previously persisted external credentials in app-owned configuration copies."""
    from pathlib import Path
    home=Path(home)
    candidates=list(home.glob('host-settings.*'))
    state=home/'openclaw/state'
    if state.exists():
        candidates += [p for p in state.rglob('*') if p.is_file() and ('.json' in p.name or p.name.endswith(('.bak','.new')))]
    removed=set()
    def scrub(value):
        if isinstance(value,dict):
            for k,v in list(value.items()):
                if (k=='apiKey' or (value.get('type')=='api_key' and k=='key')) and isinstance(v,str) and v not in ('local-only','session-only',''):
                    removed.add(v);value[k]=''
                else:scrub(v)
        elif isinstance(value,list):
            for v in value:scrub(v)
    for target in candidates:
        try:
            original=target.read_text();data=json.loads(original);scrub(data)
            updated=json.dumps(data,indent=2)
            if json.loads(original)!=data:target.write_text(updated)
        except (OSError,ValueError,UnicodeError):continue
    # Invitation credentials were previously written by the app; drop, never restore into memory.
    studio=home/'studio'
    for target in [*studio.glob('marketing-telegram-*'), studio/'telegram.json']:
        if target.suffix not in ('.json','.new'):continue
        try:
            value=json.loads(target.read_text()).get('token')
            if value:removed.add(value)
            target.unlink()
        except (OSError,ValueError):continue
    (home/'openclaw/search-enabled').unlink(missing_ok=True)
    # Redact known removed values in this app's runtime logs/backups, without displaying them.
    if removed:
        for target in (home/'openclaw').glob('*.log*'):
            try:
                original=target.read_text();updated=original
                for value in removed:updated=updated.replace(value,'[removed]')
                if updated!=original:target.write_text(updated)
            except (OSError,UnicodeError):pass
        for parent in (home/'openclaw/state',):
            if not parent.exists():continue
            for target in parent.rglob('*'):
                if not target.is_file() or not any(x in target.name for x in ('.json','.log','.bak','.new')):continue
                try:
                    original=target.read_text();updated=original
                    for value in removed:updated=updated.replace(value,'[removed]')
                    if updated!=original:target.write_text(updated)
                except (OSError,UnicodeError):continue
