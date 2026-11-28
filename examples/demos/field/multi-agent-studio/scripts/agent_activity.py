# SPDX-License-Identifier: Apache-2.0

"""Read observed tool calls from OpenClaw's native transcript, excluding hidden reasoning and file contents."""
import json
from pathlib import Path
import shlex
import re
import sqlite3
import posixpath
from contextlib import closing


HTTP_FAILURES = {400:'Bad request',401:'Authentication required',403:'Access denied',404:'Page not found',
                 408:'Request timed out',429:'Too many requests',500:'Server error',502:'Bad gateway',
                 503:'Service unavailable',504:'Gateway timed out'}

WEB_FAILURES = {'search-rate-limit': 'Search service rate limit',
                'research-budget': 'Demo research limit',
                'tool-error': 'Web tool failed; cause unconfirmed'}


def web_failure_reason(message, tool):
    """Classify failed tool results, never a model's explanation or page content."""
    details = message.get('details') or {}
    if not (message.get('isError') or details.get('status') in ('error', 'failed')):
        return None
    content = message.get('content', [])
    text = ' '.join(str(b.get('text', '')) for b in content if isinstance(b, dict) and b.get('type') == 'text')[:16000] if isinstance(content, list) else ''
    if re.match(r'^(?:Demo )?Research budget reached\.', text, re.I):
        return 'research-budget'
    if tool == 'web_search' and (web_failure_status(message) == 429 or re.search(r'\brate[ -]limit|too many requests', text, re.I)):
        return 'search-rate-limit'
    return 'tool-error'


def observed_access(profile, reply):
    """Small application-owned facts for Captain handoffs, not raw error bodies."""
    failures = []
    for call in (getattr(reply, 'activity', None) or {}).get('calls', []):
        if call.get('status') != 'failed' or call.get('tool') not in ('web_search', 'web_fetch'):
            continue
        label = WEB_FAILURES.get(call.get('failureReason'), WEB_FAILURES['tool-error'])
        code = call.get('httpStatus')
        if type(code) is int and 400 <= code <= 599:
            label = str(code) + ' - ' + HTTP_FAILURES.get(code, 'HTTP request failed')
        failure = {'tool': call['tool'], 'reason': label}
        if failure not in failures:
            failures.append(failure)
    return {'openShellEnabled': profile.get('protection') == 'openshell',
            'confirmedPolicyDenial': bool(getattr(reply, 'policy_denials', None)),
            'toolFailures': failures[:8]}


def web_failure_status(message):
    # Inspect only a failed web tool result, and expose a status code, never its
    # raw response body, URL, headers or instructions embedded in the page.
    details=message.get('details') or {}
    for key in ('statusCode','httpStatus','status'):
        value=details.get(key)
        if type(value) is int and 400<=value<=599:return value
    content=message.get('content',[])
    text=' '.join(str(item.get('text','')) for item in content if isinstance(item,dict) and item.get('type')=='text')[:16000] if isinstance(content,list) else ''
    text=str(details.get('error',''))[:16000]+' '+text
    match=re.search(r'(?:Web fetch failed\s*\(|HTTP(?:\s+error)?\s+)([45]\d{2})\b',text,re.I)
    return int(match[1]) if match else None


def custom_skill_paths(config, agent, catalog):
    """Only this agent's equipped project skills, at its real workspace paths."""
    if not isinstance(config,dict):return {}
    entry=config.get('agents',{}).get('entries',{}).get(agent,{})
    workspace=entry.get('workspace')
    if not workspace:return {}
    roots=[workspace]
    sandbox=entry.get('sandbox',{})
    if sandbox.get('mode')!='off' and sandbox.get('backend')=='openshell':
        remote=config.get('plugins',{}).get('entries',{}).get('openshell',{}).get('config',{}).get('remoteWorkspaceDir','/sandbox')
        roots.append(remote)
    paths={}
    for name in entry.get('skills',[]):
        if name not in catalog:continue
        relative='skills/'+name+'/SKILL.md'
        skill={'id':name,'label':catalog[name]}
        for path in [relative]+[str(Path(root)/relative) for root in roots]:
            paths[posixpath.normpath(path)]=skill
    return paths


