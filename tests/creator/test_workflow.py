import copy
import json
from pathlib import Path
import pytest
from PIL import Image
from lib.creator import review_scene_plan, revision_plan, RevisionRequest
from lib.creator_media import run, probe
from schemas.artifacts import validate_artifact

@pytest.fixture
def plan():
    return {'version':'1.1','scenes':[{'id':f's{i}','type':'anime_scene','description':f'Shot {i}','start_seconds':i-1,'end_seconds':i,'shot_intent':'Show evidence','narrative_role':'evidence','metadata':{'voice':'approved'}} for i in (1,2)]}

@pytest.fixture
def media(tmp_path):
    a=tmp_path/'red.png';b=tmp_path/'blue.png'
    Image.new('RGB',(320,240),'red').save(a);Image.new('RGB',(320,240),'blue').save(b)
    wav=tmp_path/'tone.wav';run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=3','-c:a','pcm_s16le',str(wav)])
    return a,b,wav

def test_contract_and_continuity(plan):
    validate_artifact('scene_plan',plan)
    bad=copy.deepcopy(plan);del bad['scenes'][0]['shot_intent']
    with pytest.raises(Exception): validate_artifact('scene_plan',bad)
    plan['scenes'][0]['continuity']=[{'entity_id':'product','state_in':{'color':'red'},'state_out':{'color':'red'}}]
    plan['scenes'][1]['continuity']=[{'entity_id':'product','state_in':{'color':'blue'},'state_out':{'color':'blue'}}]
    assert review_scene_plan(plan)['issues'][0]['kind']=='continuity_change'
    plan['scenes'][1]['continuity'][0]['change_reason']='Show blue variant'
    assert review_scene_plan(plan)['ready']

def test_revision_locks_staleness_and_ripple(plan):
    args={'scene_plan':plan,'expected_fingerprint':review_scene_plan(plan)['fingerprint'],'changes':[{'shot_id':'s1','note':'Shorten opening','at_seconds':.5,'set_fields':{'end_seconds':.5}}],'locks':{'s1':['metadata.voice']},'ripple':True}
    result=revision_plan(RevisionRequest(**args))
    assert result['rerender_shot_ids']==['s1'] and result['retime_shot_ids']==['s2']
    assert result['candidate']['scenes'][1]['start_seconds']==.5
    args['locks']={'s2':['start_seconds']}
    with pytest.raises(ValueError,match='Locked'): revision_plan(RevisionRequest(**args))
    args['expected_fingerprint']='stale'
    with pytest.raises(ValueError,match='changed'): revision_plan(RevisionRequest(**args))

def test_animatic_selective_rerender_and_audio(plan,media,tmp_path):
    from tools.video.animatic import Animatic
    a,b,wav=media;out=tmp_path/'animatic.mp4'
    args={'scene_plan':plan,'frames':[{'shot_id':'s1','path':str(a),'caption':'Evidence one'},{'shot_id':'s2','path':str(b),'caption':'Evidence two'}], 'sound_cues':[{'id':'voice','role':'narration','path':str(wav),'start':0,'duration':2,'intent':'temporary timing'}],'output_path':str(out),'width':320,'height':240,'fps':6}
    first=Animatic().execute(args);assert first.success and len(first.data['rendered_shots'])==2
    assert any(s['codec_type']=='audio' for s in probe(out)['streams'])
    args['scene_plan']['scenes'][0]['description']='New hook'
    second=Animatic().execute(args)
    assert second.data['rendered_shots']==['s1'] and second.data['reused_shots']==['s2']
    assert 'Evidence two' in out.with_suffix('.srt').read_text()

def test_sound_mix_and_silence(media,tmp_path):
    from tools.audio.sound_design import SoundDesign
    _,_,wav=media
    r=SoundDesign().execute({'cues':[{'id':'voice','role':'narration','path':str(wav),'start':0,'duration':2,'intent':'speech'},{'id':'music','role':'music','path':str(wav),'start':0,'duration':2,'gain':.2,'intent':'bed'},{'id':'pause','role':'silence','start':1,'duration':.5,'intent':'dramatic pause'}],'duration':2,'export_stems':True,'output_path':str(tmp_path/'mix.wav')})
    assert r.success and r.data['ducking'] and 'input_i' in r.data['measured_loudness']
    assert {s['role'] for s in r.data['stems']}=={'narration','music'}

