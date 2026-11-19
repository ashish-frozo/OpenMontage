import json,subprocess
from pathlib import Path
import pytest
from tools.analysis import rea_video as r

@pytest.fixture
def project(tmp_path,monkeypatch):
    root=tmp_path/'projects';p=root/'demo';(p/'assets').mkdir(parents=True);(p/'project.json').write_text('{}');(p/'assets/source.mp4').write_bytes(b'video')
    monkeypatch.setattr(r,'PROJECTS_DIR',root);return p

def test_rejects_path_escape(project):
    with pytest.raises(ValueError,match='remain'):r.scoped('demo','../../outside')
    with pytest.raises(ValueError,match='assets'):r.scoped('demo','artifacts/out',True)

def test_symlink_escape(project,tmp_path):
    outside=tmp_path/'outside.mp4';outside.write_bytes(b'video');(project/'assets/link.mp4').symlink_to(outside)
    with pytest.raises(ValueError):r.scoped('demo','assets/link.mp4')

def test_no_overwriting_analysis(project):
    (project/'assets/report').mkdir()
    with pytest.raises(ValueError,match='exists'):
        r.ReaVideoAnalyze().execute({'project_id':'demo','video_path':'assets/source.mp4','analysis_dir':'assets/report'})

def test_analysis_disables_hidden_models_and_bounds_context(project,monkeypatch):
    monkeypatch.setattr(r.subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,0,stdout='{"format":{"duration":"2"}}',stderr=''))
    def run(self,cmd,root,timeout):
        assert all(x in cmd for x in ('--no-vlm','--no-whole','--no-asr','--no-ocr','--no-stems','--no-speakers','--no-packaging'))
        out=project/'assets/report';(out/'VIDEO.md').write_text('x'*13000)
        return subprocess.CompletedProcess(cmd,0,stdout='two shots',stderr='')
    monkeypatch.setattr(r._ReaBase,'run',run)
    result=r.ReaVideoAnalyze().execute({'project_id':'demo','video_path':'assets/source.mp4','analysis_dir':'assets/report'})
    assert result.success and len(result.data['VIDEO_md'])==12000 and result.cost_usd==0

def test_review_requires_answers(project):
    out=project/'assets/report';out.mkdir();(out/'breakdown.json').write_text('{}')
    with pytest.raises(ValueError,match='answers_path'):r.ReaVideoReview().execute({'project_id':'demo','analysis_dir':'assets/report','action':'apply_review'})

def test_registry_discovers_tools():
    from tools.tool_registry import registry
    registry.discover()
    assert registry.get('rea_video_analyze').provider=='rea_video'
    assert registry.get('rea_video_review').input_schema['properties']['action']['enum']==['summary','prepare_review','apply_review','validate']

def test_health_detects_broken_ffprobe(monkeypatch):
    import sys
    monkeypatch.setattr(r._ReaBase,'python',property(lambda self:Path(sys.executable)))
    monkeypatch.setattr(r.shutil,'which',lambda name:'/usr/bin/'+name)
    monkeypatch.setattr(r.subprocess,'run',lambda cmd,**kw:subprocess.CompletedProcess(cmd,-6 if cmd[0]=='ffprobe' else 0))
    assert r.ReaVideoAnalyze().get_status()==r.ToolStatus.UNAVAILABLE
