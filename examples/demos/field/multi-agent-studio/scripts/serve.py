#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0

"""Multi-Agent Studio: local UI, participant API and shared OpenClaw task queue."""
import argparse
import base64
import functools
import hashlib
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import threading
from urllib.parse import urlparse, parse_qs

from app_publish import bundle_lock
from studio import Studio, Problem, safe_file
from diagnostics import REQUEST, traced_request


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        if getattr(self, '_diag_request', None):self.send_header('X-BaC-Request-ID', self._diag_request)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        super().end_headers()

    def log_message(self, format, *args):
        # API paths may carry file names; never log request bodies or cookies.
        if self.path != '/health' and not self.path.startswith(('/api/', '/survey/')):
            super().log_message(format, *args)

    def send_head(self):
        if urlparse(self.path).path in ('/', '/index.html'):
            with bundle_lock(self.server.app_root):
                return super().send_head()
        return super().send_head()

    def json_response(self, value, status=200, cookie=None, conditional=False):
        self._diag_status = status
        body = json.dumps(value).encode()
        etag = '"' + hashlib.sha256(body).hexdigest() + '"' if conditional else None
        if etag and self.headers.get('If-None-Match') == etag:
            self._diag_status = 304
            self.send_response(304)
            self.send_header('ETag', etag)
            self.end_headers()
            return
        self.send_response(status)
        if etag:
            self.send_header('ETag', etag)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        if cookie:
            self.send_header('Set-Cookie', 'bac_session=' + cookie + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000')
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        host = urlparse('http://' + self.headers.get('Host', '')).hostname
        if host in ('localhost', socket.gethostname().lower(), socket.gethostname().lower() + '.local'):
            return True
        try:
            return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError):
            return False

    def is_operator(self):
        # The demo's supported host addresses have the same controls on LAN
        # clients and localhost. Session, Host, origin and CSRF checks still apply.
        return self.host_ok()

    def require_operator(self):
        if not self.is_operator():
            raise Problem('Use the host IP address or localhost.',403)

    def participant(self, create=False):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except Exception:
            raise Problem('Invalid session.', 401)
        token = cookie['bac_session'].value if 'bac_session' in cookie else None
        view = self.headers.get('X-BaC-Browser-View')
        if view is not None:
            return self.server.studio.browser_access.session(token, view, create)
        if create:
            return self.server.studio.session(token)
        with self.server.studio.db() as db:
            row = db.execute('SELECT * FROM participants WHERE token=?', (token,)).fetchone()
        if not row or not self.server.studio.touch_session(row['id']):
            raise Problem('Open the Multi-Agent Studio page to start a session.', 401)
        return dict(row), False

    @traced_request
    def do_GET(self):
        if self.path.startswith('/survey/'):
            return self.json_response({'error':'This workflow is retired.'},410)
        if self.path == '/health':
            with bundle_lock(self.server.app_root):
                try:
                    app_revision = json.loads(self.server.app_version_file.read_text()).get('appRevision', '')
                except (OSError, ValueError):
                    app_revision = ''
            return self.json_response({'app': 'bac-demo', **self.server.build_info,
                                       'appRevision': app_revision, 'mode': 'agent-studio'})
        if not self.path.startswith('/api/'):
            return super().do_GET()
        try:
            if not self.host_ok():
                raise Problem('Use the host IP address or localhost.', 403)
            parsed = urlparse(self.path)
            studio = self.server.studio
            row, new = self.participant(create=parsed.path == '/api/session')
            REQUEST.set({**REQUEST.get(), 'participant': row['id']})
            if parsed.path == '/api/diagnostics':
                self.require_operator()
                return self.json_response(studio.diagnostics.report(row['id'], full=parse_qs(parsed.query).get('full') == ['1'], studio=studio))
            owner = studio.resolve_agent(row['id'], self.headers.get('X-BaC-Agent'))
            from scenarios import validate as validate_scenario
            scenario = validate_scenario(self.headers.get('X-BaC-Scenario', 'plan'))
            if parsed.path in ('/api/session', '/api/state'):
                studio.heartbeat.presence(row['id'], self.headers.get('X-BaC-Key-Session', ''))
            if parsed.path == '/api/session':
                if self.headers.get('X-BaC-Browser-View'):
                    studio.start_shell_preparation(owner)
                return self.json_response({'csrf': row['csrf'], 'canConfigure': self.is_operator(), 'runtime': studio.runtime_status(), **studio.state(owner, scenario)}, cookie=row['token'] if new else None)
            if parsed.path == '/api/state':
                return self.json_response(studio.state(owner, scenario), conditional=True)
            if parsed.path == '/api/event-catalog':
                raise Problem('This workflow is retired.',410)
            if parsed.path == '/api/survey-report':
                raise Problem('This workflow is retired.',410)
            if parsed.path == '/api/settings':
                self.require_operator()
                import runtime_settings
                return self.json_response(runtime_settings.public(row['id']+':'+self.headers.get('X-BaC-Key-Session','missing')))
            if parsed.path == '/api/telemetry':
                import telemetry
                return self.json_response(telemetry.report(studio, owner))
            if parsed.path == '/api/settings/connections':
                self.require_operator()
                import model_connections
                return self.json_response(model_connections.public_for(studio,owner))
            if parsed.path == '/api/runtime':
                return self.json_response(studio.runtime_status(retry=parse_qs(parsed.query).get('retry') == ['1']))
            if parsed.path == '/api/security':
                from security_lab import public_report
                return self.json_response(public_report(studio.directory))
            if parsed.path == '/api/agent-policy':
                return self.json_response(studio.policy_report(owner))
            if parsed.path == '/api/crew-policy':
                query = parse_qs(parsed.query, keep_blank_values=True)
                values = query.get('role', [])
                if set(query) != {'role'} or len(values) != 1 or not values[0].isascii() or not values[0].isdecimal():
                    raise Problem('Choose one valid crew member.')
                return self.json_response(studio.crew_policy_report(studio.crew_owner(owner, scenario), int(values[0])))
            if parsed.path == '/api/evidence':
                return self.json_response(studio.evidence(studio.job_owner(owner, parse_qs(parsed.query).get('id',[''])[0]), parse_qs(parsed.query).get('id',[''])[0]))
            if parsed.path == '/api/model-reasoning':
                import model_reasoning
                query=parse_qs(parsed.query,keep_blank_values=True)
                if set(query)!={'id'} or len(query['id'])!=1:raise Problem('Choose one mission.')
                job=query['id'][0]
                return self.json_response(model_reasoning.report(studio,studio.job_owner(owner,job),job))
            if parsed.path == '/api/agent-documents':
                from agent_documents import read_documents
                query=parse_qs(parsed.query,keep_blank_values=True)
                if set(query)-{'role'} or len(query.get('role',[]))>1:
                    raise Problem('Choose one agent to inspect.')
                role=None
                if 'role' in query:
                    value=query['role'][0]
                    if not value.isascii() or not value.isdecimal():raise Problem('Choose a valid crew member.')
                    role=int(value)
                return self.json_response(read_documents(studio,studio.crew_owner(owner, scenario) if role is not None else owner,role))
            if parsed.path == '/api/workspace-files':
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {'workspace', 'view'} or len(query.get('workspace', [])) > 1 or query.get('view', ['all']) not in (['all'], ['uploads']):
                    raise Problem('Choose one workspace.')
                target, role = studio.browsing_workspace(owner, scenario, query.get('workspace', ['personal'])[0])
                return self.json_response({'files': studio.files(target, role, recursive=True, uploads_only=query.get('view') == ['uploads']) if target else []})
            if parsed.path == '/api/file':
                name = parse_qs(parsed.query).get('path', [''])[0]
                if not (name.startswith(('inbox/', 'artifacts/')) or name in ('MEMORY.md', 'IDENTITY.md', 'SOUL.md', 'AGENTS.md')):
                    raise Problem('File is not available.', 404)
                job_id = parse_qs(parsed.query).get('job',[''])[0]
                query = parse_qs(parsed.query, keep_blank_values=True)
                if 'workspace' in query:
                    if job_id or len(query['workspace']) != 1:
                        raise Problem('Choose one file workspace.')
                    target, role = studio.browsing_workspace(owner, scenario, query['workspace'][0])
                    if not target:
                        raise Problem('File is not available.', 404)
                    path = safe_file(studio.workspace(target, role), name, True)
                else:
                    path = safe_file(studio.workspace(studio.job_owner(owner,job_id)),name,True) if job_id else studio.available_file(owner, name, scenario)
                if path.suffix.lower() in ('.png','.jpg','.webp'):
                    mime={'.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp'}[path.suffix.lower()]
                    return self.json_response({'path':name,'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode(),'mime':mime})
                if path.suffix.lower()=='.pdf':
                    return self.json_response({'path':name,'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode(), 'mime':'application/pdf'})
                if path.suffix.lower()=='.pptx':
                    return self.json_response({'path':name,'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode(),'mime':'application/vnd.openxmlformats-officedocument.presentationml.presentation'})
                if path.suffix.lower() in ('.xlsx','.eml'):
                    return self.json_response({'path':name,'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode(), 'mime':'message/rfc822' if path.suffix.lower()=='.eml' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})
                return self.json_response({'path': name, 'content': path.read_text(encoding='utf-8')})
            raise Problem('Not found.', 404)
        except Problem as error:
            self._diag_error = error
            self.json_response({'error': str(error)}, error.status)
        except (UnicodeError, ValueError) as error:
            self._diag_error = error
            self.json_response({'error': 'Invalid data.'}, 400)

    @traced_request
    def do_POST(self):
        try:
            if not self.host_ok():
                raise Problem('Use the host IP address or localhost.', 403)
            origin = self.headers.get('Origin')
            if origin and urlparse(origin).netloc != self.headers.get('Host'):
                raise Problem('Cross-origin requests are not accepted.', 403)
            if self.path.startswith('/survey/'):
                raise Problem('This workflow is retired.',410)
            row, _ = self.participant()
            REQUEST.set({**REQUEST.get(), 'participant': row['id']})
            if not secrets.compare_digest(self.headers.get('X-BaC-CSRF', ''), row['csrf']):
                raise Problem('Refresh the page to renew your session.', 403)
            size = int(self.headers.get('Content-Length', '0'))
            # A 10 MB text file can expand sixfold when JSON escapes control
            # characters. The decoder still enforces the actual 10 MB file cap.
            limit = 64 * 1024 * 1024 if self.path == '/api/upload' else 15 * 1024 * 1024 if self.path == '/api/jobs' else 512000
            if not 0 < size <= limit:
                raise Problem('Request is too large or empty.', 413)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise Problem('Expected a JSON object.')
            studio = self.server.studio
            owner = studio.resolve_agent(row['id'], self.headers.get('X-BaC-Agent'))
            from scenarios import validate as validate_scenario
            scenario = validate_scenario(self.headers.get('X-BaC-Scenario', 'plan'))
            lease = self.headers.get('X-BaC-Key-Session','')
            if not lease or len(lease)>100:lease='missing'
            data['_credentialSession']=row['id']+':'+lease
            if self.path == '/api/credential-session':
                import session_secrets
                studio.heartbeat.presence(row['id'], self.headers.get('X-BaC-Key-Session', ''),
                                          end=bool(data.get('end')), open_task=data.get('openTask'),
                                          revision=data.get('viewRevision'), view_state=data.get('viewState'))
                if data.get('end'):session_secrets.release(data['_credentialSession'])
                else:session_secrets.renew(data['_credentialSession'])
                if data.get('end'):
                    studio.browser_access.release(row['id'], self.headers.get('X-BaC-Browser-View', ''))
                studio.status_cache=(0,{})
                return self.json_response({'ok':True})
            if self.path in ('/api/settings/connections', '/api/settings/connections/preferences', '/api/settings/connections/check', '/api/settings/connections/models'):
                self.require_operator()
                import model_connections
                if self.path.endswith('/models'):return self.json_response(model_connections.models(data))
                if self.path.endswith('/preferences'):return self.json_response(model_connections.preferences(studio,data,studio.crew_owner(owner,scenario),participant=owner))
                if self.path.endswith('/check'):return self.json_response(model_connections.public(refresh=True))
                return self.json_response(model_connections.configure(studio,data))
            if self.path in ('/api/settings/scenario-model', '/api/settings/scenario-models'):
                self.require_operator()
                import scenario_models
                if self.path.endswith('/scenario-models'):
                    return self.json_response(scenario_models.models(data))
                return self.json_response(scenario_models.configure(studio, studio.crew_owner(owner, scenario), data))
            if self.path in ('/api/settings','/api/settings/models','/api/settings/start','/api/settings/team-model'):
                self.require_operator()
                import runtime_settings
                if self.path == '/api/settings/team-model':
                    import team_models
                    return self.json_response(team_models.configure(studio,data))
                if self.path == '/api/settings/models':return self.json_response(runtime_settings.models(data))
                if self.path == '/api/settings/start':return self.json_response(runtime_settings.start_gateway())
                return self.json_response(runtime_settings.save(studio,data))
            if self.path in ('/api/prepare-demo','/api/event-plan','/api/survey-replan') or (self.path=='/api/jobs' and data.get('kind') in ('crew','prepare')):
                raise Problem('This workflow is retired. Use Open Task.',410)
            if self.path == '/api/team-model':
                import team_models
                return self.json_response(team_models.select(studio,studio.crew_owner(owner, scenario),data))
            if self.path == '/api/agent-documents':
                from agent_documents import save_documents
                from studio import CREW_CATALOG
                role = data.get('role')
                if role is not None and (type(role) is not int or role not in range(len(CREW_CATALOG))):
                    raise Problem('Choose a valid crew member.')
                return self.json_response(save_documents(studio, studio.crew_owner(owner, scenario) if role is not None else owner, data, role))
            if self.path == '/api/bac-reset' and data.get('scope', 'scenario') not in ('scenario', 'all'):
                raise Problem('Choose whether to reset this scenario or all scenarios.')
            routes = {
                '/api/heartbeat': lambda: studio.heartbeat.control(owner, data),
                '/api/agents': lambda: studio.add_agent(row['id'], data),
                '/api/onboard': lambda: studio.onboard(owner, data),
                '/api/profile': lambda: studio.configure(owner, data),
                '/api/agent-model': lambda: studio.select_agent_model(owner, data),
                '/api/delete-agent': lambda: studio.delete_agent(owner, data, enqueue_only=True),
                '/api/agent-policy': lambda: studio.policy_change(owner, data),
                '/api/crew-policy': lambda: studio.crew_policy_change(studio.crew_owner(owner, scenario), data),
                '/api/jobs': lambda: studio.enqueue(studio.crew_owner(owner, scenario) if data.get('kind')=='crew-chat' else owner, data),
                '/api/upload': lambda: studio.upload(studio.crew_owner(owner, scenario) if 'crewRole' in data else owner, data),
                '/api/task-policy-decision': lambda: __import__('task_policy').decide(studio, studio.job_owner(owner, data.get('id')), data.get('id'), data.get('request'), data.get('action')),
                '/api/decision': lambda: studio.decision(studio.job_owner(owner, data.get('id')), data.get('id'), data.get('action')),
                '/api/ask-reaction': lambda: studio.retry_reaction(studio.job_owner(owner, data.get('id')), data, first_request=True),
                '/api/retry-reaction': lambda: studio.retry_reaction(studio.job_owner(owner, data.get('id')), data),
                '/api/reset': lambda: studio.reset_board(owner),
                '/api/crew-chat-reset': lambda: studio.reset_crew_chats(studio.crew_owner(owner, scenario)),
                '/api/bac-reset': lambda: studio.reset_crew_chats(owner if data.get('scope')=='all' else studio.crew_owner(owner, scenario), reset_event=True),
            }
            if self.path not in routes:
                raise Problem('Not found.', 404)
            self.json_response(routes[self.path]())
        except Problem as error:
            self._diag_error = error
            self.json_response({'error': str(error)}, error.status)
        except (UnicodeError, ValueError, TypeError) as error:
            self._diag_error = error
            self.json_response({'error': 'Invalid request data.'}, 400)


def create_server(host='127.0.0.1', port=8080, studio=None):
    import session_secrets, ops_common
    if studio is None:
        session_secrets.purge_legacy(ops_common.home())
        import model_connections
        model_connections.initialize()
    root = Path(__file__).resolve().parents[1] / 'app'
    server = ThreadingHTTPServer((host, port), functools.partial(Handler, directory=str(root)))
    server.studio = studio or Studio()
    server.build_info = server.studio.diagnostics.build
    server.app_root = root
    server.app_version_file = root / 'version.json'
    return server


def main():
    import signal
    def shutdown(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, shutdown)
    parser = argparse.ArgumentParser(description='Run Multi-Agent Studio.')
    parser.add_argument('--host', default=os.environ.get('HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8080')))
    args = parser.parse_args()
    # Docker imports as root at startup; a source preview can use its own private file.
    config_file = Path(__file__).resolve().parents[1] / 'api.json'
    if not os.environ.get('BAC_CONTAINER'):
        import api_key_setup
        import provider_keys
        if config_file.is_file() and not config_file.is_symlink():
            if api_key_setup.main([str(config_file), '--optional']):
                raise SystemExit(1)
        else:
            provider_keys.private_path().unlink(missing_ok=True)
    import resource_links
    resource_links.filter_page(Path(__file__).resolve().parents[1] / 'app/index.html')
    try:
        server = create_server(args.host, args.port)
    except OSError as error:
        parser.exit(1, f'Cannot start server: {error}. Try --port 8081.\n')
    print(f'Multi-Agent Studio: http://{args.host}:{server.server_port}', flush=True)
    print('Build: ' + json.dumps(server.build_info, sort_keys=True), flush=True)
    print('Connect a model in Settings to run OpenClaw tasks.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.studio.stop.set()
        if hasattr(server.studio, 'heartbeat_worker'):server.studio.heartbeat_worker.join(timeout=15)
        server.server_close()


if __name__ == '__main__':
    main()
