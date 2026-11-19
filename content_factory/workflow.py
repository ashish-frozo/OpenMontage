"""Evidence, narration timing, review and asset memory for bounded agent workflows."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from pydantic import Field
from content_factory.models import Model
from content_factory.automation import record,records,policy_for
from lib.research import EvidencePack,validate_evidence


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def project_file(factory,project,path):
    root=factory.project(project);p=Path(path).expanduser().resolve()
    if not p.is_relative_to(root) or not p.is_file(): raise ValueError('Expected an existing file inside the project')
    return p


def save_evidence(factory,project,id,pack):
    sources={}
    with factory.db(project) as db:
        jobs=db.execute("SELECT result FROM jobs WHERE status='completed'").fetchall()
    for job in jobs:
        result=json.loads(job[0] or '{}');data=result.get('data',{})
        for source in data.get('sources',[data]):
            if source.get('trust')=='untrusted_source_content' and source.get('text'):
                if hashlib.sha256(source['text'].encode()).hexdigest()!=source.get('sha256'): continue
                sources[source['id']]=source
    verdict=validate_evidence(pack,sources)
    return record(factory,project,'evidence',id,{'pack':pack.model_dump(mode='json'),'sources':sources,'review':verdict})


class ScriptLine(Model):
    id: str=Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    text: str=Field(min_length=1,max_length=5000)
    factual: bool=True
    claim_ids: list[str]=Field(default_factory=list,max_length=20)

class ScriptAudit(Model):
    evidence_id: str
    lines: list[ScriptLine]=Field(min_length=1,max_length=200)
    words_per_minute: int=Field(default=145,ge=60,le=240)
    pronunciation: dict[str,str]=Field(default_factory=dict)


def audit_script(factory,project,p):
    evidence=records(factory,project,'evidence').get(p.evidence_id)
    if not evidence: raise ValueError('Unknown evidence pack')
    review=validate_evidence(evidence['pack'],evidence['sources']);claims={c['id']:c for c in evidence['pack']['claims']};issues=list(review['issues'])
    seen=set();words=0;lines=[]
    for line in p.lines:
        if line.id in seen: raise ValueError('Duplicate script line id')
        seen.add(line.id)
        if line.factual and not line.claim_ids: issues.append({'line':line.id,'kind':'unsupported_claim'})
        if set(line.claim_ids)-claims.keys(): issues.append({'line':line.id,'kind':'unknown_claim'})
        count=len(line.text.split());words+=count
        spoken=line.text
        for term,pronunciation in sorted(p.pronunciation.items(),key=lambda x:-len(x[0])):
            if not term: raise ValueError('Empty pronunciation term')
            spoken=re.sub(r'(?<!\w)'+re.escape(term)+r'(?!\w)',lambda _:pronunciation,spoken)
        lines.append({**line.model_dump(),'spoken_text':spoken,'estimated_seconds':count*60/p.words_per_minute})
    return {'ready':not issues,'issues':issues,'estimated_seconds':words*60/p.words_per_minute,'lines':lines,
            'note':'Claim references are checked; the agent must assess whether each spoken statement is entailed by its evidence.'}


class NarrationClip(Model):
    shot_id: str
    path: str
    gap_after: float=Field(default=0,ge=0,le=10)
    words: list[dict]=Field(default_factory=list,max_length=1000,description='Measured relative word timestamps from transcriber; never estimate them.')


def narration_timeline(factory,project,clips):
    from lib.creator_media import probe
    cursor=0;shots=[];captions=[];seen=set()
    for clip in clips:
        if clip.shot_id in seen: raise ValueError('Duplicate shot id')
        seen.add(clip.shot_id);path=project_file(factory,project,clip.path);info=probe(path)
        if not any(s['codec_type']=='audio' for s in info['streams']): raise ValueError('Narration clip has no audio')
        duration=float(info['format']['duration'])
        shots.append({'shot_id':clip.shot_id,'path':str(path),'sha256':digest(path),'start_seconds':cursor,'end_seconds':cursor+duration,'duration_seconds':duration})
        previous=0
        for word in clip.words:
            a,b=float(word['start']),float(word['end'])
            if not 0<=previous<=a<b<=duration+.05: raise ValueError('Word timestamps must be ordered and inside the measured clip')
            captions.append({'text':str(word.get('word',word.get('text',''))),'start':cursor+a,'end':cursor+b});previous=b
        cursor+=duration+clip.gap_after
    return {'shots':shots,'words':captions,'duration_seconds':cursor,'timing_source':'ffprobe measured audio','note':'Apply timings using factory_preview_revision; locked timings require explicit resolution.'}


class AssetEntry(Model):
    path: str
    kind: str=Field(pattern='^(image|video|audio|logo|character|font)$')
    license: str=Field(min_length=1,max_length=1000)
    source_url: str=Field(default='',max_length=2000)
    tags: list[str]=Field(default_factory=list,max_length=30)
    approved: bool=False


def save_asset(factory,project,id,p):
    path=project_file(factory,project,p.path)
    return record(factory,project,'asset',id,{**p.model_dump(),'sha256':digest(path),'project_id':project})


def find_assets(factory,query='',limit=20):
    found=[]
    for marker in sorted(factory.root.glob('*/project.json')):
        try:
            items=records(factory,marker.parent.name,'asset')
            for id,asset in items.items():
                if not asset['approved'] or query.lower() not in ' '.join(asset['tags']).lower(): continue
                path=project_file(factory,marker.parent.name,asset['path'])
                if digest(path)!=asset['sha256']: continue
                found.append({'id':id,**asset})
                if len(found)>=limit: return found
        except (ValueError,FileNotFoundError): continue
    return found


class QualityDecision(Model):
    video_path: str
    report_path: str
    evidence_id: str
    script_audit_id: str
    approved: bool
    assessment: str=Field(min_length=20,max_length=4000)
    accepted_issue_kinds: list[str]=Field(default_factory=list,max_length=50)
    visual_checks: list[str]=Field(min_length=1,max_length=30)


def save_quality(factory,project,id,p):
    video=project_file(factory,project,p.video_path);report=project_file(factory,project,p.report_path)
    data=json.loads(report.read_text());evidence=records(factory,project,'evidence').get(p.evidence_id)
    audit=records(factory,project,'script_audit').get(p.script_audit_id)
    if not evidence or not audit: raise ValueError('Evidence and script audit are required')
    fresh=validate_evidence(evidence['pack'],evidence['sources'])
    if data.get('source_sha256')!=digest(video): raise ValueError('Quality report must inspect these exact video bytes')
    nonwaivable={'caption_timing','invalid_caption_block','text_safe_area','text_timing','missing_transcript','speech_mismatch','caption_text_mismatch'}
    unhandled=[i for i in data.get('issues',[]) if i['kind'] in nonwaivable or i['kind'] not in p.accepted_issue_kinds]
    required={'visual_relevance','caption_accuracy','speech_intelligibility','brand_continuity','rights'}
    if p.approved and (unhandled or not fresh['ready'] or not audit['ready'] or not required.issubset(p.visual_checks)):
        raise ValueError('Final review has unresolved evidence, script, technical or visual checks')
    return record(factory,project,'quality',id,{**p.model_dump(),'video_sha256':digest(video),'report_sha256':digest(report),'evidence_sha256':hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest(),
                   'note':'Semantic visual/audio checks are the reviewing agent’s assessment, not a deterministic guarantee.'})


def repair_plan(factory,project,id,report_path,shot_ids):
    report=json.loads(project_file(factory,project,report_path).read_text())
    policy=policy_for(factory,project)
    limit=policy['policy']['max_repairs'] if policy and policy['valid'] else 2
    existing=records(factory,project,'repair')
    if id in existing: return existing[id]
    if len(existing)>=limit: return {'action':'pause','reason':'Repair limit reached; inspect failures before continuing'}
    return record(factory,project,'repair',id,{'action':'revise_selected_shots','shot_ids':shot_ids,'issues':report.get('issues',[]),
           'next_tool':'factory_preview_revision','rule':'Keep locks; regenerate affected assets, then repeat technical and semantic review. Never silently approve failures.'})