def collect(state, agent, session, started=0, skill_paths=None):
    path=Path(state)/'agents'/agent/'agent/openclaw-agent.sqlite'
    if not path.is_file():return {'source':'OpenClaw transcript','available':False,'calls':[]}
    try:
        with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=.2)) as db:
            rows=db.execute('''SELECT t.event_json FROM transcript_events t JOIN session_windows s USING(session_id)
                WHERE s.session_key=? AND t.created_at>=? ORDER BY t.seq LIMIT 2000''',
                ('agent:'+agent+':openai-user:'+session,int(started*1000))).fetchall()
        calls={}
        for row in rows:
            event=json.loads(row[0]);message=event.get('message',{})
            if message.get('role')=='assistant':
                for item in message.get('content',[]) if isinstance(message.get('content'),list) else []:
                    if item.get('type')!='toolCall':continue
                    name=item.get('name','');args=item.get('arguments',{})
                    if not isinstance(args,dict):continue
                    target=str(args.get('path') or args.get('file_path') or args.get('url') or args.get('query') or '')[:500]
                    command=str(args.get('command',''))
                    action='';actions=[]
                    if name=='exec':
                        try:
                            lexer=shlex.shlex(command,posix=True,punctuation_chars=';&|<>');lexer.whitespace_split=True
                            parts=list(lexer)
                            indexes=[i for i,x in enumerate(parts) if x.endswith('/event_agent_tools.py') and i>0 and re.fullmatch(r'python(?:3(?:\.\d+)?)?',Path(parts[i-1]).name) and i+1<len(parts) and parts[i+1] in ('search','read','draft-schedule','schedule')]
                            if indexes:
                                action=parts[indexes[0]+1];target=' '.join(parts[indexes[0]:])[:500]
                                # Only a single command or an && chain proves every action
                                # succeeded. A later command after ; can mask a failed tool.
                                if not any(p in (';','||','|','&','>','>>','<','<<','>&') for p in parts):
                                    actions=[parts[i+1] for i in indexes]
                            else:target='Shell command'
                        except ValueError:target='Shell command'
                    calls[item['id']]={'id':item['id'],'tool':name,'target':target,'action':action,'actions':actions,'time':event.get('timestamp'),'status':'started'}
            elif message.get('role')=='toolResult' and message.get('toolCallId') in calls:
                call=calls[message['toolCallId']];details=message.get('details') or {}
                failed=message.get('isError') or details.get('exitCode',0) not in (0,None) or details.get('status') in ('error','failed')
                if failed and call['tool'] in ('web_fetch','web_search'):
                    code=web_failure_status(message)
                    if code:call['httpStatus']=code
                    call['failureReason']=web_failure_reason(message,call['tool']) or 'tool-error'
                call['status']='failed' if failed else 'running' if details.get('status')=='running' else 'completed'
        for call in calls.values():
            # Reading a skill is observable; mentioning or equipping one is not use.
            if call['tool']=='read' and call['status']=='completed':
                skill=(skill_paths or {}).get(posixpath.normpath(call['target']))
                if skill:call['customSkill']=dict(skill)
        return {'source':'OpenClaw transcript','available':True,'calls':list(calls.values())}
    except (OSError,ValueError,TypeError,sqlite3.Error):return {'source':'OpenClaw transcript','available':False,'calls':[]}


