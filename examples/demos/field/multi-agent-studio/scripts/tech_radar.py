# SPDX-License-Identifier: Apache-2.0

"""Fixed technical-feed reads and durable article discovery. The agent authors updates.

This file is copied into the agent workspace and executes there (inside OpenShell
when protected). It has no host relay, alternate transport or arbitrary URL input.
"""
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

HEARTBEAT_SECONDS = 20
STARTUP_DELAY_SECONDS = 10

SOURCES = (
    {'id':'nvidia','name':'NVIDIA Developer Blog','url':'https://developer.nvidia.com/blog/feed/','host':'developer.nvidia.com'},
    {'id':'huggingface','name':'Hugging Face Blog','url':'https://huggingface.co/blog/feed.xml','host':'huggingface.co'},
)
STATE = '.tech-radar-state.json'
CACHE = '.tech-radar-cache.json'
OUTBOX = 'artifacts/heartbeat-radar.json'
DRAFT = 'artifacts/radar-draft.json'
# A first pass excludes obvious nontechnical news; the model must also assess relevance.
EXCLUDE = re.compile(r'\b(?:politic\w*|election\w*|president\w*|parliament\w*|stock prices?|share prices?|earnings|quarterly results|dividends?|market cap|acquisition|funding round|joins? (?:hugging face|nvidia))\b', re.I)
TECHNICAL = re.compile(r'\b(?:tutorial\w*|developer\w*|open[ -]source|sdk\w*|api\w*|library|libraries|framework\w*|release\w*|inference|training|model\w*|agent\w*|benchmark\w*|dataset\w*|transformers|cuda|gpu\w*|workflow\w*|quant\w*|python|computing|scheduling|rendering)\b', re.I)


def read(root, name, default=None):
    root=Path(root).resolve();path=root/name
    if path.is_symlink():raise ValueError('Invalid radar file.')
    if not path.exists():return default
    if root not in path.resolve().parents or path.stat().st_size>900000:raise ValueError('Invalid radar file.')
    return json.loads(path.read_text())


