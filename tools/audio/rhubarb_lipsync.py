"""Convert narration into timed cartoon mouth shapes with local Rhubarb."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from tools.base_tool import BaseTool,ToolResult,ToolStatus

class RhubarbLipsync(BaseTool):
 name='rhubarb_lipsync'
 capability='character_animation'
 provider='rhubarb'
 version='1.0.0'
 install_instructions='Install Rhubarb Lip Sync and put rhubarb on PATH, or set RHUBARB_BINARY to the executable.'
 best_for=['offline cartoon mouth timing']
 agent_skills=['motion-recipes']
 input_schema={'type':'object','additionalProperties':False,'required':['audio_path','output_path'],'properties':{'audio_path':{'type':'string'},'output_path':{'type':'string'},'recognizer':{'type':'string','enum':['pocketSphinx','phonetic'],'default':'phonetic'}}}
 def binary(self):
  from lib.paths import REPO_ROOT
  installed=REPO_ROOT/'.runtime/rhubarb/Rhubarb-Lip-Sync-1.14.0-macOS/rhubarb'
  return os.environ.get('RHUBARB_BINARY') or shutil.which('rhubarb') or (str(installed) if installed.is_file() else None)
 def get_status(self):
  if not self.binary(): return ToolStatus.UNAVAILABLE
  try:
   result=subprocess.run([self.binary(),'--version'],capture_output=True,timeout=5)
   return ToolStatus.AVAILABLE if result.returncode==0 else ToolStatus.UNAVAILABLE
  except (OSError,subprocess.SubprocessError): return ToolStatus.UNAVAILABLE
 def execute(self,inputs):
  import jsonschema
  jsonschema.validate(inputs,self.input_schema)
  if self.get_status()!=ToolStatus.AVAILABLE: return ToolResult(success=False,error=self.install_instructions)
  path=Path(inputs['output_path']);path.parent.mkdir(parents=True,exist_ok=True)
  try:
   subprocess.run([self.binary(),'-f','json','-r',inputs.get('recognizer','phonetic'),'-o',str(path),inputs['audio_path']],check=True,capture_output=True,text=True,timeout=300)
   data=json.loads(path.read_text())
   return ToolResult(success=True,data=data,artifacts=[str(path)])
  except (OSError,ValueError,subprocess.SubprocessError) as exc:return ToolResult(success=False,error=str(exc))
