"""Mix an explicit sound cue sheet with narration ducking and intentional silence."""
import tempfile
from pathlib import Path
from pydantic import Field
from lib.creator import Strict, SoundCue
from lib.creator_media import sound_mix, loudness
from tools.base_tool import BaseTool, ToolResult

class SoundInput(Strict):
    cues: list[SoundCue] = Field(min_length=1,max_length=200)
    duration: float = Field(gt=0,le=3600)
    output_path: str
    duck_music: bool = True
    export_stems: bool = False
    target_lufs: float = Field(default=-16,ge=-30,le=-10)

class SoundDesign(BaseTool):
    name='sound_design'
    capability='audio_mix'
    dependencies=['cmd:ffmpeg','cmd:ffprobe']
    input_schema=SoundInput.model_json_schema()
    best_for=['sound cue sheets','dialogue lead-ins','ambience and intentional silence']
    agent_skills=['creator-workflow']
    def execute(self, inputs):
        p=SoundInput.model_validate(inputs);out=Path(p.output_path).resolve()
        if out.suffix!='.wav': raise ValueError('Sound design output must be .wav')
        out.parent.mkdir(parents=True,exist_ok=True)
        stems=[]
        with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
            mix=Path(tmp)/'mix.wav'
            report=sound_mix([c.model_dump() for c in p.cues],p.duration,mix,p.duck_music,p.target_lufs)
            report['measured_loudness']=loudness(mix)
            if p.export_stems:
                import uuid
                stem_dir=out.parent/('stems-'+uuid.uuid4().hex);stem_dir.mkdir()
                for role in ('narration','music','ambience','sfx'):
                    cues=[c.model_dump() for c in p.cues if c.role in (role,'silence')]
                    if not any(c['role']==role for c in cues): continue
                    stem=stem_dir/(role+'.wav')
                    sound_mix(cues,p.duration,stem,False,p.target_lufs)
                    stems.append({'role':role,'path':str(stem),'note':'Normalized isolated role stem; sum is not identical to the ducked master.'})
            mix.replace(out)
        report['stems']=stems
        return ToolResult(success=True,data={'output_path':str(out),**report},artifacts=[str(out)]+[s['path'] for s in stems])
