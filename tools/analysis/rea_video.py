"""Local rea-video shot analysis, layered VIDEO.md evidence and agent visual review."""
from __future__ import annotations
import json,os,shutil,subprocess
from pathlib import Path
from typing import Literal
from pydantic import Field
from content_factory.models import Model
from lib.paths import REPO_ROOT,PROJECTS_DIR
from tools.base_tool import BaseTool,ToolResult,ToolRuntime,ToolStatus,ResourceProfile

class AnalyzeInput(Model):
    project_id: str=Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$')
    video_path: str=Field(description='Existing video relative to this project, under assets/ or renders/. Download remote sources first.')
    analysis_dir: str=Field(description='New output directory under this project assets/, e.g. assets/rea-breakdown-v1. Existing outputs are never overwritten.')
    language: Literal['en','zh']='en'
    packaging: bool=False
    timeout_seconds: int=Field(default=900,ge=10,le=1800)

class ReviewInput(Model):
    project_id: str=Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$')
    analysis_dir: str
    action: Literal['summary','prepare_review','apply_review','validate']='summary'
    answers_path: str|None=Field(default=None,description='Project-relative JSON answers written by the calling AI after actual visual review.')
    reviewer: str=Field(default='calling-agent',min_length=1,max_length=100)
    language: Literal['en','zh']='en'
    timeout_seconds: int=Field(default=300,ge=10,le=900)

def scoped(project_id,value,folder=False):
    root=(PROJECTS_DIR/project_id).resolve()
    if root.parent!=PROJECTS_DIR.resolve() or not (root/'project.json').is_file():raise ValueError('Unknown project')
    p=(root/value).resolve()
    if not p.is_relative_to(root) or p==root:raise ValueError('Path must remain in the project')
    if folder and not p.is_relative_to((root/'assets').resolve()):raise ValueError('Analysis outputs must be under project assets/')
    return root,p

class _ReaBase(BaseTool):
    runtime=ToolRuntime.LOCAL
    provider='rea_video'
    agent_skills=['rea-video']
    resource_profile=ResourceProfile(cpu_cores=2,ram_mb=2048,disk_mb=2048)
    best_for=['reference video analysis','shot evidence','style breakdown','VIDEO.md','remake planning evidence']
    not_good_for=['definitive AI detection','automatic video generation','unreviewed provenance claims']
    install_instructions='Install the pinned rea-video checkout into .venv-rea-video; FFmpeg and FFprobe are required. See docs/content-factory/rea-video.md.'
    @property
    def python(self):return Path(os.environ.get('REA_VIDEO_PYTHON',str(REPO_ROOT/'.venv-rea-video/bin/python'))).expanduser().absolute()
    def estimate_cost(self,inputs):return 0.0
    def get_status(self):
        if not self.python.is_file() or not shutil.which('ffmpeg') or not shutil.which('ffprobe'):return ToolStatus.UNAVAILABLE
        try:
            for binary in ('ffmpeg','ffprobe'):
                probe=subprocess.run([binary,'-version'],capture_output=True,timeout=5)
                if probe.returncode:return ToolStatus.UNAVAILABLE
            x=subprocess.run([str(self.python),'-m','rea_video','--help'],capture_output=True,timeout=10)
            return ToolStatus.AVAILABLE if x.returncode==0 else ToolStatus.UNAVAILABLE
        except (OSError,subprocess.SubprocessError):return ToolStatus.UNAVAILABLE
    def run(self,cmd,root,timeout):
        env=os.environ.copy();env['REA_VIDEO_HOME']=str(root/'artifacts/rea-video-settings')
        # Analysis/review commands below explicitly disable VLM, ASR, OCR and model downloads.
        return subprocess.run([str(self.python),'-m','rea_video',*cmd],cwd=root,env=env,capture_output=True,text=True,timeout=timeout,check=False)
    def result(self,completed,out):
        if completed.returncode:return ToolResult(success=False,error=f'rea-video exited {completed.returncode}; inspect the saved analysis log.',data={'analysis_dir':str(out)})
        files=[p for p in sorted(out.rglob('*')) if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(out.resolve())]
        index=[{'path':str(p),'bytes':p.stat().st_size} for p in files[:40]]
        card=out/'VIDEO.md';text=card.read_text(encoding='utf-8')[:12000] if card.is_file() and card.resolve().is_relative_to(out.resolve()) else ''
        return ToolResult(success=True,data={'analysis_dir':str(out),'VIDEO_md':text,'files':index,'total_files':len(files),'files_truncated':len(files)>40,'summary':completed.stdout[-6000:],'review_required':True,'limitations':'Offline measurements and classifications are hypotheses. Calling AI must inspect frames, record evidence and apply review. No paid VLM calls were made.'},artifacts=[str(p) for p in files if p.name in ('VIDEO.md','storyboard.jpg','report.html','review_tasks.json')],cost_usd=0)

