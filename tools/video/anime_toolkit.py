"""Anime project setup, bounded local tasks and separately approved Fal generation."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal
from pydantic import Field

from content_factory.models import Model
from lib import anime_toolkit as bridge
from lib.research import now
from tools.base_tool import BaseTool, ToolResult, ToolRuntime, ToolStatus, ResourceProfile


class ProjectInput(Model):
    project_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$')
    action: Literal['initialize','status','reference','read_file','write_file'] = 'status'
    run: str = Field(default='scene-01',pattern=r'^[A-Za-z0-9_-]{1,100}$')
    story: str | None = Field(default=None,max_length=100000)
    reference: str | None = Field(default=None,description='Reference filename from the returned reference list, such as planning.md.')
    relative_path: str | None = Field(default=None,description='Authoring path relative to assets/anime, under config/, prompts/ or docs/.')
    content: str | None = Field(default=None,max_length=1_000_000)
    expected_sha256: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$',description='Required when replacing a file: read_file returns the current hash.')


class LocalInput(Model):
    project_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$')
    task: Literal[bridge.LOCAL_TASKS]
    run: str = Field(default='scene-01',pattern=r'^[A-Za-z0-9_-]{1,100}$')
    args: list[str] = Field(default_factory=list,max_length=20,description='Separate Ruby task arguments. File paths are relative to assets/anime; no brackets or comma-packed arguments.')
    cue: str | None = Field(default=None,pattern=r'^[A-Za-z0-9_-]{1,100}$',description='SFX/VFX cue filename stem when needed.')
    force: bool = Field(default=False,description='Rebuild an existing local derived output after changing its inputs.')
    timeout_seconds: int = Field(default=900,ge=10,le=3600)


class GenerateInput(Model):
    project_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$')
    task: Literal[bridge.PAID_TASKS]
    run: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    only: str | None = Field(default=None,pattern=r'^[A-Za-z0-9_-]{1,100}$',description='Exactly one item id; required for dialogue, keyframes, shots and clips. Separate jobs for separate items.')
    video_model: Literal['minimax','seedance'] = 'minimax'
    video_resolution: Literal['480p','720p','1080p','768P','1080P'] | None = None
    force: bool = Field(default=False,description='Retake an existing selected item after an approved prompt/seed change. Identical Fal request inputs still reuse receipts.')
    plan_sha256: str = Field(pattern=r'^[a-f0-9]{64}$',description='Hash of the approved assets/anime/docs/PLAN.md; changed plans require renewed approval.')
    approval_evidence: str = Field(min_length=5,max_length=4000,description="The user's actual approval for this anime plan; never invent approval.")
    estimated_cost_usd: float = Field(gt=0,le=1000,allow_inf_nan=False,description='Current Fal estimate for this bounded task, including uploads/retries; reserved by Content Factory. Upstream cannot enforce a provider spending cap.')
    timeout_seconds: int = Field(default=1800,ge=30,le=3600)


class _Anime(BaseTool):
    provider='anime_toolkit'
    agent_skills=['anime-production']
    install_instructions=bridge.SETUP
    def get_status(self):
        return ToolStatus.AVAILABLE if bridge.ruby() and (bridge.runtime()/'mv.rb').is_file() else ToolStatus.UNAVAILABLE
    def estimate_cost(self,inputs): return 0.0


class AnimeProject(_Anime):
    """Initialize an anime workspace, author its plan/config/prompts, inspect status, or read upstream planning/camera/episode references. Does not execute authored source."""
    name='anime_project'
    capability='anime_project'
    runtime=ToolRuntime.LOCAL
    input_schema=ProjectInput.model_json_schema()
    resource_profile=ResourceProfile(cpu_cores=1,ram_mb=256,disk_mb=20)
    best_for=['story-to-anime project setup','character and location bibles','upstream anime workflow references','episode planning']
    not_good_for=['automatic creative direction','generating footage without a plan']
    side_effects=['initialize writes a new assets/anime workspace; write_file versions authored source with hash checks; read/status/reference do not generate media']
    def execute(self,inputs):
        p=ProjectInput.model_validate(inputs)
        root,work=bridge.project(p.project_id)
        if p.action in {'read_file','write_file'}:
            if not (work/'config/project.json').is_file(): raise ValueError('Initialize the anime project first')
            if not p.relative_path: raise ValueError('Provide relative_path')
            path=bridge.relative(work,p.relative_path)
            parts=path.relative_to(work).parts
            if parts[0] not in {'config','prompts','docs'} or path.suffix not in {'.rb','.js','.json','.yml','.yaml','.md','.txt'} or parts==('config','approval.json'):
                raise ValueError('Author only config, prompts or docs source files; approval receipts cannot be edited')
            current=None
            if path.is_file():
                if path.stat().st_size>1_000_000: raise ValueError('Source file exceeds 1MB')
                current=path.read_bytes()
            digest=hashlib.sha256(current).hexdigest() if current is not None else None
            if p.action=='read_file':
                if current is None: raise ValueError('Source file does not exist')
                return ToolResult(success=True,data={'relative_path':p.relative_path,'sha256':digest,'content':current.decode('utf-8')})
            if p.content is None or len(p.content.encode('utf-8'))>1_000_000: raise ValueError('Provide content, at most 1MB')
            if digest!=p.expected_sha256: raise ValueError('Source changed or already exists; read_file and pass its sha256 before replacing it')
            path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
                f.write(p.content); temporary=Path(f.name)
            temporary.replace(path)
            return ToolResult(success=True,data={'path':str(path),'relative_path':p.relative_path,'sha256':hashlib.sha256(p.content.encode('utf-8')).hexdigest(),'executed':False},artifacts=[str(path)])
        upstream=bridge.REPO_ROOT/'.agents/skills/anime-production/upstream'
        references=upstream/'references'
        sources={x.name:x for x in references.glob('*.md')}
        for folder in ['examples','assets']:
            sources.update({str(x.relative_to(upstream)):x for x in (upstream/folder).rglob('*') if x.is_file() and x.suffix in {'.md','.rb','.json','.yml','.js'}})
        names=sorted(sources)
        if p.action=='reference':
            if p.reference not in names: raise ValueError('Choose a reference from '+', '.join(names))
            return ToolResult(success=True,data={'reference':p.reference,'text':sources[p.reference].read_text(encoding='utf-8')[:60000]})
        if p.action=='initialize':
            if not p.story or not p.story.strip(): raise ValueError('Provide the story/brief')
            return bridge.initialize(p.project_id,p.story)
        manifest=bridge.relative(work,'output/'+p.run+'/manifest.json')
        plan=bridge.relative(work,'docs/PLAN.md')
        return ToolResult(success=True,data={'workspace':str(work),'initialized':(work/'config/project.json').is_file(),
            'upstream_revision':bridge.REVISION,'references':names,'local_tasks':list(bridge.LOCAL_TASKS),
            'paid_tasks':list(bridge.PAID_TASKS),'fal_configured':bool(os.getenv('FAL_AI_API_KEY') or os.getenv('FAL_KEY')),
            'plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest() if plan.is_file() else None,
            'manifest':json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() and manifest.stat().st_size<2_000_000 else {}})


class AnimeLocal(_Anime):
    """Run a local anime task: mix audio, render p5 overlays, review camera/continuity, assemble scenes or finish VFX. No generation key is forwarded."""
    name='anime_local'
    capability='anime_processing'
    runtime=ToolRuntime.LOCAL
    input_schema=LocalInput.model_json_schema()
    resource_profile=ResourceProfile(cpu_cores=2,ram_mb=2048,disk_mb=4096)
    best_for=['p5 anime titles and subtitles','paper-cut panels and sprites','camera movement evidence','dialogue timelines','episode assembly','Swift grain glow impact finishing']
    not_good_for=['paid asset generation','guaranteed lip sync','untrusted executable project config']
    side_effects=['writes or replaces derived media inside the project anime workspace']
    def get_status(self):
        if super().get_status()!=ToolStatus.AVAILABLE:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE if bridge.bundle_path().is_dir() else ToolStatus.UNAVAILABLE
    def execute(self,inputs):
        p=LocalInput.model_validate(inputs); _,work=bridge.project(p.project_id)
        if not (work/'config/project.json').is_file(): raise ValueError('Initialize with anime_project first')
        if p.task=='gen:overlay':
            manifest=bridge.relative(work,'output/'+p.run+'/manifest.json')
            data=json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() and manifest.stat().st_size<2_000_000 else {}
            if not data.get('dialogue'):
                raise ValueError('gen:overlay without dialogue would request paid Whisper. Use local anim:prepare then anim:overlay instead.')
        return bridge.invoke(work,p.task,p.args,timeout=p.timeout_seconds,RUN=p.run,SFX=p.cue,VFX=p.cue,FORCE='1' if p.force else None)


class AnimeGenerate(_Anime):
    """Execute one approved anime generation task through upstream Fal: sheets, keyframes, shots, voices or score. Submit through persistent factory jobs and inspect receipts before retrying."""
    name='anime_generate'
    capability='anime_generation'
    runtime=ToolRuntime.API
    input_schema=GenerateInput.model_json_schema()
    resource_profile=ResourceProfile(cpu_cores=2,ram_mb=2048,disk_mb=4096,network_required=True)
    best_for=['consistent anime character/location sheets','camera-directed image-to-video','dialogue-guided shots','scene voices and score','cached Fal request receipts']
    not_good_for=['free rendering','hard provider spending limits','automatic full-episode batch runs','untrusted Ruby project configuration']
    side_effects=['uploads references and audio to Fal; may incur provider charges; writes generated assets and request receipts']
    def get_status(self):
        ready=(os.getenv('FAL_AI_API_KEY') or os.getenv('FAL_KEY')) and bridge.bundle_path().is_dir()
        return super().get_status() if ready else ToolStatus.UNAVAILABLE
    def estimate_cost(self,inputs): return GenerateInput.model_validate(inputs).estimated_cost_usd
    def execute(self,inputs):
        p=GenerateInput.model_validate(inputs); root,work=bridge.project(p.project_id)
        if not (os.getenv('FAL_AI_API_KEY') or os.getenv('FAL_KEY')): raise ValueError(bridge.SETUP)
        if p.task in bridge.ITEM_TASKS and not p.only: raise ValueError('Select exactly one item with only; batch generation is not exposed')
        bridge.require_production_approval(root)
        plan=bridge.relative(work,'docs/PLAN.md')
        if not plan.is_file() or hashlib.sha256(plan.read_bytes()).hexdigest()!=p.plan_sha256:
            raise ValueError('Approved anime plan is missing or changed; review it and provide its current hash')
        approval=bridge.relative(work,'config/approval.json')
        approval.write_text(json.dumps({'plan_sha256':p.plan_sha256,'user_approval':p.approval_evidence,'recorded_at':now()}),encoding='utf-8')
        return bridge.invoke(work,p.task,timeout=p.timeout_seconds,paid=True,RUN=p.run,ONLY=p.only,
                             VIDEO_MODEL=p.video_model,VIDEO_RES=p.video_resolution,FORCE='1' if p.force else None)