def heartbeat_failure(state, agent, started):
    """Return only a fixed operational diagnosis, never raw transcript contents."""
    path=Path(state)/'agents'/agent/'agent/openclaw-agent.sqlite'
    if not path.is_file():return None
    try:
        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=2) as db:
            rows=db.execute("""SELECT t.event_json,t.created_at FROM transcript_events t
                JOIN session_windows s USING(session_id) WHERE s.session_key=? AND t.created_at>=?
                ORDER BY t.created_at DESC,t.seq DESC LIMIT 100""",
                ('agent:'+agent+':heartbeat-radar:heartbeat',int(started*1000))).fetchall()
        for raw,stamp in rows:
            message=json.loads(raw).get('message',{})
            if message.get('role')!='toolResult' or message.get('toolName')!='exec':continue
            content=message.get('content',[])
            text=' '.join(str(item.get('text','')) for item in content if isinstance(item,dict)) if isinstance(content,list) else ''
            if 'ENOENT' in text and 'launch' in text:
                return {'time':stamp/1000,'code':'execution-failed','message':'Heartbeat could not launch its command. Check the agent runtime; no website-policy denial was confirmed.'}
            # A later successful exec supersedes an earlier launch failure.
            return None
    except (OSError,ValueError,TypeError,sqlite3.Error):pass
    return None


def model_failure(state, agent, session, started, output_limit):
    """Diagnose only this invocation; never expose model text, arguments or keys."""
    path = Path(state) / 'agents' / agent / 'agent/openclaw-agent.sqlite'
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.2)) as db:
            rows = db.execute('''SELECT t.event_json FROM transcript_events t
                JOIN session_windows s USING(session_id)
                WHERE s.session_key=? AND t.created_at>=?
                ORDER BY t.created_at DESC,t.seq DESC LIMIT 20''',
                ('agent:' + agent + ':openai-user:' + session, int(started * 1000))).fetchall()
        for raw, in rows:
            message = json.loads(raw).get('message', {})
            if message.get('role') != 'assistant':
                continue
            # OpenClaw can convert an empty length-stopped native response into
            # HTTP 500, losing finish_reason in its compatibility response.
            # Usage may report only one output token, so do not require 8192.
            if message.get('stopReason') == 'length':
                return {'code': 'output-limit', 'message':
                    'The model stopped at a generation length limit before finishing. '
                    'Accumulated context may leave too little room for the answer. '
                    'Saved work is preserved; the request was not automatically repeated.'}
            error = str(message.get('errorMessage', ''))
            if re.fullmatch(r'context length exceeded: automatic output budget of [0-9]+ tokens exhausted before completion\.?',
                            error.strip(), re.IGNORECASE):
                return {'code': 'output-limit', 'message':
                    'The model used its available output budget before finishing a response. Saved work is preserved.'}
            if 'context overflow' in error.lower() or 'prompt too large' in error.lower():
                return {'code': 'context-overflow', 'message':
                    'The research exceeded the available context limit. Saved work is preserved. '
                    'Narrow the research scope or start a fresh request; this request was not automatically repeated.'}
            malformed = error in {
                'Provider returned an incomplete or malformed tool call',
                'Provider completed tool call with malformed JSON arguments',
                'Provider completed stream with an incomplete tool call',
            }
            if malformed:
                output = (message.get('usage') or {}).get('output')
                capped = type(output) is int and output >= output_limit
                return {'code': 'tool-call-output-limit' if capped else 'malformed-tool-call',
                    'message': 'The model returned an incomplete or invalid tool call.' +
                    (f' Its output reached the configured {output_limit:,}-token limit, which may have cut the call short.' if capped else '') +
                    ' Saved work is preserved. The request was not automatically repeated.'}
            if error:
                lowered = error.lower()
                from session_secrets import TRANSPORT_MESSAGES
                for code,message in TRANSPORT_MESSAGES.items():
                    if code+':' in lowered:
                        return {'code':code,'message':message+' Saved work is preserved.'}
                # Some providers wrap their database saturation in HTTP 401.
                # Do not misdiagnose that explicit infrastructure error as a bad key.
                if any(text in lowered for text in ('remaining connection slots are reserved',
                                                     'too many connections', 'too many clients already')):
                    return {'code': 'provider-capacity', 'message':
                        'The model service could not accept the request because its connection capacity was exhausted. '
                        'Saved work is preserved; try again after the service recovers. The request was not automatically repeated.'}
                if re.search(r'(?:http\s*|status(?:\s+code)?[\s:=]*)(?:502|503|504)\b', lowered):
                    return {'code': 'provider-unavailable', 'message':
                        'The model service is temporarily unavailable. Saved work is preserved; the request was not automatically repeated.'}
                if re.search(r'(?:http\s*|status(?:\s+code)?[\s:=]*)429\b', lowered):
                    return {'code': 'provider-rate-limit', 'message':
                        'The model service rate limit was reached. Saved work is preserved; wait before trying again. The request was not automatically repeated.'}
            # Do not diagnose an older error after a later successful response.
            return None
    except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error):
        return None


