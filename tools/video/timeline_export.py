"""Export explicit clip timing as native OpenTimelineIO, without rendering."""
import importlib.util
from pathlib import Path
from tools.base_tool import BaseTool,ToolResult,ToolStatus

class TimelineExport(BaseTool):
 name='timeline_export'
 capability='video_post'
 provider='opentimelineio'
 version='1.0.0'
 dependencies=['python:opentimelineio']
 install_instructions='pip install -r requirements-motion.txt'
 input_schema={'type':'object','additionalProperties':False,'required':['clips','output_path'],'properties':{'output_path':{'type':'string'},'fps':{'type':'number','exclusiveMinimum':0,'maximum':120,'default':24},'clips':{'type':'array','minItems':1,'maxItems':1000,'items':{'type':'object','additionalProperties':False,'required':['path','duration'],'properties':{'path':{'type':'string'},'start':{'type':'number','minimum':0,'default':0},'duration':{'type':'number','exclusiveMinimum':0},'name':{'type':'string'}}}}}}
 def execute(self,inputs):
  import jsonschema
  jsonschema.validate(inputs,self.input_schema)
  import opentimelineio as otio
  fps=inputs.get('fps',24);timeline=otio.schema.Timeline(name='OpenMontage');track=otio.schema.Track();timeline.tracks.append(track)
  for c in inputs['clips']:
   track.append(otio.schema.Clip(name=c.get('name',Path(c['path']).name),media_reference=otio.schema.ExternalReference(target_url=Path(c['path']).resolve().as_uri()),source_range=otio.opentime.TimeRange(otio.opentime.RationalTime(c.get('start',0)*fps,fps),otio.opentime.RationalTime(c['duration']*fps,fps))))
  output=Path(inputs['output_path']);output.parent.mkdir(parents=True,exist_ok=True);otio.adapters.write_to_file(timeline,str(output),adapter_name='otio_json')
  return ToolResult(success=True,data={'output_path':str(output),'effects_preserved':False},artifacts=[str(output)])
