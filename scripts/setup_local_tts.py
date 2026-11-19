#!/usr/bin/env python3
"""Install model files and verify actual speech inside an isolated engine environment."""
import argparse
import json
import os
from pathlib import Path
import sys
from huggingface_hub import HfApi, snapshot_download
from local_tts_worker import generate

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('engine',choices=['kokoro','chatterbox']);parser.add_argument('--variant',choices=['english','multilingual'],default='english');parser.add_argument('--revision');args=parser.parse_args()
folder=Path(os.environ.get(args.engine.upper()+'_MODEL_DIR',str(root/'.runtime/tts'/args.engine)))
if args.engine=='chatterbox': folder/=args.variant
folder.mkdir(parents=True,exist_ok=True)
if args.engine=='kokoro': repo='hexgrad/Kokoro-82M';patterns=['config.json','kokoro-v1_0.pth','voices/*.pt','LICENSE*']
elif args.variant=='english': repo='ResembleAI/chatterbox';patterns=['ve.safetensors','t3_cfg.safetensors','s3gen.safetensors','tokenizer.json','conds.pt','LICENSE*']
else: repo='ResembleAI/chatterbox';patterns=['ve.pt','t3_mtl23ls_v2.safetensors','s3gen.pt','grapheme_mtl_merged_expanded_v1.json','conds.pt','Cangjie5_TC.json','LICENSE*']
revision=args.revision or HfApi().model_info(repo).sha
snapshot_download(repo_id=repo,revision=revision,allow_patterns=patterns,local_dir=str(folder))
# English G2P resources must be installed before runtime offline mode is enabled.
if args.engine=='kokoro':
 import spacy
 if not spacy.util.is_package('en_core_web_sm'):
  from spacy.cli import download
  download('en_core_web_sm')
output=root/'projects/local-voiceover-smoke/assets/audio'/f'{args.engine}-{args.variant}.wav';output.parent.mkdir(parents=True,exist_ok=True)
params={'engine':args.engine,'model_dir':str(folder),'text':'Welcome to Open Montage. Your story deserves a clear and expressive voice.','output_path':str(output),'device':'cpu','variant':args.variant,'language_code':'a' if args.engine=='kokoro' else 'en','voice':'af_heart'}
result=generate(params)
files={str(p.relative_to(folder)):p.stat().st_size for p in folder.rglob('*') if p.is_file() and '.cache' not in p.parts and p.name!='ready.json'}
(folder/'ready.json').write_text(json.dumps({'engine':args.engine,'variant':args.variant,'revision':revision,'repo':repo,'files':files,'verified_generation':True,'sample':str(output),'verification':result},indent=2))
print(json.dumps({'engine':args.engine,'variant':args.variant,'revision':revision,'sample':str(output),'verification':result}))
