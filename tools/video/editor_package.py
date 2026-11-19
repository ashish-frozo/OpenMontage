"""Package portable source media, OTIO tracks, captions, markers and effect warnings."""
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Literal
from pydantic import Field
from lib.creator import Strict
from lib.creator_media import media_file, probe
from tools.base_tool import BaseTool, ToolResult

class EditorClip(Strict):
    id: str
    path: str
    start: float = Field(default=0,ge=0)
    duration: float = Field(gt=0)
    timeline_start: float = Field(default=0,ge=0)
    track: str = 'Picture'
    kind: Literal['Video','Audio'] = 'Video'
    effects: list[str] = Field(default_factory=list)

class EditorMarker(Strict):
    name: str
    start: float = Field(ge=0)
    duration: float = Field(default=0,ge=0)
    note: str = ''

class PackageInput(Strict):
    clips: list[EditorClip] = Field(min_length=1,max_length=1000)
    markers: list[EditorMarker] = Field(default_factory=list,max_length=1000)
    captions_path: str | None = None
    output_path: str
    fps: float = Field(default=24,gt=0,le=120)

class EditorPackage(BaseTool):
    name='editor_package'
    capability='video_post'
    dependencies=['python:opentimelineio','cmd:ffprobe']
    input_schema=PackageInput.model_json_schema()
    best_for=['portable editor handoff','separate audio stems','relink manifests']
    agent_skills=['creator-workflow']
    def execute(self, inputs):
        import opentimelineio as otio
        p=PackageInput.model_validate(inputs);out=Path(p.output_path).resolve()
        if out.exists(): raise ValueError('Choose a new package directory; existing handoffs are immutable')
        out.parent.mkdir(parents=True,exist_ok=True)
        ids=[c.id for c in p.clips]
        if len(set(ids))!=len(ids): raise ValueError('Clip ids must be unique')
        manifest=[];unsupported=[];tracks={}
        rt=lambda t:otio.opentime.RationalTime(t*p.fps,p.fps)
        tr=lambda a,b:otio.opentime.TimeRange(rt(a),rt(b))
        with tempfile.TemporaryDirectory(dir=out.parent) as temp:
            root=Path(temp)/'package';root.mkdir();(root/'media').mkdir()
            timeline=otio.schema.Timeline(name='OpenMontage handoff')
            for clip in p.clips:
                source=media_file(clip.path);digest=hashlib.sha256(source.read_bytes()).hexdigest()
                relative='media/'+digest[:20]+source.suffix.lower();destination=root/relative
                if not destination.exists(): shutil.copy2(source,destination)
                if source.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:
                    info=probe(source)
                    if clip.start+clip.duration>float(info['format']['duration'])+.05: raise ValueError(f'{clip.id}: source range exceeds media duration')
                manifest.append({'clip_id':clip.id,'original_path':str(source),'relative_path':relative,'sha256':digest,'track':clip.track,'kind':clip.kind})
                tracks.setdefault((clip.track,clip.kind),[]).append((clip,relative))
                unsupported.extend({'clip_id':clip.id,'effect':e,'action':'Recreate in editor or replace with a baked clip'} for e in clip.effects)
            for (name,kind),clips in tracks.items():
                track=otio.schema.Track(name=name,kind=kind);cursor=0
                for clip,relative in sorted(clips,key=lambda item:item[0].timeline_start):
                    if clip.timeline_start<cursor-1e-6: raise ValueError('Overlapping clips need separate tracks')
                    if clip.timeline_start>cursor: track.append(otio.schema.Gap(source_range=tr(0,clip.timeline_start-cursor)))
                    track.append(otio.schema.Clip(name=clip.id,media_reference=otio.schema.ExternalReference(target_url=relative),source_range=tr(clip.start,clip.duration)))
                    cursor=clip.timeline_start+clip.duration
                timeline.tracks.append(track)
            for marker in p.markers:
                timeline.tracks.markers.append(otio.schema.Marker(name=marker.name,marked_range=tr(marker.start,marker.duration),metadata={'note':marker.note}))
            otio.adapters.write_to_file(timeline,str(root/'timeline.otio'),adapter_name='otio_json')
            if p.captions_path: shutil.copy2(media_file(p.captions_path),root/'captions.srt')
            report={'media':manifest,'markers':[m.model_dump() for m in p.markers],'unsupported_effects':unsupported,'effects_preserved':False,
                    'audio_tracks':[name for name,kind in tracks if kind=='Audio'],'relink_base':'.','note':'Native OTIO with relative media URLs. NLE adapter support varies; effects must be recreated or baked.'}
            (root/'manifest.json').write_text(json.dumps(report,indent=2))
            (root/'README.txt').write_text('Open timeline.otio with an OTIO-capable editor/importer. Resolve media paths relative to this directory. Audio clips are on separate tracks. Read manifest.json for unsupported effects. Captions, when supplied, are captions.srt.\n')
            root.replace(out)
        return ToolResult(success=True,data={'output_path':str(out),'unsupported_effects':unsupported,'media_count':len(manifest)},artifacts=[str(out)])
