import json
import sys
from pathlib import Path
import pytest
from lib.local_tts import health
from tools.audio.kokoro_tts import KokoroTTS
from tools.audio.chatterbox_tts import ChatterboxTTS
from tools.audio.tts_selector import TTSSelector


def test_health_requires_verified_model_files(tmp_path,monkeypatch):
    monkeypatch.setenv('KOKORO_PYTHON',sys.executable)
    monkeypatch.setenv('KOKORO_MODEL_DIR',str(tmp_path))
    assert health('kokoro')['status']=='unavailable'
    (tmp_path/'weights').write_bytes(b'abc')
    marker={'engine':'kokoro','verified_generation':True,'files':{'weights':3},'revision':'test'}
    (tmp_path/'ready.json').write_text(json.dumps(marker))
    assert health('kokoro')['status']=='available'
    (tmp_path/'weights').write_bytes(b'changed')
    assert health('kokoro')['status']=='unavailable'


def test_selector_adapts_local_voices_without_routing_noise():
    result=TTSSelector._adapt_inputs(KokoroTTS(),{'preferred_tool':'kokoro_tts','text':'Hello','language_code':'en-GB','output_path':'sample.wav','speaking_rate':1.1,'sample_mode':True})
    assert result=={'text':'Hello','language_code':'b','voice':'bf_emma','output_path':'sample.wav','speed':1.1}
    result=TTSSelector._adapt_inputs(ChatterboxTTS(),{'preferred_tool':'chatterbox_tts','text':'Hello','output_path':'sample.wav','exaggeration':.7,'seed':42})
    assert result['seed']==42 and result['exaggeration']==.7 and 'preferred_tool' not in result

@pytest.mark.parametrize('extra',[{'timestamps':True},{'input_type':'ssml'},{'voice':'af_heart'},{'speed':1.5}])
def test_chatterbox_rejects_unsupported_selector_controls(extra):
    with pytest.raises(ValueError): TTSSelector._adapt_inputs(ChatterboxTTS(),{'text':'Hello',**extra})


def test_native_validation_no_model_load():
    r=ChatterboxTTS().execute({'text':'Hello','output_path':'speech.wav','language_code':'hi'})
    assert not r.success and 'multilingual' in r.error
    r=KokoroTTS().execute({'text':'Hello','output_path':'speech.wav','language_code':'a','voice':'../../bad'})
    assert not r.success


def test_atomic_output_on_worker_failure(tmp_path,monkeypatch):
    import lib.local_tts as bridge
    out=tmp_path/'speech.wav';out.write_bytes(b'previous')
    monkeypatch.setattr(bridge,'health',lambda *args:{'status':'available'})
    monkeypatch.setattr(bridge,'runtime',lambda engine:Path('/missing/python'))
    r=bridge.synthesize('kokoro',{'text':'Hello','output_path':str(out)})
    assert not r.success and out.read_bytes()==b'previous'

def test_animation_permits_native_offline_voice_routes():
    from lib.pipeline_loader import load_pipeline,get_stage_tools
    for pipeline in ('animation','animated-explainer','character-animation','cinematic'):
        assert {'kokoro_tts','chatterbox_tts'} <= set(get_stage_tools(load_pipeline(pipeline),'assets'))
