"""Creator contracts and deterministic editorial checks. No creative routing decisions."""
from __future__ import annotations
import hashlib
import json
from copy import deepcopy
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from schemas.artifacts import validate_artifact

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class SoundCue(Strict):
    id: str = Field(min_length=1, max_length=80)
    role: Literal['narration', 'music', 'ambience', 'sfx', 'silence']
    path: str | None = None
    start: float = Field(ge=0, le=3600)
    duration: float = Field(gt=0, le=3600)
    source_start: float = Field(default=0, ge=0)
    gain: float = Field(default=1, ge=0, le=2)
    fade_in: float = Field(default=0, ge=0)
    fade_out: float = Field(default=0, ge=0)
    intent: str = Field(min_length=1, max_length=500)

class ShotChange(Strict):
    shot_id: str
    note: str = Field(min_length=1, max_length=2000)
    at_seconds: float | None = Field(default=None, ge=0)
    set_fields: dict = Field(min_length=1, description="Fields to update. Dot paths such as metadata.background preserve siblings. Do not change id.")

class RevisionEdit(Strict):
    expected_fingerprint: str
    changes: list[ShotChange] = Field(min_length=1, max_length=200)
    locks: dict[str, list[str]] = Field(default_factory=dict, description='Shot id -> locked dot-separated field paths; * locks the complete shot.')
    ripple: bool = False


class RevisionRequest(RevisionEdit):
    scene_plan: dict = Field(description="Unchanged source plan; put requested edits only in changes.")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def review_scene_plan(plan):
    import jsonschema
    try: validate_artifact('scene_plan', plan)
    except jsonschema.ValidationError as exc: raise ValueError('.'.join(map(str,exc.absolute_path))+': '+exc.message) from exc
    issues, previous, seen = [], {}, set()
    end = 0
    for i, shot in enumerate(plan['scenes']):
        sid = shot['id']
        if sid in seen: raise ValueError(f'Duplicate shot id: {sid}')
        seen.add(sid)
        a,b=shot['start_seconds'],shot['end_seconds']
        if b <= a: raise ValueError(f'{sid}: end_seconds must exceed start_seconds')
        if a < end - 1e-6: raise ValueError(f'{sid}: scenes overlap or are out of order')
        if a > end + 1e-6: issues.append({'shot_id':sid,'kind':'gap','seconds':a-end})
        end=b
        for field in ('shot_intent','narrative_role'):
            if not shot.get(field): issues.append({'shot_id':sid,'kind':'missing_intent','field':field})
        for entity in shot.get('continuity',[]):
            eid=entity['entity_id']
            old=previous.get(eid)
            if old:
                mismatch={k:{'previous':v,'current':entity['state_in'].get(k)} for k,v in old.items() if entity['state_in'].get(k)!=v}
                if mismatch and not entity.get('change_reason'):
                    issues.append({'shot_id':sid,'entity_id':eid,'kind':'continuity_change','fields':mismatch})
            previous[eid]=entity['state_out']
    return {'fingerprint':fingerprint(plan),'duration':end,'issues':issues,'ready':not issues,
            'human_review':['story clarity','emotional progression','visual continuity against actual frames','intentional repetition']}


def revision_plan(request: RevisionRequest):
    original=request.scene_plan
    review_scene_plan(original)
    if fingerprint(original)!=request.expected_fingerprint: raise ValueError('Scene plan changed; review the current plan and use its fingerprint')
    candidate=deepcopy(original); by_id={s['id']:s for s in candidate['scenes']}
    for sid,paths in request.locks.items():
        if sid not in by_id: raise ValueError(f'Unknown locked shot: {sid}')
        for path in paths:
            if path!='*': _field(by_id[sid],path)
    touched=set()
    for change in request.changes:
        if change.shot_id not in by_id: raise ValueError(f'Unknown shot: {change.shot_id}')
        if change.shot_id in touched: raise ValueError('Combine updates to a shot in one change')
        touched.add(change.shot_id)
        if 'id' in change.set_fields: raise ValueError('Stable shot ids cannot be edited')
        shot=by_id[change.shot_id]
        if change.at_seconds is not None and not shot['start_seconds'] <= change.at_seconds <= shot['end_seconds']:
            raise ValueError('Timestamped note must fall inside the referenced shot')
        keys=list(change.set_fields)
        if any(a!=b and b.startswith(a+'.') for a in keys for b in keys): raise ValueError('Do not mix parent and child updates in one change')
        for path,value in change.set_fields.items():
            parts=path.split('.')
            if parts[0]=='id': raise ValueError('Stable shot ids cannot be edited')
            parent=shot
            for part in parts[:-1]:
                if part not in parent or not isinstance(parent[part],dict): raise ValueError(f'Unknown parent field: {path}')
                parent=parent[part]
            parent[parts[-1]]=deepcopy(value)
    if request.ripple:
        cursor=0
        for shot in candidate['scenes']:
            duration=shot['end_seconds']-shot['start_seconds']
            shot.update(start_seconds=cursor,end_seconds=cursor+duration);cursor+=duration
    for old in original['scenes']:
        new=by_id[old['id']]
        for path in request.locks.get(old['id'],[]):
            if (old if path=='*' else _field(old,path)) != (new if path=='*' else _field(new,path)):
                raise ValueError(f"Locked field changed: {old['id']}.{path}")
    review=review_scene_plan(candidate)
    changes=[];rerender=[];retime=[]
    for old,new in zip(original['scenes'],candidate['scenes']):
        fields=[k for k in set(old)|set(new) if old.get(k)!=new.get(k)]
        if not fields: continue
        changes.append({'shot_id':old['id'],'fields':sorted(fields)})
        old_duration=old['end_seconds']-old['start_seconds'];new_duration=new['end_seconds']-new['start_seconds']
        if set(fields)<= {'start_seconds','end_seconds'} and abs(old_duration-new_duration)<1e-6: retime.append(old['id'])
        else: rerender.append(old['id'])
    return {'candidate':candidate,'review':review,'changes':changes,'rerender_shot_ids':rerender,'retime_shot_ids':retime,
            'reuse_shot_ids':[s['id'] for s in original['scenes'] if s['id'] not in rerender],
            'invalidate':['animatic','edit_decisions','final_mix','composition','final_review','editor_package'] if changes else [],
            'notes':[c.model_dump(exclude={'set_fields'}) for c in request.changes],
            'applied':False,'next_action':'Save candidate through factory_checkpoint and obtain the existing scene-plan approval before executing replacement assets.'}


def _field(obj,path):
    for key in path.split('.'):
        if not isinstance(obj,dict) or key not in obj: raise ValueError(f'Unknown lock field: {path}')
        obj=obj[key]
    return obj
