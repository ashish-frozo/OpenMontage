"""Lightweight bridge to isolated local speech runtimes; no torch in the MCP host."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from lib.paths import REPO_ROOT
from tools.base_tool import ToolResult, ToolStatus


def runtime(engine):
    return Path(os.environ.get(engine.upper()+'_PYTHON',str(REPO_ROOT/f'.venv-{engine}'/'bin/python')))


def model_dir(engine,variant='english'):
    root=Path(os.environ.get(engine.upper()+'_MODEL_DIR',str(REPO_ROOT/'.runtime/tts'/engine)))
    return root/variant if engine=='chatterbox' else root


def health(engine,variant='english'):
    python=runtime(engine);root=model_dir(engine,variant)
    if not python.is_file(): return {'status':'unavailable','reason':'Isolated Python environment missing'}
    marker=root/'ready.json'
    try:
        ready=json.loads(marker.read_text())
        if ready['engine']!=engine or not ready.get('files') or not ready.get('verified_generation'): raise ValueError('Invalid readiness record')
        if any(not (root/name).is_file() or (root/name).stat().st_size!=size for name,size in ready['files'].items()): raise ValueError('Model files missing or changed')
        return {'status':'available','model_revision':ready.get('revision'),'verified_generation':ready.get('verified_generation',False)}
    except (OSError,ValueError,KeyError): return {'status':'unavailable','reason':'Run scripts/setup_local_tts.py to install and verify model files'}


def synthesize(engine,inputs):
    import jsonschema
    variant=inputs.get('variant','english')
    status=health(engine,variant)
    if status['status']!='available': return ToolResult(success=False,error=status['reason'])
    output=Path(inputs['output_path']).expanduser().resolve()
    if output.suffix.lower()!='.wav': return ToolResult(success=False,error='Use a .wav output_path; convert formats after synthesis')
    if not inputs['text'].strip(): return ToolResult(success=False,error='text must contain speech')
    output.parent.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    try:
        with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
            tmp=Path(tmp);request={**inputs,'output_path':str(tmp/'speech.wav'),'model_dir':str(model_dir(engine,variant)),'engine':engine}
            req=tmp/'request.json';report=tmp/'report.json';req.write_text(json.dumps(request))
            env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PYTORCH_ENABLE_MPS_FALLBACK':'1','TOKENIZERS_PARALLELISM':'false'}
            result=subprocess.run([str(runtime(engine)),str(REPO_ROOT/'scripts/local_tts_worker.py'),str(req),str(report)],capture_output=True,text=True,timeout=900,env=env)
            if result.returncode: return ToolResult(success=False,error=(result.stderr or result.stdout)[-3500:])
            data=json.loads(report.read_text());(tmp/'speech.wav').replace(output)
            data.update(output=str(output),output_path=str(output),provider=engine,model_revision=status.get('model_revision'))
            return ToolResult(success=True,data=data,artifacts=[str(output)],cost_usd=0,duration_seconds=time.monotonic()-started,model=data['model'])
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        return ToolResult(success=False,error=f'{engine} synthesis failed: {exc}')
