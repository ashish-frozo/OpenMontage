"""Pinned make-an-anime Ruby runtime bridge; creative direction stays with the caller."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from lib.paths import PROJECTS_DIR, REPO_ROOT
from tools.base_tool import ToolResult

UPSTREAM = 'https://github.com/makevoid/claude-make-an-anime'
REVISION = 'adc1a76eb4e77df47f42160c2c166350a76ad849'
SETUP = 'Run scripts/setup_anime_toolkit.py on the MCP host. Requires Ruby 3.2+, Bundler, FFmpeg, ImageMagick, Python, Node and Chrome; Swift VFX is optional. Paid tasks require centrally configured FAL_AI_API_KEY or FAL_KEY.'
LOCAL_TASKS = (
    'doctor', 'pipeline:status', 'gen:mix', 'gen:overlay', 'anim:prepare',
    'anim:preview', 'anim:overlay', 'anim:render', 'review:camera',
    'review:believable', 'review:likeness', 'dialogue:timeline',
    'scene:new', 'episode:preview', 'audio:analyze', 'audio:seams',
    'media:probe', 'media:sheet', 'media:frames', 'media:frame', 'media:cut',
    'media:cutout', 'media:keep_component', 'media:sprite_box', 'media:split_row',
    'media:track', 'media:audio_cut', 'media:style', 'media:concat', 'media:mux',
    'assets:cut', 'assets:faces', 'sfx:mix', 'vfx:build', 'vfx:analyze',
    'vfx:stills', 'vfx:clip', 'vfx:render', 'vfx:bake',
)
PAID_TASKS = ('gen:ref_base', 'gen:ref_torn', 'gen:keyframes', 'gen:shots',
              'gen:clips', 'gen:video', 'gen:dialogue', 'gen:music')
ITEM_TASKS = {'gen:keyframes', 'gen:shots', 'gen:clips', 'gen:dialogue'}


def runtime():
    return Path(os.environ.get('ANIME_TOOLKIT_HOME', str(REPO_ROOT/'.runtime/anime-toolkit'))).expanduser().resolve()/'skills/make-an-anime/scripts'


def bundle_path():
    checkout=runtime().parents[2]
    return checkout.with_name(checkout.name+'-bundle')


def ruby():
    candidates = [os.environ.get('ANIME_RUBY'), '/opt/homebrew/opt/ruby/bin/ruby',
                  '/usr/local/opt/ruby/bin/ruby', shutil.which('ruby')]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            result = subprocess.run([candidate, '-e', 'puts RUBY_VERSION'], capture_output=True, text=True, timeout=5)
            match = re.match(r'(\d+)\.(\d+)', result.stdout.strip())
            if result.returncode == 0 and match and tuple(map(int, match.groups())) >= (3, 2):
                return candidate
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def project(project_id):
    root = (PROJECTS_DIR/project_id).resolve()
    if root.parent != PROJECTS_DIR.resolve() or not (root/'project.json').is_file():
        raise ValueError('Create an OpenMontage project first')
    work = (root/'assets/anime').resolve()
    if not work.is_relative_to(root/'assets'):
        raise ValueError('Anime workspace must stay inside project assets/')
    return root, work


def relative(work, value):
    if Path(value).is_absolute():
        raise ValueError('Use workspace-relative paths')
    out = (work/value).resolve()
    if not out.is_relative_to(work) or out == work:
        raise ValueError('Path escapes the anime workspace')
    return out


def environment(paid=False, **options):
    env = dict(os.environ)
    for key in ('RUN','ONLY','FORCE','NEW_REQUEST','RECUT','SEED','VIDEO_MODEL','VIDEO_RES','SFX','VFX','NOTE','STRICT',
                'FAL_KEY','FAL_AI_API_KEY','FAL_AI_API_KEY_PLUGIN','BUNDLE_GEMFILE','BUNDLE_PATH','RUBYOPT'):
        env.pop(key, None)
    if paid:
        env['FAL_AI_API_KEY'] = os.environ.get('FAL_AI_API_KEY') or os.environ.get('FAL_KEY', '')
    env.update({k:str(v) for k,v in options.items() if v is not None})
    exe = ruby()
    if exe:
        env['PATH'] = str(Path(exe).parent)+os.pathsep+env.get('PATH','')
    env['MV_PYTHON'] = sys.executable
    env['BUNDLE_PATH'] = str(bundle_path())
    env['LANG'] = 'en_US.UTF-8'
    return env


def redact(text):
    for key in ('FAL_KEY','FAL_AI_API_KEY','FAL_AI_API_KEY_PLUGIN'):
        secret = os.environ.get(key)
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return text


def invoke(work, task, args=(), timeout=900, paid=False, **options):
    exe = ruby()
    if not exe or not (runtime()/'mv.rb').is_file():
        raise ValueError(SETUP)
    # Rake has its own comma/bracket argument grammar. No arbitrary tasks,
    # command strings or environment dictionaries are accepted from callers.
    for arg in args:
        if not arg or any(c in arg for c in '[],\x00\r\n'):
            raise ValueError('Invalid task argument')
        if not re.fullmatch(r'-?\d+(?:\.\d+)?', arg):
            relative(work, arg)
    command = task + ('['+','.join(args)+']' if args else '')
    try:
        # Activate the locked bundle before mv.rb requires Ruby's default JSON
        # gem; otherwise Ruby 3.4 can load an incompatible default version.
        proc = subprocess.run([exe,'-S','bundle','exec',exe,'-EUTF-8',str(runtime()/'mv.rb'),'--project',str(work),command],
                              cwd=work,env=environment(paid,**options),capture_output=True,
                              text=True,encoding='utf-8',errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, cost_usd=None if paid else 0,
                          error='Anime task timed out. Inspect saved manifests and Fal receipts before retrying; provider work may continue.')
    output = redact(proc.stdout[-16000:]+'\n'+proc.stderr[-4000:])
    media=[]
    for path in sorted((work/'output').rglob('*')):
        if path.is_file() and path.resolve().is_relative_to(work) and path.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.wav','.mp3','.mp4','.srt','.vtt'}:
            media.append(str(path))
            if len(media)>=200: break
    return ToolResult(success=proc.returncode==0, cost_usd=None if paid else 0,
                      error=None if proc.returncode==0 else output[-3000:],
                      data={'task':task,'output':output,'workspace':str(work),'media':media,
                            'cost_note':'Provider billing is not reported by upstream; reconcile Fal receipts. The estimate is a reservation, not a provider spending cap.' if paid else 'Local task; no generation API key forwarded.',
                            'review_required':True},artifacts=media)


def require_production_approval(root):
    from lib.checkpoint import read_checkpoint
    from lib.pipeline_loader import load_pipeline
    marker=json.loads((root/'project.json').read_text(encoding='utf-8'))
    manifest=load_pipeline(marker['pipeline_type'])
    if 'assets' not in [s['name'] for s in manifest['stages']]:
        raise ValueError('Choose a production pipeline with an assets stage')
    for stage in manifest['stages']:
        if stage['name']=='assets': break
        check=read_checkpoint(root.parent,root.name,stage['name'])
        if not check or check['status']!='completed' or (stage.get('human_approval_default') and not check.get('human_approved')):
            raise ValueError(f'Complete and approve predecessor {stage["name"]} before anime generation')


def initialize(project_id, story):
    root,work=project(project_id)
    if work.exists():
        raise ValueError('Anime workspace already exists; inspect or revise it instead of reinitializing')
    exe=ruby()
    if not exe or not (runtime()/'mv.rb').is_file(): raise ValueError(SETUP)
    brief=root/'artifacts/anime-story.md'
    brief.parent.mkdir(parents=True,exist_ok=True)
    with brief.open('x',encoding='utf-8') as f: f.write(story)
    proc=subprocess.run([exe,'-EUTF-8',str(runtime()/'mv.rb'),'init','--project',str(work),'--story',str(brief)],
                        env=environment(),capture_output=True,text=True,encoding='utf-8',timeout=60)
    if proc.returncode: raise ValueError(redact(proc.stderr[-2000:]))
    # ESM resolves dependencies relative to the copied toolkit. Only this
    # dependency directory points at the centrally installed trusted runtime.
    if (runtime()/'node_modules').is_dir():
        (work/'node_modules').symlink_to(runtime()/'node_modules',target_is_directory=True)
    return ToolResult(success=True,data={'workspace':str(work),'upstream_revision':REVISION,
        'next':'Write config/style.md, config/cast.yml, config/generations.rb, docs/PLAN.md and prompts/<run>/. Read anime-production instructions; preserve canonical script/scene_plan and approvals.'},artifacts=[str(brief)])
