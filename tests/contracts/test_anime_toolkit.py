import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from lib import anime_toolkit as bridge
from tools.base_tool import ToolResult, ToolStatus
from tools.video.anime_toolkit import AnimeProject, AnimeLocal, AnimeGenerate, GenerateInput, LocalInput


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'PROJECTS_DIR',tmp_path)
    root=tmp_path/'demo'; work=root/'assets/anime'
    (work/'config').mkdir(parents=True);(work/'docs').mkdir()
    (root/'project.json').write_text(json.dumps({'pipeline_type':'animation'}))
    (work/'config/project.json').write_text('{}')
    (work/'docs/PLAN.md').write_text('Approved scene plan')
    return root,work


def generation(work):
    return {'project_id':'demo','task':'gen:shots','run':'scene-01','only':'shot-1',
            'plan_sha256':hashlib.sha256((work/'docs/PLAN.md').read_bytes()).hexdigest(),
            'approval_evidence':'User approved the bounded anime plan','estimated_cost_usd':1.5}


def test_paid_missing_item_and_changed_plan_never_execute(workspace,monkeypatch):
    _,work=workspace;monkeypatch.setenv('FAL_KEY','test-key')
    monkeypatch.setattr(bridge,'require_production_approval',lambda root:None)
    monkeypatch.setattr(bridge,'invoke',lambda *a,**kw:pytest.fail('must not invoke'))
    inputs=generation(work);inputs['only']=None
    with pytest.raises(ValueError,match='exactly one'):AnimeGenerate().execute(inputs)
    inputs=generation(work);inputs['plan_sha256']='0'*64
    with pytest.raises(ValueError,match='changed'):AnimeGenerate().execute(inputs)
    assert not (work/'config/approval.json').exists()


def test_paid_requires_canonical_approval(workspace,monkeypatch):
    _,work=workspace;monkeypatch.setenv('FAL_KEY','test-key')
    with pytest.raises(ValueError,match='predecessor research'):
        AnimeGenerate().execute(generation(work))


def test_paid_records_actual_approval_and_unknown_cost(workspace,monkeypatch):
    _,work=workspace;monkeypatch.setenv('FAL_KEY','test-key')
    monkeypatch.setattr(bridge,'require_production_approval',lambda root:None)
    calls=[]
    def invoke(*a,**kw):calls.append((a,kw));return ToolResult(success=True,cost_usd=None)
    monkeypatch.setattr(bridge,'invoke',invoke)
    inputs=generation(work);result=AnimeGenerate().execute(inputs)
    assert result.cost_usd is None
    assert AnimeGenerate().estimate_cost(inputs)==1.5
    assert calls[0][1]['paid'] and calls[0][1]['ONLY']=='shot-1'
    approval=json.loads((work/'config/approval.json').read_text())
    assert approval['user_approval']==inputs['approval_evidence']
    assert approval['plan_sha256']==inputs['plan_sha256']


@pytest.mark.parametrize('override',[{'estimated_cost_usd':0},{'estimated_cost_usd':float('nan')},{'only':'one,two'},{'task':'pipeline:all'},{'approval_evidence':''}])
def test_reject_unsafe_or_unpriced_generation(workspace,override):
    with pytest.raises(ValidationError):GenerateInput.model_validate({**generation(workspace[1]),**override})


def test_local_removes_generation_keys_and_forcing_flags(monkeypatch,tmp_path):
    monkeypatch.setattr(bridge,'ruby',lambda:'/ruby')
    for name in ['FAL_KEY','FAL_AI_API_KEY','FAL_AI_API_KEY_PLUGIN','NEW_REQUEST','FORCE','VIDEO_MODEL']:
        monkeypatch.setenv(name,'secret')
    env=bridge.environment(RUN='scene-02')
    assert env['RUN']=='scene-02'
    assert all(k not in env for k in ['FAL_KEY','FAL_AI_API_KEY','FAL_AI_API_KEY_PLUGIN','NEW_REQUEST','FORCE','VIDEO_MODEL'])
    assert bridge.environment(paid=True)['FAL_AI_API_KEY']=='secret'


@pytest.mark.parametrize('arg',['../escape.mp4','/tmp/escape.mp4','foo,bar','x]','a\nb'])
def test_reject_injected_and_escaping_arguments(workspace,monkeypatch,tmp_path,arg):
    _,work=workspace;rt=tmp_path/'runtime';rt.mkdir();(rt/'mv.rb').touch()
    monkeypatch.setattr(bridge,'runtime',lambda:rt);monkeypatch.setattr(bridge,'ruby',lambda:'/ruby')
    with pytest.raises(ValueError):bridge.invoke(work,'media:probe',[arg])


