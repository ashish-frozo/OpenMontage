import json
import pytest
from tools.openshorts import backend as b

def test_discovered_operations():
    from tools.tool_registry import registry
    registry.discover()
    names=[n for n in registry.list_all() if n.startswith('openshorts_')]
    assert len(names)==6
    assert not any('publish' in n for n in names)

def test_endpoint_rejects_credentials_and_cleartext_remote(monkeypatch):
    for url in ['http://user:secret@localhost:8017','http://example.com','https://example.com?token=x']:
        monkeypatch.setenv('OPENSHORTS_API_URL',url)
        with pytest.raises(ValueError): b.endpoint()

def test_mutation_not_replayed(monkeypatch):
    monkeypatch.setenv('OPENSHORTS_API_URL','http://127.0.0.1:8017')
    calls=[]
    def post(self,*a,**kw):
        calls.append(kw)
        raise b.httpx.ReadTimeout('uncertain')
    monkeypatch.setattr(b.httpx.Client,'post',post)
    result=b.OpenShortsProcessVideo().execute({'source_url':'https://example.org/a.mp4','confirm_rights':True,'estimated_cost_usd':.2})
    assert not result.success and len(calls)==1
    assert 'estimated_cost_usd' not in calls[0]['json']['params']['arguments']
    assert 'may have been accepted' in result.error

def test_job_id_preserved_and_unknown_cost(monkeypatch):
    monkeypatch.setenv('OPENSHORTS_API_URL','http://127.0.0.1:8017')
    def post(self,url,**kw):
        return b.httpx.Response(200,request=b.httpx.Request('POST',url),json={'jsonrpc':'2.0','id':1,'result':{'content':[{'type':'text','text':'{"job_id":"abc"}'}]}})
    monkeypatch.setattr(b.httpx.Client,'post',post)
    result=b.OpenShortsProcessVideo().execute({'source_url':'https://example.org/a.mp4','confirm_rights':True,'estimated_cost_usd':.2})
    assert result.success and result.cost_usd is None
    assert 'abc' in json.dumps(result.data)

def test_health_does_not_claim_ready_when_backend_offline(monkeypatch):
    monkeypatch.setenv('OPENSHORTS_API_URL','http://127.0.0.1:8017')
    def get(*args,**kwargs): raise b.httpx.ConnectError('offline')
    monkeypatch.setattr(b.httpx.Client,'get',get)
    assert b.OpenShortsGetJobStatus().get_status()==b.ToolStatus.UNAVAILABLE

def test_health_checks_upstream_ready_endpoint(monkeypatch):
    monkeypatch.setenv('OPENSHORTS_API_URL','http://127.0.0.1:8017')
    def get(self,url):
        assert url=='http://127.0.0.1:8017/health/ready'
        return b.httpx.Response(200,request=b.httpx.Request('GET',url),json={'status':'ready'})
    monkeypatch.setattr(b.httpx.Client,'get',get)
    assert b.OpenShortsGetJobStatus().get_status()==b.ToolStatus.AVAILABLE

def test_factory_exposes_native_permissions():
    from content_factory.registry import Registry
    import yaml
    factory=Registry()
    for name in ['process_video','get_job_status','list_clips','get_quota','add_subtitles','recut_clip']:
        _,op=factory.resolve('openmontage:openshorts_'+name)
        assert op.native_tool=='openshorts_'+name
        for pipeline in ['clip-factory','podcast-repurpose']:
            manifest=yaml.safe_load((b.Path('pipeline_defs')/(pipeline+'.yaml')).read_text())
            stage=next(s for s in manifest['stages'] if s['name']=='assets')
            assert op.native_tool in stage['tools_available']

@pytest.mark.parametrize('layout,framing',[('fill','track'),('fit','full'),('auto','auto')])
def test_portrait_layout_mapping(monkeypatch,layout,framing):
    monkeypatch.setenv('OPENSHORTS_API_URL','http://127.0.0.1:8017')
    def post(self,url,**kw):
        args=kw['json']['params']['arguments']
        assert args['framing']==framing and 'vertical_layout' not in args
        return b.httpx.Response(200,request=b.httpx.Request('POST',url),json={'result':{'isError':False}})
    monkeypatch.setattr(b.httpx.Client,'post',post)
    assert b.OpenShortsRecutClip().execute({'job_id':'abc','clip_index':0,'segments':[{'start':1,'end':20}],'vertical_layout':layout,'estimated_cost_usd':0}).success

def test_conflicting_framing_rejected():
    with pytest.raises(ValueError,match='either'):
        b.OpenShortsRecutClip().execute({'job_id':'abc','clip_index':0,'segments':[{'start':1,'end':20}],'vertical_layout':'fill','framing':'full','estimated_cost_usd':0})
