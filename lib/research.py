"""Bounded public-web retrieval and evidence validation; never executes page instructions."""
from __future__ import annotations
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin, urlencode, quote
from pydantic import Field
from content_factory.models import Model


def now():
    return datetime.now(timezone.utc).isoformat()


def fetch_bytes(url, headers=None, limit=2_000_000):
    """HTTPS only, public addresses, pinned DNS per hop, bounded response and redirects."""
    for _ in range(5):
        u = urlsplit(url)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None,443):
            raise ValueError('Research URLs must be public HTTPS URLs without credentials or custom ports')
        addresses = socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Private or non-public research address rejected')
        conn = http.client.HTTPSConnection(u.hostname,timeout=20)
        raw = socket.create_connection((addresses[0][4][0],443),timeout=20)
        try:
            conn.sock = ssl.create_default_context().wrap_socket(raw,server_hostname=u.hostname)
            conn.request('GET', u.path + ('?'+u.query if u.query else '') or '/', headers={'User-Agent':'OpenMontageResearch/1.0', 'Accept-Encoding':'identity', **(headers or {})})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308):
                url=urljoin(url,response.getheader('Location',''))
                # Never forward API credentials to a redirect destination.
                headers=None
                continue
            if response.status!=200:
                raise ValueError(f'Research retrieval HTTP {response.status}; source unavailable')
            data=response.read(limit+1)
            if len(data)>limit: raise ValueError('Research response exceeds size limit')
            return url, response.getheader('Content-Type',''), data
        finally:
            conn.close()
            raw.close()
    raise ValueError('Too many redirects')


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.hidden=0; self.title=False; self.titles=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','svg'): self.hidden+=1
        if tag=='title': self.title=True
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','svg'): self.hidden=max(0,self.hidden-1)
        if tag=='title': self.title=False
    def handle_data(self,data):
        if not self.hidden:
            if self.title: self.titles.append(data)
            if data.strip(): self.parts.append(data.strip())


def retrieve(url):
    final,ctype,body=fetch_bytes(url)
    text=body.decode('utf-8',errors='replace')
    title=final
    if 'html' in ctype:
        parser=PageText();parser.feed(text);text=' '.join(parser.parts);title=' '.join(parser.titles) or final
    elif not any(t in ctype for t in ('text/plain','application/json','text/markdown')):
        raise ValueError('Unsupported source type; use a text/HTML source or a PDF extraction tool')
    text=' '.join(text.split())[:100000]
    if len(text)<40: raise ValueError('Source has insufficient readable text')
    digest=hashlib.sha256(text.encode()).hexdigest()
    return {'id':digest[:24],'url':final,'requested_url':url,'title':title[:500], 'retrieved_at':now(),
            'published_at':None,'sha256':digest,'text':text,'trust':'untrusted_source_content'}


def search(query,provider='wikipedia',limit=5):
    if provider=='tavily':
        from content_factory.publishing import cli,body
        data=body(cli('TAVILY_SEARCH',{'query':query,'max_results':limit,'search_depth':'basic','include_answer':False,'include_raw_content':False},os.environ.get('TAVILY_COMPOSIO_ACCOUNT')))
        results=[{'title':r.get('title',''),'url':r['url'],'snippet':r.get('content','')} for r in data.get('results',[])[:limit]]
    elif provider=='wikipedia':
        url='https://en.wikipedia.org/w/api.php?'+urlencode({'action':'query','format':'json','list':'search','srsearch':query,'srlimit':limit})
        _,_,raw=fetch_bytes(url);data=json.loads(raw)
        results=[{'title':r['title'],'url':'https://en.wikipedia.org/wiki/'+quote(r['title'].replace(' ','_')),'snippet':r.get('snippet','')} for r in data.get('query',{}).get('search',[])]
    else:
        endpoint=os.environ.get('SEARXNG_URL','').rstrip('/')
        if not endpoint: raise ValueError('SEARXNG_URL is not configured; Wikipedia search is available for background research only')
        _,_,raw=fetch_bytes(endpoint+'/search?'+urlencode({'q':query,'format':'json'}));data=json.loads(raw)
        results=[{'title':r.get('title',''),'url':r['url'],'snippet':r.get('content','')} for r in data.get('results',[])[:limit]]
    return {'query':query,'provider':provider,'retrieved_at':now(),'results':results,'note':'Search snippets are discovery leads, not verified evidence. Retrieve original sources; Wikipedia is not a trends or audience research engine.'}


class EvidenceLink(Model):
    source_id: str
    quote: str = Field(min_length=10,max_length=2000)
    relation: str = Field(default='supports',pattern='^(supports|contradicts)$')

class Claim(Model):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    statement: str = Field(min_length=1,max_length=2000)
    evidence: list[EvidenceLink] = Field(min_length=1,max_length=20)
    fresh_until: datetime
    confidence: str = Field(default='unreviewed',pattern='^(unreviewed|supported|disputed)$')

class EvidencePack(Model):
    topic: str = Field(min_length=1,max_length=500)
    claims: list[Claim] = Field(min_length=1,max_length=100)
    audience_questions: list[str] = Field(default_factory=list,max_length=50)
    angles: list[str] = Field(default_factory=list,max_length=20)


def validate_evidence(pack, sources):
    pack=EvidencePack.model_validate(pack);issues=[];seen=set()
    for claim in pack.claims:
        if claim.id in seen: raise ValueError('Duplicate claim id')
        seen.add(claim.id)
        if claim.fresh_until.tzinfo is None: raise ValueError('fresh_until must include timezone')
        if claim.fresh_until<=datetime.now(timezone.utc): issues.append({'claim':claim.id,'kind':'stale'})
        for link in claim.evidence:
            source=sources.get(link.source_id)
            if not source: raise ValueError(f'Unknown fetched source: {link.source_id}')
            if ' '.join(link.quote.split()) not in ' '.join(source['text'].split()):
                raise ValueError(f'Quote not present in source for {claim.id}')
        if claim.confidence!='supported' or any(e.relation=='contradicts' for e in claim.evidence):
            issues.append({'claim':claim.id,'kind':'needs_semantic_review'})
    return {'issues':issues,'ready':not issues,'note':'Quote provenance is mechanically checked. Entailment, independence and factual truth require agent review.'}
