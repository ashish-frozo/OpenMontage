#!/usr/bin/env python3
"""Runs only inside the selected engine's isolated environment."""
import json
import os
from pathlib import Path
import sys


def generate(p):
    import numpy as np
    import soundfile as sf
    import torch
    torch.set_num_threads(min(4,os.cpu_count() or 1))
    device=p.get('device','auto')
    if device=='auto': device='cuda' if torch.cuda.is_available() else 'cpu'
    if device=='mps' and not torch.backends.mps.is_available(): raise ValueError('MPS is not available; choose cpu')
    if device=='cuda' and not torch.cuda.is_available(): raise ValueError('CUDA is not available; choose cpu')
    root=Path(p['model_dir']);seed=p.get('seed',1);torch.manual_seed(seed);np.random.seed(seed)
    if p['engine']=='kokoro':
        from kokoro import KModel,KPipeline
        model=KModel(config=str(root/'config.json'),model=str(root/'kokoro-v1_0.pth')).to(device).eval()
        pipeline=KPipeline(lang_code=p['language_code'],repo_id='hexgrad/Kokoro-82M',model=model,device=device)
        voice_path=root/'voices'/(p['voice']+'.pt')
        voice=torch.load(voice_path,map_location='cpu',weights_only=True)
        chunks=[a.detach().cpu().numpy() if hasattr(a,'detach') else np.asarray(a) for _,_,a in pipeline(p['text'],voice=voice,speed=p.get('speed',1))]
        if not chunks: raise ValueError('No speech returned')
        audio=np.concatenate(chunks);sr=24000;model_name='Kokoro-82M'
    else:
        if p.get('variant','english')=='multilingual':
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            model=ChatterboxMultilingualTTS.from_local(root,device=device)
        else:
            from chatterbox.tts import ChatterboxTTS
            model=ChatterboxTTS.from_local(root,device=device)
        kwargs={'exaggeration':p.get('exaggeration',.5),'cfg_weight':p.get('cfg_weight',.5),'temperature':p.get('temperature',.8)}
        if p.get('reference_audio_path'): kwargs['audio_prompt_path']=p['reference_audio_path']
        if p.get('variant','english')=='multilingual': kwargs['language_id']=p.get('language_code','en')
        audio=model.generate(p['text'],**kwargs).detach().cpu().numpy().reshape(-1);sr=model.sr;model_name='Chatterbox-'+p.get('variant','english')
    if not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio))<1e-6: raise ValueError('Model returned empty, non-finite or silent audio')
    source_peak=float(np.max(np.abs(audio)))
    gain=min(1.0,0.98/source_peak)
    audio=audio*gain
    sf.write(p['output_path'],audio,sr,subtype='PCM_16')
    return {'model':model_name,'sample_rate':sr,'duration_seconds':round(len(audio)/sr,3),'device':device,'seed':seed,'peak':float(np.max(np.abs(audio))),'source_peak':source_peak,'peak_protection_gain':gain}

if __name__=='__main__':
    request=json.loads(Path(sys.argv[1]).read_text());result=generate(request);Path(sys.argv[2]).write_text(json.dumps(result))
