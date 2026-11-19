"""Create a real footage/image transition with normalized size, timing and frame rate."""
import tempfile
from pathlib import Path
from typing import Literal
from pydantic import Field
from lib.creator import Strict
from lib.creator_media import run, media_file, probe
from tools.base_tool import BaseTool, ToolResult

class TransitionInput(Strict):
    from_path: str
    to_path: str
    from_duration: float = Field(default=2,gt=0,le=60)
    to_duration: float = Field(default=2,gt=0,le=60)
    transition_duration: float = Field(default=.5,gt=0,le=5)
    effect: Literal['fade','wipeleft','wiperight','slideleft','slideright','circleopen','dissolve'] = 'fade'
    width: int = Field(default=1280,ge=64,le=1920,multiple_of=2)
    height: int = Field(default=720,ge=64,le=1920,multiple_of=2)
    fps: int = Field(default=24,ge=1,le=60)
    output_path: str

class MediaTransition(BaseTool):
    name='media_transition'
    capability='video_post'
    dependencies=['cmd:ffmpeg','cmd:ffprobe']
    input_schema=TransitionInput.model_json_schema()
    best_for=['transitions between footage or images']
    agent_skills=['creator-workflow']
    def execute(self, inputs):
        p=TransitionInput.model_validate(inputs)
        if p.transition_duration>=min(p.from_duration,p.to_duration): raise ValueError('Transition duration must be shorter than both sources')
        out=Path(p.output_path).resolve()
        if out.suffix!='.mp4': raise ValueError('Transition output must be .mp4')
        out.parent.mkdir(parents=True,exist_ok=True)
        args=['ffmpeg','-v','error','-y'];filters=[]
        for i,(value,duration) in enumerate(((p.from_path,p.from_duration),(p.to_path,p.to_duration))):
            path=media_file(value)
            if path.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}: args+=['-loop','1','-t',str(duration),'-i',str(path)]
            else:
                if float(probe(path)['format']['duration'])+.01<duration: raise ValueError('Video source is shorter than requested duration')
                args+=['-i',str(path)]
            filters.append(f'[{i}:v]scale={p.width}:{p.height}:force_original_aspect_ratio=decrease,pad={p.width}:{p.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={p.fps},format=yuv420p,trim=duration={duration},settb=AVTB,setpts=PTS-STARTPTS[v{i}]')
        filters.append(f'[v0][v1]xfade=transition={p.effect}:duration={p.transition_duration}:offset={p.from_duration-p.transition_duration}[out]')
        with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
            pending=Path(tmp)/'transition.mp4'
            run(args+['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map','[out]','-an','-c:v','libx264','-pix_fmt','yuv420p','-t',str(p.from_duration+p.to_duration-p.transition_duration),str(pending)])
            pending.replace(out)
        return ToolResult(success=True,data={'output_path':str(out),'duration':p.from_duration+p.to_duration-p.transition_duration,'audio_preserved':False,'note':'Compose audio with sound_design; picture overlap shortens total duration.'},artifacts=[str(out)])
