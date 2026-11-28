# SPDX-License-Identifier: Apache-2.0

"""Bounded page excerpts. Run INSIDE OpenShell; curl retains native policy enforcement."""
import argparse
import json
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip=0;self.article=0;self.main=0
        self.body=[];self.articles=[];self.mains=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('head','script','style','svg','nav','footer'):self.skip+=1
        if tag=='article':self.article+=1
        if tag=='main':self.main+=1
    def handle_endtag(self,tag):
        if tag in ('head','script','style','svg','nav','footer'):self.skip=max(0,self.skip-1)
        if tag=='article':self.article=max(0,self.article-1)
        if tag=='main':self.main=max(0,self.main-1)
    def handle_data(self,value):
        if self.skip:return
        text=' '.join(value.split())
        if not text:return
        self.body.append(text)
        if self.article:self.articles.append(text)
        if self.main:self.mains.append(text)
    def text(self):return '\n'.join(self.articles or self.mains or self.body)


def excerpt(raw,limit=4000,offset=0):
    if offset < 0:
        raise ValueError('Offset must be nonnegative.')
    source=raw.decode('utf-8',errors='replace')
    if '<' in source[:1024]:
        parser=ArticleText();parser.feed(source);source=parser.text()
    end=min(len(source),offset+limit)
    return {'text':source[offset:end], 'offset':offset, 'totalChars':len(source),
            'nextOffset':end if end<len(source) else None,
            'truncated':offset>0 or end<len(source)}


def fetch(url,offset=0):
    if offset < 0:
        raise ValueError('Offset must be nonnegative.')
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a public HTTP(S) URL without credentials.')
    with tempfile.TemporaryDirectory(prefix='bac-page-') as directory:
        body=Path(directory)/'page'
        result=subprocess.run(['/usr/bin/curl','--disable','--silent','--show-error','--fail',
            '--location','--max-redirs','3','--proto','=http,https','--proto-redir','=http,https',
            '--max-time','30','--max-filesize','2000000','--output',str(body),
            '--write-out','%{url_effective}','--url',url],capture_output=True,text=True,timeout=35)
        if result.returncode:raise RuntimeError('Page read failed (curl %d): %s'%(result.returncode,result.stderr.strip()[:500]))
        with body.open('rb') as stream:raw=stream.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError('Page exceeds the download limit.')
        return {'url':result.stdout.strip(),**excerpt(raw,offset=offset)}


if __name__=='__main__':
    try:
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('url')
        parser.add_argument('--offset',type=int,default=0,help='Start within visible article text, for a missing section only.')
        args=parser.parse_args()
        print(json.dumps(fetch(args.url,args.offset),ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'error':str(error)[:600]}));sys.exit(1)
