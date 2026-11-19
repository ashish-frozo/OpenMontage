import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from content_factory import trends as t

@pytest.fixture
def factory(tmp_path):return SimpleNamespace(root=tmp_path/'projects')

def save(f,id,time,views,scope=None):
    data={'id':id,'collected_at':time,'scope':scope or {'platform':'youtube'},'sample_type':'public_search','warnings':[], 'videos':[{'id':'v1','title':'Example','creator':'c1','views':views,'likes':5,'comments':None,'metric_definition':'youtube_public_viewCount'}]}
    with t.database(f) as db:db.execute('INSERT INTO trend_snapshots VALUES(?,?,?,?)',(id,'same',time,json.dumps(data)))
    return data

def test_single_snapshot_not_growth(factory):
    save(factory,'a','2026-01-01T02:00:00+00:00',120)
    d=t.report(factory,'a');assert d['videos'][0]['views_per_hour'] is None
    assert d['videos'][0]['engagement_per_view'] is None
    assert 'One snapshot' in d['warnings'][-1]

def test_real_delta_not_lifetime_velocity(factory):
    save(factory,'a','2026-01-01T00:00:00+00:00',100)
    save(factory,'b','2026-01-01T02:00:00+00:00',220)
    d=t.report(factory,'b','a');assert d['videos'][0]['views_per_hour']==60
    assert d['videos'][0]['view_delta']==120

def test_missing_and_corrected_counts(factory):
    save(factory,'a','2026-01-01T00:00:00+00:00',100)
    save(factory,'b','2026-01-01T02:00:00+00:00',90)
    d=t.report(factory,'b','a');assert d['videos'][0]['counter_revision']
    assert d['videos'][0]['views_per_hour'] is None
    save(factory,'c','2026-01-01T04:00:00+00:00',None)
    assert t.report(factory,'c','b')['videos'][0]['views_per_hour'] is None

def test_incomparable_or_too_recent_baseline(factory):
    save(factory,'a','2026-01-01T00:00:00+00:00',10)
    save(factory,'b','2026-01-01T00:10:00+00:00',15)
    with pytest.raises(ValueError,match='recent'):t.report(factory,'b','a')
    save(factory,'c','2026-01-01T02:00:00+00:00',15,{'platform':'instagram'})
    with pytest.raises(ValueError,match='scope'):t.report(factory,'c','a')

def test_normalizers_preserve_missing_and_public_instagram_fields():
    a=t.youtube([{'id':'a','snippet':{},'statistics':{}}])[0];assert a['views'] is None
    b=t.instagram([{'id':'42','media_type':2,'caption':{'text':'demo'},'code':'ABC','ig_play_count':100,'created_at':'2026-01-01T00:00:00Z','comment_count':0}], 'creator')[0]
    assert b['views']==100 and b['comments']==0 and b['published_at']
    assert b['url']=='https://www.instagram.com/p/ABC/'
    assert t.number(True) is None and t.number(-2) is None

def test_owned_insights_fallback_is_explicit(factory,monkeypatch):
    calls=[]
    def source(slug,args,account):
        calls.append(args.copy())
        if 'insights' in args['fields']:raise ValueError('ineligible')
        return {'data':[{'id':'42','media_type':'VIDEO','timestamp':'2026-01-01T00:00:00Z'}]}
    monkeypatch.setattr(t,'read_source',source)
    d=t.collect(factory,t.Collect(platform='instagram'))
    assert len(calls)==2 and d['videos'][0]['views'] is None
    assert any('unavailable' in w for w in d['warnings'])

def test_oversized_cli_spill_path_rejected(monkeypatch,tmp_path):
    p=tmp_path/'secret.json';p.write_text('{}')
    monkeypatch.setattr(t,'cli',lambda *a:{'storedInFile':True,'outputFilePath':str(p)})
    with pytest.raises(ValueError,match='directory'):t.read_source('slug',{},None)

def test_no_style_from_title_only(factory):
    from mcp.server.fastmcp import FastMCP
    m=FastMCP('test');t.register(m,factory)
    save(factory,'a','2026-01-01T00:00:00+00:00',100)
    fn=m._tool_manager.get_tool('factory_trend_label').fn
    with pytest.raises(ValueError,match='visual'):
        fn('a',[t.Label(video_id='v1',styles=['cinematic'],evidence='Title says cinematic; frames not viewed.',basis='title_description')])
    fn('a',[t.Label(video_id='v1',topics=['demo'],evidence='Title mentions this specific demo topic.',basis='title_description')])
    assert t.report(factory,'a')['topic_style_signals'][0]['signal']=='insufficient_evidence'

def test_group_growth_requires_three_videos_two_creators(factory):
    a=save(factory,'a','2026-01-01T00:00:00+00:00',100)
    b=save(factory,'b','2026-01-01T02:00:00+00:00',220)
    for d in (a,b):
        d['videos']=[dict(d['videos'][0],id='v'+str(i),creator='c'+str(i%2)) for i in range(3)]
        with t.database(factory) as db:db.execute('UPDATE trend_snapshots SET data=? WHERE id=?',(json.dumps(d),d['id']))
    with t.database(factory) as db:
        for i in range(3):db.execute('INSERT INTO trend_labels VALUES(?,?,?)',('b','v'+str(i),t.Label(video_id='v'+str(i),styles=['screencast'],basis='visual_review',evidence='Reviewed frames at 0:05 and 0:15; computer UI fills frame.').model_dump_json()))
    group=t.report(factory,'b','a')['topic_style_signals'][0]
    assert group['signal']=='sampled_growth' and group['median_views_per_hour']==60 and group['creator_count']==2