def save(root, name, data):
    root=Path(root).resolve();path=root/name
    if path.is_symlink() or (root not in path.parent.resolve().parents and path.parent.resolve()!=root):
        raise ValueError('Invalid radar destination.')
    path.parent.mkdir(exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as handle:json.dump(data,handle,ensure_ascii=False)
    os.replace(temporary,path)


def article_url(value, source=None):
    if not isinstance(value,str) or len(value)>1200:return ''
    try:
        parsed=urlsplit(value)
        hosts={source['host']} if source else {s['host'] for s in SOURCES}
        if (parsed.scheme!='https' or parsed.hostname not in hosts or parsed.port not in (None,443)
                or parsed.username or parsed.password or not parsed.path.startswith('/blog/')
                or any(ord(c)<33 for c in value)):
            return ''
        return urlunsplit(('https',parsed.hostname,parsed.path.rstrip('/')+'/', '', ''))
    except ValueError:return ''


class PlainText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def plain(value,limit):
    parser=PlainText();parser.feed(value[:30000]);return re.sub(r'\s+',' ',' '.join(parser.parts)).strip()[:limit]


def timestamp(value):
    try:return datetime.fromisoformat(value.strip().replace('Z','+00:00')).timestamp()
    except (ValueError,AttributeError):
        try:return parsedate_to_datetime(value).timestamp()
        except (ValueError,TypeError,AttributeError,OverflowError):return 0


def parse_feed(raw, source, now):
    if len(raw)>1_500_000 or re.search(br'<!\s*(?:DOCTYPE|ENTITY)',raw,re.I):raise ValueError('Unsupported feed.')
    root=ET.fromstring(raw);rows={}
    for entry in root.iter():
        if entry.tag.split('}')[-1] not in ('item','entry'):continue
        fields={}
        links=[]
        for child in entry:
            name=child.tag.split('}')[-1]
            fields.setdefault(name,''.join(child.itertext()))
            if name=='link' and child.attrib.get('rel','alternate')=='alternate':
                links.append(child.attrib.get('href') or child.text or '')
        url=next((article_url(link,source) for link in links if article_url(link,source)), '')
        title=plain(fields.get('title',''),240)
        published=timestamp(fields.get('published') or fields.get('pubDate') or fields.get('updated',''))
        if not url or not title or not 0<published<=now+300:continue
        description=plain(fields.get('summary') or fields.get('description') or fields.get('encoded') or fields.get('content',''),1600)
        identifier=hashlib.sha256(url.encode()).hexdigest()
        rows[identifier]={'id':identifier,'url':url,'title':title,'published':published,
            'source':source['name'],'sourceId':source['id'],'excerpt':description,
            'eligible':not EXCLUDE.search(title+' '+description[:400]) and bool(TECHNICAL.search(title+' '+description))}
    return sorted(rows.values(),key=lambda row:(row['published'],row['id']),reverse=True)[:40]


def fetch(source, cached):
    """One bounded GET to a fixed HTTPS feed, with conditional caching. No redirects."""
    with tempfile.TemporaryDirectory(prefix='bac-radar-') as temporary:
        body=Path(temporary)/'feed';headers=Path(temporary)/'headers'
        command=['/usr/bin/curl','--disable','--silent','--show-error','--proto','=https',
            '--connect-timeout','4','--max-time','8','--max-filesize','1500000',
            '--user-agent','BaC-Tech-Radar/1.0','--dump-header',str(headers),
            '--output',str(body),'--write-out','%{http_code}','--url',source['url']]
        for key,header in [('etag','If-None-Match'),('modified','If-Modified-Since')]:
            value=cached.get(key,'')
            if isinstance(value,str) and len(value)<500 and not re.search(r'[\r\n\x00]',value) and value:
                command+=['--header',header+': '+value]
        try:result=subprocess.run(command,capture_output=True,text=True,timeout=11)
        except subprocess.TimeoutExpired:raise ValueError('Feed request timed out.') from None
        status=result.stdout.strip()
        if result.returncode or status not in ('200','304'):
            raise ValueError('Feed unavailable (HTTP '+(status if status.isdigit() else 'unknown')+'). Check its connection or OpenShell Policy.')
        fields={}
        for line in headers.read_text(errors='replace').splitlines():
            name,sep,value=line.partition(':')
            if sep:fields[name.lower()]=value.strip()
        raw=body.read_bytes() if status=='200' else None
        return raw, {'etag':fields.get('etag',cached.get('etag','')), 'modified':fields.get('last-modified',cached.get('modified',''))}


def candidate_digest(rows):
    return hashlib.sha256(json.dumps([(r['id'],r['title'],r['excerpt']) for r in rows],sort_keys=True).encode()).hexdigest()


def run(root, action, fetcher=fetch, now=None):
    root=Path(root).resolve();now=time.time() if now is None else now
    state=read(root,STATE,{'seen':{},'startedAt':now,'initialized':False})
    box=read(root,OUTBOX,{'events':[]})
    if not isinstance(state,dict) or not isinstance(state.get('seen'),dict) or not isinstance(box,dict) or not isinstance(box.get('events'),list):
        raise ValueError('Invalid radar state.')
    if action=='poll':
        cache=read(root,CACHE,{})
        if not isinstance(cache,dict):raise ValueError('Invalid feed cache.')
        rows=[];failures=[];successes=0
        for source in SOURCES:
            previous=cache.get(source['id'],{})
            if previous.get('retryAfter',0)>now:
                failures.append({'host':source['host'],'detail':'Feed unavailable; waiting before retry.'})
                continue
            try:
                if now-previous.get('fetchedAt',0)>=30:
                    raw,validators=fetcher(source,previous)
                    parsed=parse_feed(raw,source,now) if raw is not None else previous.get('rows',[])
                    if raw is not None and not parsed:raise ValueError('Feed returned no dated articles.')
                    previous={**validators,'rows':parsed,'fetchedAt':now}
                    cache[source['id']]=previous
                rows+=previous.get('rows',[]);successes+=1
            except (ValueError,OSError,ET.ParseError) as error:
                cache[source['id']]={**previous,'retryAfter':now+60}
                failures.append({'host':source['host'],'detail':str(error)[:180]})
        save(root,CACHE,cache)
        initial=not state.get('initialized')
        cutoff=state.get('retiredBefore',0)
        candidates=[row for row in rows if row['eligible'] and row['id'] not in state['seen'] and row['published']>=cutoff]
        candidates=sorted({row['id']:row for row in candidates}.values(),key=lambda row:(row['published'],row['id']),reverse=True)[:5]
        if candidates:
            token=candidate_digest(candidates)
            state['pending']={'token':token,'articles':candidates,'initial':initial,'checkedAt':now}
            status='new-articles'
        else:
            state.pop('pending',None)
            if successes:state['initialized']=True
            token=None;status='source-unavailable' if not successes else 'idle'
        save(root,STATE,state)
        box.update(status=status,checkedAt=now,failures=failures);save(root,OUTBOX,box)
        return {'status':status,'token':token,'initial':initial,'articles':candidates,'sourceIssues':failures,
                'evidence':'Feed excerpts only; full articles were not fetched.'}
    if action!='publish':raise ValueError('Unknown radar action.')
    pending=state.get('pending');draft=read(root,DRAFT,{})
    if not pending:return {'status':'idle'}
    if not isinstance(draft,dict) or draft.get('token')!=pending['token']:raise ValueError('Stale radar draft. Poll again on the next heartbeat.')
    candidates={r['id']:r for r in pending['articles']}
    skip=draft.get('skipIds',[])
    if not isinstance(skip,list) or any(not isinstance(i,str) or i not in candidates for i in skip):raise ValueError('Invalid skipped articles.')
    selected=draft.get('articleId');answer=draft.get('answer','')
    if selected is not None:
        if not isinstance(selected,str) or selected not in candidates or selected in skip:raise ValueError('Choose one returned article.')
        if not isinstance(answer,str) or not answer.strip() or len(answer)>1400:raise ValueError('Use a short, nonempty update of at most 1400 characters.')
        article=candidates[selected]
        if not any(isinstance(e,dict) and e.get('id')==selected for e in box['events']):
            box['events']=(box['events']+[{'id':selected,'answer':answer.strip(),'url':article['url'],
                'title':article['title'],'published':article['published'],'created':now,'initial':pending['initial']}])[-50:]
    elif set(skip)!=set(candidates):raise ValueError('Explain the selection by skipping every irrelevant candidate, or choose one.')
    # Commit the outbox first; a crash cannot duplicate the same article notification.
    box.update(status='updated' if selected else 'idle',checkedAt=now);save(root,OUTBOX,box)
    acknowledged={i:candidates[i]['published'] for i in skip+([selected] if selected else [])}
    state['seen'].update(acknowledged);state['initialized']=True;state.pop('pending',None)
    if len(state['seen'])>2000:
        keep=sorted(state['seen'].items(),key=lambda pair:pair[1],reverse=True)[:2000]
        state['retiredBefore']=max(state.get('retiredBefore',0),keep[-1][1]+.001);state['seen']=dict(keep)
    save(root,STATE,state)
    return {'status':'published' if selected else 'skipped','id':selected}


if __name__=='__main__':
    import sys
    try:
        fd=os.open('.tech-radar.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            print(json.dumps(run(Path.cwd(),sys.argv[1]),ensure_ascii=False))
    except (ValueError,OSError,IndexError) as error:
        print(json.dumps({'error':str(error),'instruction':'Stop. Do not bypass restrictions.'}));sys.exit(1)
