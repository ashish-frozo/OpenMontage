"""Render bounded data-driven motion scenes to previews or MP4 assets."""
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from pydantic import Field
from typing import Literal
from lib.motion_scene import MotionScene as Scene, Strict, validate_scene
from lib.paths import REPO_ROOT
from tools.base_tool import BaseTool, ToolResult, ToolStatus, Determinism

RUNTIME=REPO_ROOT/'motion-runtime'

class SceneRequest(Strict):
 scene: Scene
 output_path: str
 mode: Literal['preview','render'] = 'preview'

class MotionScene(BaseTool):
 name='motion_scene'
 provider='openmontage'
 capability='procedural_animation'
 version='1.0.0'
 determinism=Determinism.SEEDED
 input_schema=SceneRequest.model_json_schema()
 dependencies=['cmd:node','cmd:ffmpeg']
 best_for=['validated motion recipes','small-model animation authoring','deterministic previews']
 not_good_for=['bespoke hero films','photorealistic footage']
 supports={'recipes':['media','sketch','morph','diagram','lottie','transition','physics','particles','chart','map','mouth']}
 agent_skills=['motion-recipes']
 install_instructions='cd motion-runtime && npm ci && node build.mjs && npx playwright install chromium; install ffmpeg.'
 def get_status(self):
  if not shutil.which('node') or not shutil.which('ffmpeg'): return ToolStatus.UNAVAILABLE
  try:
   check=subprocess.run(['node','health.mjs'],cwd=RUNTIME,capture_output=True,timeout=10)
   return ToolStatus.AVAILABLE if check.returncode==0 else ToolStatus.UNAVAILABLE
  except (OSError,subprocess.SubprocessError): return ToolStatus.UNAVAILABLE
 def execute(self,inputs):
  result=validate_scene(inputs.get('scene'))
  if not result['valid']: return ToolResult(success=False,data=result,error='Invalid scene; repair the indicated fields')
  request=SceneRequest.model_validate(inputs)
  output=Path(request.output_path).resolve()
  if request.mode=='render' and output.suffix!='.mp4': return ToolResult(success=False,error='render output_path must end in .mp4')
  output.parent.mkdir(parents=True,exist_ok=True)
  manifest=None
  if request.mode=='preview':
   output.mkdir(parents=True,exist_ok=True)
   manifest=output/'latest.json'
   pending=output/('pending-'+uuid.uuid4().hex+'.json')
   pending.write_text(json.dumps({'status':'in_progress','output_path':None}))
   pending.replace(manifest)
   output=output/('run-'+uuid.uuid4().hex)
  try:
   with tempfile.TemporaryDirectory() as tmp:
    spec=Path(tmp)/'scene.json'
    # Convert approved files to bounded raster data; no file URLs or SVG scripts enter the browser.
    import base64, io
    from PIL import Image
    def embed(path):
     source=Path(path).expanduser().resolve(strict=True)
     if source.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'} or source.stat().st_size>20_000_000: raise ValueError('Use a PNG/JPEG/WebP smaller than 20MB')
     with Image.open(source) as im:
      if im.width*im.height>20_000_000: raise ValueError('Image exceeds 20 megapixels')
      im=im.convert('RGBA');im.thumbnail((1920,1920));data=io.BytesIO();im.save(data,format='PNG')
     return 'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
    for obj in result['scene']['objects']:
     if obj.get('image_path'): obj['image_data']=embed(obj['image_path'])
     if obj.get('mouth_images'): obj['mouth_data']={k:embed(v) for k,v in obj['mouth_images'].items()}
    spec.write_text(json.dumps(result['scene']))
    frames=Path(tmp)/'frames' if request.mode=='render' else output
    subprocess.run(['node','render.mjs',str(spec),str(frames),request.mode],cwd=RUNTIME,check=True,capture_output=True,text=True,timeout=600)
    report=json.loads((frames/'report.json').read_text())
    if request.mode=='render':
     subprocess.run(['ffmpeg','-y','-framerate',str(request.scene.fps),'-i',str(frames/'%06d.png'),'-c:v','libx264','-pix_fmt','yuv420p',str(output)],check=True,capture_output=True,text=True,timeout=300)
    if manifest:
     pending=manifest.with_name('complete-'+uuid.uuid4().hex+'.json')
     pending.write_text(json.dumps({'status':'completed','output_path':str(output),'verification':report}))
     pending.replace(manifest)
    return ToolResult(success=True,data={'output_path':str(output),'verification':report,'recipe_version':'1'},artifacts=[str(output)])
  except (OSError,subprocess.SubprocessError) as exc:
   if manifest:
    pending=manifest.with_name('failed-'+uuid.uuid4().hex+'.json')
    pending.write_text(json.dumps({'status':'failed','output_path':None}))
    pending.replace(manifest)
   return ToolResult(success=False,error=(getattr(exc,'stderr',None) or str(exc))[-4000:])