class ReaVideoAnalyze(_ReaBase):
    """Extract local shot evidence, storyboards, VIDEO.md and reports; no paid model inference."""
    name='rea_video_analyze'
    capability='video_analysis'
    input_schema=AnalyzeInput.model_json_schema()
    def execute(self,inputs):
        p=AnalyzeInput.model_validate(inputs);root,video=scoped(p.project_id,p.video_path);_,out=scoped(p.project_id,p.analysis_dir,True)
        if not video.is_file() or video.suffix.lower() not in ('.mp4','.mov','.mkv','.webm','.m4v'):raise ValueError('Use an existing local video')
        if not any(video.is_relative_to(root/d) for d in ('assets','renders')):raise ValueError('Source must be in project assets/ or renders/')
        if out.exists():raise ValueError('Analysis directory already exists; inspect it or choose a new version')
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(video)],capture_output=True,text=True,timeout=15,check=True)
        duration=float(json.loads(probe.stdout)['format']['duration'])
        if not 0<duration<=600:raise ValueError('Use a source of at most 10 minutes; trim a reference segment first')
        out.mkdir(parents=True)
        cmd=['decompose',str(video),'-o',str(out),'--lang',p.language,'--workers','2','--no-vlm','--no-whole','--no-ocr','--no-asr','--no-speakers','--no-stems']
        if not p.packaging:cmd.append('--no-packaging')
        try:x=self.run(cmd,root,p.timeout_seconds)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False,error='Analysis timed out; partial evidence is retained. Use a shorter source or a new output directory.',data={'analysis_dir':str(out)})
        (out/'analysis.log').write_text(x.stdout+'\n'+x.stderr,encoding='utf-8')
        return self.result(x,out)

class ReaVideoReview(_ReaBase):
    """Read summaries, prepare visual-review tasks, merge caller answers or validate a VIDEO.md package."""
    name='rea_video_review'
    capability='video_analysis'
    input_schema=ReviewInput.model_json_schema()
    def execute(self,inputs):
        p=ReviewInput.model_validate(inputs);root,out=scoped(p.project_id,p.analysis_dir,True)
        if not (out/'breakdown.json').is_file() or not (out/'breakdown.json').resolve().is_relative_to(out):raise ValueError('Run rea_video_analyze first; breakdown must remain in the analysis folder')
        cmd={'summary':['summary',str(out/'breakdown.json')],'prepare_review':['review',str(out)],'validate':['videomd',str(out),'--check']}.get(p.action)
        if p.action=='apply_review':
            if not p.answers_path:raise ValueError('Provide a reviewed answers_path; no automatic visual verdicts are fabricated')
            _,answers=scoped(p.project_id,p.answers_path)
            if not answers.is_file() or answers.suffix!='.json' or answers.stat().st_size>2_000_000:raise ValueError('Use an existing project JSON answers file of at most 2 MB')
            json.loads(answers.read_text());cmd=['apply-review',str(out),str(answers),'--by',p.reviewer,'--lang',p.language]
        x=self.run(cmd,root,p.timeout_seconds)
        (out/('review-'+p.action+'.log')).write_text(x.stdout+'\n'+x.stderr,encoding='utf-8')
        return self.result(x,out)
