"""Render a cheap storyboard animatic with shot caching, captions and temporary audio."""
import hashlib
import json
import math
import shutil
import tempfile
import uuid
from pathlib import Path
from pydantic import Field
from lib.creator import Strict, SoundCue, fingerprint, review_scene_plan
from lib.creator_media import run, media_file, sound_mix, probe
from tools.base_tool import BaseTool, ToolResult

class StoryboardFrame(Strict):
    shot_id: str
    path: str | None = None
    source_start: float = Field(default=0,ge=0)
    caption: str = Field(default='',max_length=1000)

class AnimaticInput(Strict):
    scene_plan: dict
    frames: list[StoryboardFrame] = Field(default_factory=list,max_length=200)
    sound_cues: list[SoundCue] = Field(default_factory=list,max_length=200)
    output_path: str
    width: int = Field(default=640,ge=160,le=1280,multiple_of=2)
    height: int = Field(default=360,ge=160,le=1280,multiple_of=2)
    fps: int = Field(default=12,ge=1,le=30)

class Animatic(BaseTool):
    name='animatic'
    capability='video_post'
    version='1.0.0'
    dependencies=['cmd:ffmpeg','cmd:ffprobe','python:PIL']
    input_schema=AnimaticInput.model_json_schema()
    best_for=['storyboard timing review','low-cost rough cuts','selective shot rerendering']
    agent_skills=['creator-workflow']

    def execute(self,inputs):
        from PIL import Image, ImageDraw, ImageFont
        p=AnimaticInput.model_validate(inputs);review=review_scene_plan(p.scene_plan)
        if any(i['kind']=='gap' for i in review['issues']): raise ValueError('Animatic requires contiguous scenes; represent intentional gaps as explicit shots')
        if review['duration']>600 or len(p.scene_plan['scenes'])>200: raise ValueError('Animatic limit: 600 seconds and 200 shots')
        output=Path(p.output_path).resolve()
        if output.suffix!='.mp4': raise ValueError('output_path must end in .mp4')
        output.parent.mkdir(parents=True,exist_ok=True)
        cache=output.parent/'.animatic-cache';cache.mkdir(exist_ok=True)
        frames={f.shot_id:f for f in p.frames}
        ids={s['id'] for s in p.scene_plan['scenes']}
        if len(frames)!=len(p.frames) or not set(frames)<=ids: raise ValueError('Storyboard frames require unique known shot ids')
        clips=[];rendered=[];reused=[];subtitles=[];markers=[];cursor=0
        with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
            tmp=Path(tmp)
            for shot in p.scene_plan['scenes']:
                f=frames.get(shot['id'],StoryboardFrame(shot_id=shot['id']))
                duration=shot['end_seconds']-shot['start_seconds'];count=max(1,round(duration*p.fps));actual=count/p.fps
                source=media_file(f.path) if f.path else None
                source_hash=hashlib.sha256(source.read_bytes()).hexdigest() if source else None
                key=fingerprint({'v':1,'shot':{k:v for k,v in shot.items() if k not in ('start_seconds','end_seconds')},'frames':count,'frame':f.model_dump(),'source_hash':source_hash,'size':[p.width,p.height,p.fps]})
                clip=cache/(key+'.mp4')
                if clip.exists(): reused.append(shot['id'])
                else:
                    args=['ffmpeg','-v','error','-y']
                    if source and source.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:
                        info=probe(source)
                        if f.source_start+actual>float(info['format']['duration'])+1/p.fps: raise ValueError(f"{shot['id']}: video too short for storyboard shot")
                        args+=['-ss',str(f.source_start),'-i',str(source)]
                    else:
                        if not source:
                            source=tmp/'card.png';im=Image.new('RGB',(p.width,p.height),'#152536');draw=ImageDraw.Draw(im)
                            font=ImageFont.load_default(size=max(14,p.height//18))
                            import textwrap
                            text=shot['id']+'\n\n'+'\n'.join(textwrap.wrap(shot['description'],max(12,p.width//(p.height//30+6))))
                            draw.multiline_text((24,24),text,fill='white',font=font,spacing=8);im.save(source)
                        args+=['-loop','1','-i',str(source)]
                    pending=tmp/(key+'.mp4')
                    run(args+['-an','-vf',f'scale={p.width}:{p.height}:force_original_aspect_ratio=decrease,pad={p.width}:{p.height}:(ow-iw)/2:(oh-ih)/2,setsar=1', '-r',str(p.fps),'-frames:v',str(count),'-c:v','libx264','-pix_fmt','yuv420p',str(pending)])
                    pending.replace(clip);rendered.append(shot['id'])
                clips.append(clip)
                markers.append({'shot_id':shot['id'],'start':cursor,'end':cursor+actual,'planned_start':shot['start_seconds']})
                if f.caption: subtitles.append((cursor,cursor+actual,f.caption))
                cursor+=actual
            listing=tmp/'clips.txt';listing.write_text(''.join(f"file '{c.as_posix().replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n" for c in clips))
            pending=tmp/'animatic.mp4'
            args=['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing)]
            if p.sound_cues:
                wav=tmp/'mix.wav';sound_mix([c.model_dump() for c in p.sound_cues],cursor,wav)
                args+=['-i',str(wav),'-map','0:v','-map','1:a','-c:a','aac']
            run(args+['-c:v','copy','-t',str(cursor),'-movflags','+faststart',str(pending)])
            # Sidecar remains an accessibility track; titles are never used to remove it.
            def stamp(t):
                ms=round(t*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
            srt=output.with_suffix('.srt');srt.write_text(''.join(f'{i}\n{stamp(a)} --> {stamp(b)}\n{text}\n\n' for i,(a,b,text) in enumerate(subtitles,1)))
            pending.replace(output)
        report={'output_path':str(output),'captions_path':str(srt),'markers':markers,'rendered_shots':rendered,'reused_shots':reused,'duration':cursor,'plan_review':review,'purpose':'rough timing review; not final art approval'}
        report_path=output.with_suffix('.animatic.json');report_path.write_text(json.dumps(report,indent=2))
        return ToolResult(success=True,data=report,artifacts=[str(output),str(srt),str(report_path)])
