import json
import hashlib
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
from content_factory.models import ProjectConfig
from content_factory.service import Factory
from content_factory.registry import Registry
from content_factory.automation import reserve,budget_snapshot,save_policy,policy_for,AutomationPolicy,enqueue,dispatch
from content_factory.workflow import save_evidence,audit_script,ScriptAudit
from lib.research import validate_evidence,EvidencePack,fetch_bytes
from tests.content_factory.test_factory import ExamplePlugin,plan

@pytest.fixture
def factory(tmp_path):
 f=Factory(Registry([ExamplePlugin()]),tmp_path)
 f.create('film','Film','animation',ProjectConfig(max_project_estimate_usd=1))
 return f

def pack():
 return EvidencePack(topic='Test',claims=[{'id':'c1','statement':'Water example','fresh_until':datetime.now(timezone.utc)+timedelta(days=1),'confidence':'supported','evidence':[{'source_id':'s1','quote':'Water freezes under these conditions.'}]}])

def sources():return {'s1':{'text':'Water freezes under these conditions.'}}

def test_provenance_and_staleness():
 p=pack();assert validate_evidence(p,sources())['ready']
 p.claims[0].evidence[0].quote='invented quote never in source'
 with pytest.raises(ValueError,match='Quote'):validate_evidence(p,sources())
 p=pack();p.claims[0].fresh_until=datetime.now(timezone.utc)-timedelta(seconds=1)
 assert not validate_evidence(p,sources())['ready']
 p=pack();p.claims[0].evidence[0].relation='contradicts'
 assert not validate_evidence(p,sources())['ready']

@pytest.mark.parametrize('url',['file:///etc/passwd','http://example.com','https://user:secret@example.com','https://127.0.0.1','https://[::1]','https://example.com:9000'])
def test_fetch_rejects_nonpublic(url):
 with pytest.raises(ValueError): fetch_bytes(url)

def test_atomic_budget_concurrency(factory):
 def spend(i):
  try:
   with factory.db('film') as db:
    db.execute('BEGIN IMMEDIATE');reserve(db,str(i),.6,1,'test')
   return True
  except ValueError:return False
 with ThreadPoolExecutor(2) as pool: results=list(pool.map(spend,range(2)))
 assert results.count(True)==1
 with factory.db('film') as db:assert budget_snapshot(db)['committed_usd']==.6

@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1])
def test_invalid_budget(factory,value):
 with factory.db('film') as db:
  with pytest.raises(ValueError):reserve(db,'x',value,1,'test')