def test_transition_quality_handoff(plan,media,tmp_path):
    from tools.video.media_transition import MediaTransition
    from tools.video.creator_quality import CreatorQuality
    from tools.video.editor_package import EditorPackage
    import opentimelineio as otio
    a,b,wav=media;out=tmp_path/'transition.mp4'
    r=MediaTransition().execute({'from_path':str(a),'to_path':str(b),'from_duration':1.25,'to_duration':1.25,'transition_duration':.5,'output_path':str(out),'width':320,'height':240,'fps':12})
    assert r.success and abs(float(probe(out)['format']['duration'])-2)<.1
    srt=tmp_path/'captions.srt';srt.write_text('1\n00:00:00,000 --> 00:00:03,000\nA caption\n')
    q=CreatorQuality().execute({'path':str(out),'scene_plan':plan,'output_path':str(tmp_path/'quality.json'),'captions_path':str(srt)})
    assert q.success and q.data['sample_count']>=5
    assert any(i['kind']=='caption_timing' for i in q.data['issues'])
    package=tmp_path/'handoff'
    r=EditorPackage().execute({'clips':[{'id':'picture','path':str(out),'duration':2,'effects':['color grade']},{'id':'voice','path':str(wav),'duration':2,'track':'Voice stem','kind':'Audio'}],'markers':[{'name':'Revise hook','start':.5}],'captions_path':str(srt),'output_path':str(package)})
    assert r.success and r.data['unsupported_effects']
    timeline=otio.adapters.read_from_file(str(package/'timeline.otio'))
    assert len(timeline.tracks)==2 and len(timeline.tracks.markers)==1
    assert (package/timeline.tracks[0][0].media_reference.target_url).exists()

def test_media_motion_and_custom_rig(media,tmp_path):
    from tools.graphics.motion_scene import MotionScene
    a,b,_=media
    for obj in [{'recipe':'media','image_path':str(a),'zoom_end':1.2},{'recipe':'mouth','mouth_images':{'X':str(a),'D':str(b)},'mouth_cues':[{'start':0,'end':.5,'value':'D'}]}]:
        r=MotionScene().execute({'scene':{'width':320,'height':240,'duration':1,'fps':6,'objects':[{'id':'subject','x':0,'y':0,'width':320,'height':240,'duration':1,**obj}]},'output_path':str(tmp_path/obj['recipe'])})
        assert r.success,r.error
        assert r.data['verification']['deterministic']

def test_persist_revision_invalidates_routes_and_keeps_locks(plan,tmp_path):
    from content_factory.creator import save_revision
    from content_factory.service import Factory
    from content_factory.registry import Registry
    from content_factory.models import ProjectConfig
    from lib.checkpoint import write_checkpoint
    factory=Factory(Registry([]),tmp_path)
    factory.create('revision-film','Revision test','animation',ProjectConfig())
    write_checkpoint(tmp_path,'revision-film','scene_plan','in_progress',{'scene_plan':plan},pipeline_type='animation',metadata={'creator_locks':{'s1':['metadata.voice']}})
    write_checkpoint(tmp_path,'revision-film','assets','failed',{},pipeline_type='animation')
    request=RevisionRequest(scene_plan=plan,expected_fingerprint=review_scene_plan(plan)['fingerprint'],changes=[{'shot_id':'s1','note':'New hook','set_fields':{'description':'New hook'}}])
    result=save_revision(factory,'revision-film',request)
    assert result['saved'] and factory.settings('revision-film')[0]==2
    checkpoint=json.loads((tmp_path/'revision-film/checkpoint_scene_plan.json').read_text())
    assert checkpoint['status']=='in_progress' and not checkpoint['human_approved']
    assert checkpoint['metadata']['creator_locks']['s1']==['metadata.voice']
    assert json.loads((tmp_path/'revision-film/checkpoint_assets.json').read_text())['status']=='failed'
    assert list((tmp_path/'revision-film/artifacts/creator-revisions').glob('*.json'))

def test_nested_patch_preserves_siblings_and_rejects_locked_voice(plan):
    args={'scene_plan':plan,'expected_fingerprint':review_scene_plan(plan)['fingerprint'],'changes':[{'shot_id':'s1','note':'New background','set_fields':{'metadata.background':'cream'}}],'locks':{'s1':['metadata.voice']}}
    r=revision_plan(RevisionRequest(**args))
    assert r['candidate']['scenes'][0]['metadata']=={'voice':'approved','background':'cream'}
    args['changes'][0]['set_fields']={'metadata.voice':'different'}
    with pytest.raises(ValueError,match='Locked'): revision_plan(RevisionRequest(**args))

def test_creator_mcp_discovery(tmp_path):
    import asyncio
    from content_factory.server import build_server
    from content_factory.service import Factory
    from content_factory.registry import Registry
    server=build_server(Factory(Registry([]),tmp_path))
    names={t.name for t in asyncio.run(server.list_tools())}
    assert {'factory_preview_revision','factory_save_revision','factory_review_scene_plan'}<=names
