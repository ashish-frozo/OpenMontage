import json
import pytest
from lib.motion_scene import validate_scene
from tools.graphics.motion_scene import MotionScene

def test_scene_validation():
 assert validate_scene({'objects':[{'id':'a','recipe':'sketch'}]})['valid']
 for obj in [{'id':'a','recipe':'unknown'},{'id':'a','recipe':'sketch','width':1920},{'id':'a','recipe':'morph'},{'id':'a','recipe':'sketch','start':59}]:
  result=validate_scene({'objects':[obj]});assert not result['valid'];assert result['errors'][0]['message']
 assert not validate_scene({'objects':[{'id':'a','recipe':'sketch'}]*2})['valid']

def cases():
 return [
  {'recipe':'sketch'},
  {'recipe':'morph','from_path':'M 20 20 L 180 20 L 180 180 L 20 180 Z','to_path':'M 100 20 L 180 180 L 20 180 Z'},
  {'recipe':'diagram','nodes':[{'id':'a','label':'Start'},{'id':'b','label':'End'}],'edges':[{'source':'a','target':'b'}]},
  {'recipe':'transition'}, {'recipe':'physics'}, {'recipe':'particles'},
  {'recipe':'chart','data':[{'label':'A','value':5},{'label':'B','value':8}]},
  {'recipe':'map','coordinates':[[70,20],[80,30]]},
  {'recipe':'mouth','mouth_cues':[{'start':0,'end':1,'value':'D'}]},
  {'recipe':'lottie','animation':{'v':'5.7.4','fr':24,'ip':0,'op':48,'w':200,'h':200,'layers':[{'ty':1,'ind':1,'ip':0,'op':48,'st':0,'sw':100,'sh':100,'sc':'#66ccaa','ks':{'o':{'a':0,'k':100},'r':{'a':0,'k':0},'p':{'a':0,'k':[50,50,0]},'a':{'a':0,'k':[0,0,0]},'s':{'a':0,'k':[100,100,100]}}}]}}
 ]

@pytest.mark.parametrize('obj',cases(),ids=lambda o:o['recipe'])
def test_visual_recipe(obj,tmp_path):
 scene={'width':480,'height':360,'duration':2,'fps':12,'objects':[{'id':'item','x':10,'y':10,'width':440,'height':320,**obj}]}
 result=MotionScene().execute({'scene':scene,'output_path':str(tmp_path/obj['recipe'])})
 assert result.success,result.error
 assert result.data['verification']['deterministic']
 assert len(list(__import__('pathlib').Path(result.data['output_path']).glob('*.png')))==3

def test_otio_roundtrip(tmp_path):
 import opentimelineio as otio
 from tools.video.timeline_export import TimelineExport
 out=tmp_path/'edit.otio'
 result=TimelineExport().execute({'clips':[{'path':'test.mp4','start':2,'duration':3}],'output_path':str(out)})
 assert result.success
 timeline=otio.adapters.read_from_file(str(out));assert timeline.duration().to_seconds()==3

def test_rejects_lottie_expressions_and_nonfinite():
 animation=cases()[-1]['animation']
 import copy
 unsafe=copy.deepcopy(animation);unsafe['layers'][0]['ks']['o']['x']='alert(1)'
 assert not validate_scene({'objects':[{'id':'a','recipe':'lottie','animation':unsafe}]})['valid']
 assert not validate_scene({'objects':[{'id':'a','recipe':'sketch','start':float('nan')}]})['valid']

def test_render_mp4(tmp_path):
 import subprocess
 output=tmp_path/'clip.mp4'
 result=MotionScene().execute({'scene':{'width':320,'height':240,'duration':1,'fps':6,'objects':[{'id':'a','recipe':'sketch','x':10,'y':10,'width':280,'height':200,'duration':1}]},'mode':'render','output_path':str(output)})
 assert result.success,result.error
 probe=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-show_streams','-of','json',str(output)]))
 assert int(probe['streams'][0]['nb_frames'])==6
 assert probe['streams'][0]['width']==320

def test_rhubarb_health_rejects_incompatible_binary(tmp_path,monkeypatch):
 from tools.audio.rhubarb_lipsync import RhubarbLipsync
 from tools.base_tool import ToolStatus
 executable=tmp_path/'rhubarb';executable.write_text('not executable');monkeypatch.setenv('RHUBARB_BINARY',str(executable))
 assert RhubarbLipsync().get_status()==ToolStatus.UNAVAILABLE

def test_rhubarb_adapter(tmp_path,monkeypatch):
 from tools.audio.rhubarb_lipsync import RhubarbLipsync
 executable=tmp_path/'rhubarb'
 executable.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then exit 0; fi\nprintf \'{"mouthCues":[{"start":0,"end":1,"value":"A"}]}\' > "$6"\n');executable.chmod(0o755)
 monkeypatch.setenv('RHUBARB_BINARY',str(executable))
 result=RhubarbLipsync().execute({'audio_path':'sample.wav','output_path':str(tmp_path/'mouth.json')})
 assert result.success
 assert result.data['mouthCues'][0]['value']=='A'