def test_policy_expiry_and_revision(factory):
 p=AutomationPolicy(enabled=True,approved_stages=['research'],allowed_operations=['example:draw'],expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
 save_policy(factory,'film',p,'User authorized a bounded test')
 assert policy_for(factory,'film')['valid']
 factory.configure('film',ProjectConfig(max_project_estimate_usd=1),1)
 assert not policy_for(factory,'film')['valid']
 with pytest.raises(ValueError,match='changed'): save_policy(factory,'film',p,'User approved',0)

def test_evidence_requires_fetched_job(factory):
 with pytest.raises(ValueError,match='Unknown fetched'):save_evidence(factory,'film','e1',pack())
 text=sources()['s1']['text'];source={'id':'s1','text':text,'sha256':hashlib.sha256(text.encode()).hexdigest(),'trust':'untrusted_source_content'}
 with factory.db('film') as db:db.execute("INSERT INTO jobs VALUES ('r','r','r','completed','{}',?,NULL)",(json.dumps({'data':source}),))
 assert save_evidence(factory,'film','e1',pack())['review']['ready']
 audit=audit_script(factory,'film',ScriptAudit(evidence_id='e1',lines=[{'id':'l1','text':'Water freezes','claim_ids':['c1']}]))
 assert audit['ready']
 bad=audit_script(factory,'film',ScriptAudit(evidence_id='e1',lines=[{'id':'l1','text':'Unsupported fact'}]))
 assert not bad['ready']

def test_queue_reuses_job_key_and_keeps_blockers(factory,monkeypatch):
 saved=factory.save_plan('film',plan())
 enqueue(factory,'film',saved['plan_id'],'scene','once')
 assert dispatch(factory,'film')['items'][0]['status']=='waiting'
 calls=[]
 def submit(project,plan,step,key,evidence):
  calls.append(key);return {'job_id':'j','status':'queued'}
 monkeypatch.setattr(factory,'submit',submit)
 dispatch(factory,'film');dispatch(factory,'film')
 assert calls==['once']

def test_schema_registration(factory):
 import asyncio
 from content_factory.server import build_server
 async def check():
  names={t.name for t in await build_server(factory).list_tools()}
  assert {'factory_next_action','factory_export_media','factory_publish_delivery','factory_save_evidence'}<=names
 asyncio.run(check())

def test_research_registered_and_pipeline_permitted():
 from content_factory.adapters.openmontage import OpenMontage
 from lib.pipeline_loader import load_pipeline,get_stage_tools
 registry=Registry([OpenMontage()])
 assert registry.resolve('openmontage:research_search')[1].capability=='research'
 assert 'research_fetch' in get_stage_tools(load_pipeline('animated-explainer'),'research')

def test_speech_comparison():
 from lib.speech_review import compare_speech
 assert compare_speech('Hello, world!','hello world')['word_error_rate']==0
 assert compare_speech('a b c','a x c')['word_error_rate']==pytest.approx(1/3)

def test_automatic_research_cannot_skip_evidence(factory):
 from tests.contracts.test_phase0_contracts import sample_artifact
 policy=AutomationPolicy(enabled=True,approved_stages=['research'],expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
 save_policy(factory,'film',policy,'User explicitly authorized this software test')
 with pytest.raises(ValueError,match='research evidence'):
  factory.checkpoint('film','research','completed',{'research_brief':sample_artifact('research_brief')})

def test_expired_policy_cannot_supply_gate_approval(factory):
 from content_factory.automation import approval
 policy=AutomationPolicy(enabled=True,approved_stages=['script'],expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
 save_policy(factory,'film',policy,'User explicitly authorized this software test')
 with factory.db('film') as db:
  data=json.loads(db.execute('SELECT data FROM automation_policy').fetchone()[0]);data['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
  db.execute('UPDATE automation_policy SET data=?',(json.dumps(data),))
 assert approval(factory,'film',stage='script') is None

def test_collection_retains_failures_and_deduplicates(tmp_path,monkeypatch):
 import tools.research.research_collect as module
 monkeypatch.setattr(module,'search',lambda *a:{'results':[{'url':'https://bad.example'},{'url':'https://one.example'},{'url':'https://two.example'}]})
 def retrieve(url):
  if 'bad' in url:raise ValueError('blocked')
  return {'id':'same-content','url':url,'text':'Actual retrieved source','trust':'untrusted_source_content'}
 monkeypatch.setattr(module,'retrieve',retrieve)
 result=module.ResearchCollect().execute({'queries':['test'],'provider':'wikipedia','output_dir':str(tmp_path)})
 assert result.success and result.data['source_count']==1
 assert len(result.data['retrieval_failures'])==1
 assert len(result.artifacts)==1

def test_policy_supplies_proposal_approval_only_with_creative_discretion(factory):
 from tests.contracts.test_phase0_contracts import sample_artifact
 factory.checkpoint('film','research','completed',{'research_brief':sample_artifact('research_brief')})
 policy=AutomationPolicy(enabled=True,approved_stages=['proposal'],expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
 save_policy(factory,'film',policy,'User authorized automatic software-test concept selection')
 packet=sample_artifact('proposal_packet');packet['approval']['status']='pending'
 with pytest.raises(ValueError,match='creative_discretion'):
  factory.checkpoint('film','proposal','completed',{'proposal_packet':packet})
 policy.creative_discretion=True
 save_policy(factory,'film',policy,'User authorized automatic software-test concept selection',1)
 factory.checkpoint('film','proposal','completed',{'proposal_packet':packet})
 data=json.loads((factory.project('film')/'checkpoint_proposal.json').read_text())
 assert data['artifacts']['proposal_packet']['approval']['status']=='approved'
 assert data['human_approved']
