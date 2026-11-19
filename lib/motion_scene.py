"""Bounded, versioned data contract for local motion recipes."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

RECIPES = {
 'media': ('canvas', 'Approved local image with deterministic pan and zoom'),
 'sketch': ('roughjs', 'Seeded hand-drawn rectangle or ellipse'),
 'morph': ('flubber', 'Interpolate two SVG paths'),
 'diagram': ('elkjs', 'Lay out and reveal a directed graph'),
 'lottie': ('lottie-web', 'Seek an embedded, vector-only Lottie animation'),
 'transition': ('gl-transitions', 'Shader transition between two colors'),
 'physics': ('matter-js', 'Fixed-step falling boxes'),
 'particles': ('@tsparticles/engine', 'Seeded particles with a manually advanced clock'),
 'chart': ('vega', 'Data-driven bar chart'),
 'map': ('maplibre-gl', 'Offline GeoJSON route reveal'),
 'mouth': ('rhubarb', 'Play Rhubarb mouth cues on a simple original face'),
}

class Strict(BaseModel):
 model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Node(Strict):
 id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,39}$')
 label: str = Field(max_length=40)

class Edge(Strict):
 source: str
 target: str

class Datum(Strict):
 label: str = Field(max_length=30)
 value: float = Field(ge=0, le=1e9)

class MouthCue(Strict):
 start: float = Field(ge=0, le=60)
 end: float = Field(gt=0, le=60)
 value: Literal['A','B','C','D','E','F','G','H','X']
 @model_validator(mode='after')
 def ordered(self):
  if self.end <= self.start: raise ValueError('end must exceed start')
  return self

class Object(Strict):
 id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,39}$')
 recipe: Literal['media','sketch','morph','diagram','lottie','transition','physics','particles','chart','map','mouth']
 x: int = Field(default=40, ge=0, le=1920)
 y: int = Field(default=40, ge=0, le=1920)
 width: int = Field(default=400, ge=32, le=1920)
 height: int = Field(default=300, ge=32, le=1920)
 start: float = Field(default=0, ge=0, le=60)
 duration: float = Field(default=2, gt=0, le=60)
 color: str = Field(default='#66ccaa', pattern=r'^#[0-9a-fA-F]{6}$')
 secondary: str = Field(default='#ed7755', pattern=r'^#[0-9a-fA-F]{6}$')
 label: str = Field(default='', max_length=80)
 image_path: str | None = Field(default=None, description='Approved local PNG/JPEG/WebP asset; embedded at render time.')
 mouth_images: dict[Literal['A','B','C','D','E','F','G','H','X'],str] = Field(default_factory=dict, description='Reusable face sprite images for each Rhubarb cue; X is the rest pose.')
 zoom_end: float = Field(default=1, ge=1, le=2)
 pan_x: float = Field(default=0, ge=-0.5, le=0.5)
 pan_y: float = Field(default=0, ge=-0.5, le=0.5)
 shape: Literal['rectangle','ellipse'] = 'rectangle'
 from_path: str = Field(default='', max_length=4000, pattern=r'^[MmLlHhVvCcSsQqTtAaZz0-9eE., +\-]*$')
 to_path: str = Field(default='', max_length=4000, pattern=r'^[MmLlHhVvCcSsQqTtAaZz0-9eE., +\-]*$')
 nodes: list[Node] = Field(default_factory=list, max_length=20)
 edges: list[Edge] = Field(default_factory=list, max_length=40)
 data: list[Datum] = Field(default_factory=list, max_length=20)
 animation: dict = Field(default_factory=dict, description='Embedded vector-only Lottie JSON; no URLs, images or expressions.')
 effect: Literal['fade','wipeLeft','circleopen'] = 'fade'
 count: int = Field(default=20, ge=1, le=100)
 coordinates: list[tuple[float,float]] = Field(default_factory=list, max_length=100)
 mouth_cues: list[MouthCue] = Field(default_factory=list, max_length=1000)
 @model_validator(mode='after')
 def recipe_inputs(self):
  if self.recipe == 'media' and not self.image_path: raise ValueError('media requires image_path')
  if self.mouth_images and (self.recipe!='mouth' or not {'X',*(c.value for c in self.mouth_cues)} <= set(self.mouth_images)): raise ValueError('mouth_images requires X and a sprite for every used cue')
  if self.recipe == 'morph' and not (self.from_path and self.to_path): raise ValueError('morph requires from_path and to_path')
  if self.recipe == 'diagram':
   ids=[n.id for n in self.nodes]
   if not ids or len(set(ids))!=len(ids): raise ValueError('diagram requires unique node ids')
   if any(e.source not in ids or e.target not in ids for e in self.edges): raise ValueError('edge references unknown node id')
  if self.recipe == 'chart' and not self.data: raise ValueError('chart requires data')
  if self.recipe == 'map' and (len(self.coordinates)<2 or any(not -180<=x<=180 or not -85<=y<=85 for x,y in self.coordinates)): raise ValueError('map requires at least two valid longitude/latitude coordinates')
  if self.recipe == 'mouth' and not self.mouth_cues: raise ValueError('mouth requires mouth_cues from rhubarb_lipsync')
  if self.recipe == 'lottie':
   import json
   if len(json.dumps(self.animation))>200000: raise ValueError('animation exceeds 200KB')
   if not all(k in self.animation for k in ('layers','fr','ip','op','w','h')): raise ValueError('lottie requires layers, fr, ip, op, w, h')
   a=self.animation
   for key in ('fr','w','h'):
    if type(a[key]) not in (int,float) or not 0 < a[key] <= 4096: raise ValueError(f'animation.{key} must be a positive bounded number')
   for key in ('ip','op'):
    if type(a[key]) not in (int,float) or not 0 <= a[key] <= 100000: raise ValueError(f'animation.{key} must be a bounded frame number')
   if a['op'] <= a['ip']: raise ValueError('animation.op must exceed animation.ip')
   if not isinstance(a['layers'],list) or len(a['layers'])>100 or any(not isinstance(v,dict) or type(v.get('ty')) is not int for v in a['layers']): raise ValueError('animation.layers must contain at most 100 typed layer objects')
   def inspect(v, depth=0):
    if depth>30: raise ValueError('animation nesting exceeds 30 levels')
    if isinstance(v,dict):
     if 'p' in v and isinstance(v['p'],str): raise ValueError('Lottie external/image assets are not supported')
     if 'x' in v and isinstance(v['x'],str): raise ValueError('Lottie expressions are not supported')
     for child in v.values(): inspect(child, depth+1)
    elif isinstance(v,list):
     for child in v: inspect(child, depth+1)
   inspect(self.animation)
  return self

class MotionScene(Strict):
 version: Literal['1'] = '1'
 width: int = Field(default=1280, ge=64, le=1920, multiple_of=2)
 height: int = Field(default=720, ge=64, le=1920, multiple_of=2)
 fps: int = Field(default=24, ge=1, le=60)
 duration: float = Field(default=4, gt=0, le=60)
 seed: int = Field(default=1, ge=1, le=2147483647)
 background: str = Field(default='#102030', pattern=r'^#[0-9a-fA-F]{6}$')
 reduced_motion: bool = False
 objects: list[Object] = Field(min_length=1,max_length=30)
 @model_validator(mode='after')
 def consistent(self):
  ids=[o.id for o in self.objects]
  if len(set(ids))!=len(ids): raise ValueError('objects require unique ids; one recipe owns each object')
  for o in self.objects:
   if o.x+o.width>self.width or o.y+o.height>self.height: raise ValueError(f'{o.id}: object exceeds canvas bounds')
   if o.start+o.duration>self.duration: raise ValueError(f'{o.id}: motion exceeds scene duration')
  if self.width*self.height*self.fps*self.duration>1920*1080*24*60: raise ValueError('scene exceeds render pixel budget')
  return self

def validate_scene(value):
 try:
  scene=MotionScene.model_validate(value)
  return {'valid':True,'scene':scene.model_dump(),'errors':[]}
 except ValidationError as exc:
  return {'valid':False,'errors':[{'path':'.'.join(map(str,e['loc'])),'code':e['type'],'message':e['msg'],'correction':'Use factory_motion_scene_schema and recipe examples; change the indicated field.'} for e in exc.errors()]}


def recipe_examples():
 return {
  'media': {'id':'item','recipe':'media','image_path':'/absolute/project/assets/storyboard.png','zoom_end':1.1},
  'sketch': {'id':'item','recipe':'sketch','shape':'ellipse'},
  'morph': {'id':'item','recipe':'morph','from_path':'M 20 20 L 180 20 L 180 180 L 20 180 Z','to_path':'M 100 20 L 180 180 L 20 180 Z'},
  'diagram': {'id':'item','recipe':'diagram','nodes':[{'id':'a','label':'Start'},{'id':'b','label':'Finish'}],'edges':[{'source':'a','target':'b'}]},
  'chart': {'id':'item','recipe':'chart','data':[{'label':'A','value':5},{'label':'B','value':8}]},
  'physics': {'id':'item','recipe':'physics','count':10},
  'particles': {'id':'item','recipe':'particles','count':20},
  'transition': {'id':'item','recipe':'transition','effect':'wipeLeft'},
  'map': {'id':'item','recipe':'map','coordinates':[[70,20],[80,30]]},
  'mouth': {'id':'item','recipe':'mouth','mouth_cues':[{'start':0,'end':1,'value':'D'}]},
  'lottie': {'id':'item','recipe':'lottie','animation':{'v':'5.7.4','fr':24,'ip':0,'op':48,'w':200,'h':200,'layers':[{'ty':1,'ind':1,'ip':0,'op':48,'st':0,'sw':100,'sh':100,'sc':'#66ccaa','ks':{'o':{'a':0,'k':100},'r':{'a':0,'k':0},'p':{'a':0,'k':[50,50,0]},'a':{'a':0,'k':[0,0,0]},'s':{'a':0,'k':[100,100,100]}}}]}},
 }
