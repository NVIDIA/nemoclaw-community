# SPDX-License-Identifier: Apache-2.0

"""Public, observed tool metadata for a currently running collaboration turn."""
import time
from agent_activity import HTTP_FAILURES, WEB_FAILURES
from pathlib import PurePosixPath
from urllib.parse import urlsplit


def snapshot(adapter, observation):
    reader = getattr(adapter, 'observed_activity', None)
    if not callable(reader):return None
    try:
        activity = reader(observation['agent'], observation['session'], observation['started'])
        calls=[]
        for call in activity.get('calls', [])[-12:]:
            tool=call.get('tool','')
            target=call.get('target','')
            # Expose no host directories, URL credentials/queries, shell commands or arguments.
            if tool in ('web_fetch','web_search'):
                target=urlsplit(target).hostname or '' if tool=='web_fetch' else ''
            elif tool in ('read','write','edit','apply_patch'):
                target=PurePosixPath(target.replace('\\','/')).name if target else ''
            else:target=''
            calls.append({'id':str(call.get('id') or '')[:160],
                          'tool':tool if tool in ('web_fetch','web_search','read','write','edit','apply_patch','exec') else 'tool',
                          'target':target[:160], 'status':call.get('status') if call.get('status') in ('started','running','completed','failed') else 'started'})
            code=call.get('httpStatus')
            if calls[-1]['status']=='failed' and tool in ('web_fetch','web_search') and call.get('failureReason') in WEB_FAILURES:
                calls[-1]['errorLabel']=WEB_FAILURES[call['failureReason']]
            if calls[-1]['status']=='failed' and tool in ('web_fetch','web_search') and type(code) is int and 400<=code<=599:
                calls[-1]['errorLabel']=str(code)+' - '+HTTP_FAILURES.get(code,'HTTP request failed')
        return {'role':observation['role'], 'available':bool(activity.get('available')), 'calls':calls,
                'elapsed':max(0,int(time.time()-observation['started']))}
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return {'role':observation['role'],'available':False,'calls':[],
                'elapsed':max(0,int(time.time()-observation['started']))}
