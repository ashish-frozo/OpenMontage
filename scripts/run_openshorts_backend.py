#!/usr/bin/env python3
"""Launch the isolated self-hosted OpenShorts API on loopback only."""
import os
from pathlib import Path
import sys
import subprocess
root = Path(os.environ.get('OPENSHORTS_HOME', Path.home() / 'WORK/openshorts')).resolve()
if not (root / 'app.py').is_file():
    raise SystemExit('OPENSHORTS_HOME must contain the OpenShorts checkout')
key_file = os.environ.get('OPENSHORTS_LLM_KEY_FILE')
if key_file:
    os.environ['LLM_API_KEY'] = Path(key_file).expanduser().read_text().strip()
os.environ.setdefault('MAX_CONCURRENT_JOBS', '1')
os.environ.setdefault('WHISPER_DEVICE', 'cpu')
os.environ.setdefault('WHISPER_COMPUTE', 'int8')
os.environ.setdefault('OUTPUT_MAX_GB', '3')
os.environ.setdefault('UPLOADS_MAX_GB', '3')
ffmpeg_dir = Path(os.environ.get('OPENSHORTS_FFMPEG_DIR', '/opt/homebrew/opt/ffmpeg-full/bin'))
if ffmpeg_dir.is_dir():
    os.environ['PATH'] = str(ffmpeg_dir) + os.pathsep + os.environ.get('PATH', '')
probe = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True, timeout=10, check=True)
if not any(' ass ' in line for line in probe.stdout.splitlines()):
    raise SystemExit('OpenShorts requires FFmpeg with the ass subtitle filter; install ffmpeg-full or set OPENSHORTS_FFMPEG_DIR')
os.chdir(root)
os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '8017'])
