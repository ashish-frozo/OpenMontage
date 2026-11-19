#!/usr/bin/env python3
"""Explicitly download a transcription model; normal production uses cached files only."""
import argparse
from faster_whisper import WhisperModel
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--model',choices=['tiny','base','small','medium','large-v2','large-v3'],default='base')
a=p.parse_args()
WhisperModel(a.model,device='cpu',compute_type='int8',local_files_only=False)
print(f'Transcription model cached: {a.model}; production can run offline.')
