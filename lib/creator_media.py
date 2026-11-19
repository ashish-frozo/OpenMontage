"""Shared local media primitives for creator tools; all subprocesses are bounded."""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path
from lib.creator import SoundCue


def run(args, timeout=600):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)


def probe(path):
    return json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],30).stdout)


def media_file(value):
    p=Path(value).expanduser().resolve(strict=True)
    if not p.is_file(): raise ValueError(f'Not a media file: {p.name}')
    return p


def sound_mix(cues, duration, output, duck=True, target_lufs=-16):
    cues=[SoundCue.model_validate(c) for c in cues]
    ids=[c.id for c in cues]
    if len(set(ids))!=len(ids): raise ValueError('Sound cue ids must be unique')
    args=['ffmpeg','-v','error','-y','-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
    active=[]
    for cue in cues:
        if cue.start+cue.duration>duration+1e-6: raise ValueError(f'{cue.id}: cue exceeds timeline')
        if cue.fade_in+cue.fade_out>cue.duration: raise ValueError(f'{cue.id}: fades exceed cue duration')
        if cue.role=='silence': continue
        if not cue.path: raise ValueError(f'{cue.id}: non-silence cue requires path')
        p=media_file(cue.path); info=probe(p)
        if not any(s['codec_type']=='audio' for s in info['streams']): raise ValueError(f'{cue.id}: no audio stream')
        if cue.source_start+cue.duration>float(info['format']['duration'])+0.05: raise ValueError(f'{cue.id}: source too short')
        args+=['-i',str(p)];active.append(cue)
    filters=[f'[0:a]atrim=duration={duration},asetpts=PTS-STARTPTS[base]']
    speech=[];bed=[]
    for i,c in enumerate(active,1):
        filters.append(f'[{i}:a]atrim=start={c.source_start}:duration={c.duration},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume={c.gain},afade=t=in:d={c.fade_in},afade=t=out:st={c.duration-c.fade_out}:d={c.fade_out},adelay={round(c.start*1000)}:all=1[a{i}]')
        (speech if c.role=='narration' else bed).append(f'[a{i}]')
    def mix(labels,name):
        filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0:duration=longest[{name}]')
    if duck and speech and bed:
        mix(speech,'speech');mix(bed,'bed')
        filters+=['[speech]asplit=2[voice][side]','[bed][side]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=300[ducked]']
        mix(['[base]','[voice]','[ducked]'],'mixed')
    else: mix(['[base]']+speech+bed,'mixed')
    silence=''.join(f",volume=0:enable='between(t,{c.start},{c.start+c.duration})'" for c in cues if c.role=='silence')
    filters.append(f'[mixed]atrim=duration={duration}{silence},loudnorm=I={target_lufs}:TP=-1.5:LRA=11,aresample=48000[out]')
    run(args+['-filter_complex',';'.join(filters),'-map','[out]','-t',str(duration),'-c:a','pcm_s16le',str(output)])
    return {'cue_count':len(cues),'ducking':bool(duck and speech and bed),'target_lufs':target_lufs,'intentional_silence':[c.model_dump() for c in cues if c.role=='silence']}


def loudness(path):
    result=run(['ffmpeg','-hide_banner','-i',str(path),'-vn','-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'])
    blocks=re.findall(r'\{\s*"input_i".*?\}',result.stderr,re.S)
    return json.loads(blocks[-1]) if blocks else {'available':False}