def test_invoke_uses_argument_array_and_redacts_output(workspace,monkeypatch,tmp_path):
    _,work=workspace;rt=tmp_path/'runtime';rt.mkdir();(rt/'mv.rb').touch()
    monkeypatch.setattr(bridge,'runtime',lambda:rt);monkeypatch.setattr(bridge,'ruby',lambda:'/ruby')
    monkeypatch.setenv('FAL_KEY','secret-key');calls=[]
    def run(argv,**kw):calls.append((argv,kw));return SimpleNamespace(returncode=0,stdout='secret-key',stderr='')
    monkeypatch.setattr(bridge.subprocess,'run',run)
    result=bridge.invoke(work,'media:probe',['output/take.mp4'])
    assert result.success and 'secret-key' not in result.data['output']
    assert calls[0][0][-1]=='media:probe[output/take.mp4]'
    assert 'FAL_AI_API_KEY' not in calls[0][1]['env']
    assert not calls[0][1].get('shell',False)


def test_symlink_workspace_escape_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'PROJECTS_DIR',tmp_path)
    root=tmp_path/'demo';root.mkdir();(root/'project.json').write_text('{}')
    outside=tmp_path/'outside';outside.mkdir();(root/'assets').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='inside'):bridge.project('demo')


def test_no_setup_approval_or_paid_tasks_in_local_schema():
    tasks=LocalInput.model_json_schema()['properties']['task']['enum']
    assert not set(bridge.PAID_TASKS)&set(tasks)
    assert not {'setup','pipeline:all','plan:approve','openapi:fetch','media:upload','review:dialogue'}&set(tasks)


def test_local_overlay_does_not_trigger_paid_transcription(workspace,monkeypatch):
    monkeypatch.setattr(bridge,'invoke',lambda *a,**k:pytest.fail('must not invoke'))
    with pytest.raises(ValueError,match='anim:prepare'):
        AnimeLocal().execute({'project_id':'demo','task':'gen:overlay'})


def test_project_status_hash_and_run_manifest(workspace):
    _,work=workspace;(work/'output/scene-02').mkdir(parents=True)
    (work/'output/scene-02/manifest.json').write_text('{"shots":{"path":"take.mp4"}}')
    result=AnimeProject().execute({'project_id':'demo','run':'scene-02'})
    assert result.data['manifest']['shots']['path']=='take.mp4'
    assert result.data['plan_sha256']==generation(work)['plan_sha256']


def test_initialize_never_overwrites_project(workspace):
    with pytest.raises(ValueError,match='already exists'):
        AnimeProject().execute({'project_id':'demo','action':'initialize','story':'A new story'})


def test_project_references_are_bounded_and_real(workspace):
    result=AnimeProject().execute({'project_id':'demo','action':'reference','reference':'planning.md'})
    assert len(result.data['text'])>100
    with pytest.raises(ValueError,match='Choose a reference'):
        AnimeProject().execute({'project_id':'demo','action':'reference','reference':'../../.env'})


def test_mcp_can_author_prompts_and_detect_conflicting_edits(workspace):
    tool=AnimeProject();base={'project_id':'demo','relative_path':'prompts/scene-01/04_shots.yml'}
    written=tool.execute({**base,'action':'write_file','content':'- name: shot-1\n  frames: 48\n'})
    read=tool.execute({**base,'action':'read_file'})
    assert read.data['sha256']==written.data['sha256']
    assert not written.data['executed']
    with pytest.raises(ValueError,match='read_file'):
        tool.execute({**base,'action':'write_file','content':'changed'})
    updated=tool.execute({**base,'action':'write_file','expected_sha256':read.data['sha256'],'content':'revised'})
    assert updated.success
    for path in ['../escape.rb','lib/tasks.rb','config/approval.json']:
        with pytest.raises(ValueError):
            tool.execute({'project_id':'demo','action':'write_file','relative_path':path,'content':'blocked'})


def test_timeout_returns_uncertain_cost_for_paid_task(workspace,monkeypatch,tmp_path):
    rt=tmp_path/'runtime';rt.mkdir();(rt/'mv.rb').touch()
    monkeypatch.setattr(bridge,'runtime',lambda:rt);monkeypatch.setattr(bridge,'ruby',lambda:'/ruby')
    monkeypatch.setattr(bridge.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('ruby',1)))
    result=bridge.invoke(workspace[1],'gen:shots',paid=True)
    assert not result.success and result.cost_usd is None and 'receipts' in result.error


def test_registry_and_pipelines_expose_anime():
    from tools.tool_registry import ToolRegistry
    from lib.pipeline_loader import load_pipeline
    registry=ToolRegistry();registry.discover()
    assert {'anime_project','anime_local','anime_generate'}<=registry._tools.keys()
    for name in ['animation','cinematic','animated-explainer','hybrid']:
        manifest=load_pipeline(name)
        assets=next(s for s in manifest['stages'] if s['name']=='assets')
        assert {'anime_project','anime_local','anime_generate'}<=set(assets['tools_available'])