def context_failure(state, agent, session, started):
    """Native precheck failures may never become assistant transcript messages."""
    from datetime import datetime
    key = 'sessionKey=agent:' + agent + ':openai-user:' + session
    for filename in ('gateway.log', 'gateway-native.log'):
        try:
            with (Path(state).parent / filename).open('rb') as log:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - 2_000_000))
                lines = log.read().decode('utf-8', errors='replace').splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            timestamp = line.split(' ', 1)[0]
            if filename == 'gateway-native.log':
                try:
                    entry = json.loads(line)
                    if not isinstance(entry, dict):continue
                    subsystem = json.loads(entry.get('0', '{}'))
                    if not isinstance(subsystem, dict) or subsystem.get('subsystem') != 'agent/embedded':continue
                    line = '[agent/embedded] ' + str(entry.get('1', ''))
                    timestamp = entry.get('time', '')
                except (ValueError, TypeError):continue
            # A normal precheck also contains context-overflow in its tag;
            # only the failure diagnostic is evidence of overflow.
            if '[agent/embedded] [context-overflow-diag]' not in line or key + ' ' not in line:
                continue
            try:stamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()
            except (ValueError, TypeError, AttributeError):continue
            if stamp < started:continue
            return {'code':'context-overflow', 'message':
                'The research or conversation exceeded the available context limit. '
                'Saved work is preserved. Narrow the request or start a fresh conversation; '
                'this request was not automatically repeated.'}
    return None


def text_tool_write_path(text):
    """Recognize a write invocation emitted as prose; never execute its contents."""
    if not isinstance(text, str) or not re.match(r'^\s*<tool_call>\s*<function=(?:write|edit)>', text):
        return None
    match = re.search(r'<parameter=(?:path|file_path)>\s*([^<]+?)\s*</parameter>', text)
    return match.group(1).strip() if match else ''


def unexecuted_write(state, agent, session, started=0):
    """Detect a hidden text-form write even when the final reply claims success."""
    path = Path(state)/'agents'/agent/'agent/openclaw-agent.sqlite'
    if not path.is_file():return False
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
            rows = db.execute('''SELECT t.event_json FROM transcript_events t
                JOIN session_windows s USING(session_id)
                WHERE s.session_key=? AND t.created_at>=? ORDER BY t.seq''',
                ('agent:'+agent+':openai-user:'+session,int(started*1000))).fetchall()
        pending=set();writes={}
        for raw, in rows:
            message=json.loads(raw).get('message',{})
            content=message.get('content',[])
            if message.get('role')=='assistant':
                for item in content if isinstance(content,list) else []:
                    if item.get('type')=='text':
                        target=text_tool_write_path(item.get('text'))
                        if target is not None:pending.add(target)
                    elif item.get('type')=='toolCall' and item.get('name') in ('write','edit'):
                        args=item.get('arguments') or {}
                        if isinstance(args,dict):writes[item.get('id')]=args.get('path') or args.get('file_path')
            elif message.get('role')=='toolResult' and not message.get('isError'):
                details=message.get('details') or {}
                if details.get('status') not in ('failed','error','running') and details.get('exitCode',0) in (0,None):
                    pending.discard(writes.get(message.get('toolCallId')))
        return bool(pending)
    except (OSError,ValueError,TypeError,AttributeError,sqlite3.Error):
        return False
