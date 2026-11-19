"""Durable execution controls. The calling agent owns creative decisions and stage progression."""
from __future__ import annotations
import hashlib
import json
import math
from datetime import datetime, timezone
from pydantic import Field
from content_factory.models import Model
from lib.pipeline_loader import load_pipeline, get_stage_order

class AutomationPolicy(Model):
    enabled: bool=False
    creative_discretion: bool=Field(default=False, description="Explicitly permit the agent to select a concept and production details within the saved brief; required for automatic proposal approval.")
    approved_stages: list[str]=Field(default_factory=list,max_length=30)
    allowed_operations: list[str]=Field(default_factory=list,max_length=200)
    expires_at: datetime
    max_repairs: int=Field(default=2,ge=0,le=5)
    publish_platforms: list[str]=Field(default_factory=list,max_length=2)
    publishing_accounts: dict[str,str]=Field(default_factory=dict)
    require_evidence: bool=True
    require_quality_review: bool=True


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS automation_policy (id INTEGER PRIMARY KEY, revision INTEGER, data TEXT, config_revision INTEGER, profile_revision INTEGER, evidence TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS automation_history (revision INTEGER PRIMARY KEY, data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS budget (id TEXT PRIMARY KEY, reserved REAL NOT NULL, actual REAL, status TEXT NOT NULL, note TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS pending_jobs (id TEXT PRIMARY KEY, plan_id TEXT, step_id TEXT, evidence TEXT, due TEXT, status TEXT, job_id TEXT, error TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS workflow_records (kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id))')


def record(factory,project,kind,id,data):
    from content_factory.service import identifier
    identifier(id)
    with factory.db(project) as db:
        old=db.execute('SELECT data FROM workflow_records WHERE kind=? AND id=?',(kind,id)).fetchone()
        serialized=json.dumps(data,sort_keys=True,default=str)
        if old and old[0]!=serialized: raise ValueError('Record is immutable; use a new id for a revision')
        db.execute('INSERT OR IGNORE INTO workflow_records VALUES (?,?,?)',(kind,id,serialized))
    return data


def records(factory,project,kind):
    with factory.db(project) as db:
        return {r[0]:json.loads(r[1]) for r in db.execute('SELECT id,data FROM workflow_records WHERE kind=?',(kind,))}


def save_policy(factory,project,policy,evidence,expected_revision=0):
    policy=AutomationPolicy.model_validate(policy)
    if not evidence.strip(): raise ValueError('Quote the user authorization for this specific automation policy')
    if policy.expires_at.tzinfo is None or policy.expires_at<=datetime.now(timezone.utc): raise ValueError('Policy requires a future timezone-aware expiry')
    revision,config=factory.settings(project)
    if config.max_project_estimate_usd is None: raise ValueError('Set max_project_estimate_usd before enabling automation')
    stages=get_stage_order(load_pipeline(factory.marker(project)['pipeline_type']))
    if set(policy.approved_stages)-set(stages): raise ValueError('Unknown approved stage')
    if set(policy.publish_platforms)-{'youtube','instagram'}: raise ValueError('Unsupported publishing platform')
    if any(not policy.publishing_accounts.get(p) for p in policy.publish_platforms): raise ValueError('Pin a connected account for every publishing platform')
    for op in policy.allowed_operations: factory.registry.resolve(op)
    profile=factory.customer_profile_for_project(project)
    with factory.db(project) as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT revision FROM automation_policy WHERE id=1').fetchone()
        current=current[0] if current else 0
        if current!=expected_revision: raise ValueError('Automation policy changed; read it again')
        if db.execute('SELECT revision FROM settings WHERE id=1').fetchone()[0]!=revision: raise ValueError('Configuration changed')
        data={'policy':policy.model_dump(mode='json'),'approval_evidence':evidence,'config_revision':revision,'profile_revision':profile['revision'] if profile else None}
        db.execute('INSERT OR REPLACE INTO automation_policy VALUES (1,?,?,?,?,?)',(current+1,policy.model_dump_json(),revision,data['profile_revision'],evidence))
        db.execute('INSERT INTO automation_history VALUES (?,?)',(current+1,json.dumps(data)))
    return {'revision':current+1,**data}


def policy_for(factory,project):
    revision,config=factory.settings(project)
    profile=factory.customer_profile_for_project(project)
    with factory.db(project) as db:
        row=db.execute('SELECT * FROM automation_policy WHERE id=1').fetchone()
    if not row: return None
    p=AutomationPolicy.model_validate_json(row['data'])
    valid=p.enabled and p.expires_at>datetime.now(timezone.utc) and row['config_revision']==revision and row['profile_revision']==(profile['revision'] if profile else None)
    if profile and profile['profile']['safety']['human_review_required']: valid=False
    return {'revision':row['revision'],'policy':p.model_dump(mode='json'),'valid':valid,'approval_evidence':row['evidence']}


def approval(factory,project,stage=None,operation=None):
    value=policy_for(factory,project)
    if not value or not value['valid']: return None
    p=value['policy']
    if stage and stage not in p['approved_stages']: return None
    if operation and operation not in p['allowed_operations']: return None
    return f"Saved automation policy revision {value['revision']}: {value['approval_evidence']}"


def budget_snapshot(db):
    rows=db.execute('SELECT * FROM budget').fetchall()
    committed=sum(max(r['reserved'],r['actual'] or 0) for r in rows if r['status']!='released')
    return {'committed_usd':committed,'actual_reported_usd':sum(r['actual'] or 0 for r in rows),
            'entries':[dict(r) for r in rows], 'note':'Conservative reservations include unknown/uncertain charges. Provider billing can exceed estimates.'}


def reserve(db,id,amount,limit,note):
    if not math.isfinite(amount) or amount<0: raise ValueError('Cost must be finite and nonnegative')
    old=db.execute('SELECT reserved,note FROM budget WHERE id=?',(id,)).fetchone()
    if old:
        if old[0]!=amount or old[1]!=note: raise ValueError('Budget idempotency conflict')
        return
    if limit is not None and budget_snapshot(db)['committed_usd']+amount>limit+1e-9:
        raise ValueError('Production budget exhausted; no work submitted')
    db.execute('INSERT INTO budget VALUES (?,?,NULL,?,?)',(id,amount,'reserved',note))


def settle(db,id,actual):
    if actual is not None and (not math.isfinite(actual) or actual<0): raise ValueError('Invalid actual cost')
    db.execute("UPDATE budget SET actual=?,status='settled' WHERE id=?",(actual,id))


def next_action(factory,project):
    from lib.checkpoint import get_next_stage,read_checkpoint
    marker=factory.marker(project);stage=get_next_stage(factory.root,project,marker['pipeline_type'])
    with factory.db(project) as db:
        active=[{'job_id':r[0],'status':r[1]} for r in db.execute("SELECT id,status FROM jobs WHERE status IN ('queued','running','cancelling','interrupted')")]
        pending=[dict(r) for r in db.execute("SELECT id,status,error FROM pending_jobs WHERE status!='submitted' LIMIT 20")]
        budget=budget_snapshot(db)
    if active: return {'action':'inspect_jobs','jobs':active,'budget':{k:v for k,v in budget.items() if k!='entries'}}
    if stage is None: return {'action':'complete','pending':pending}
    current_policy=policy_for(factory,project)
    if current_policy and current_policy['valid'] and stage not in current_policy['policy']['approved_stages']:
        return {'action':'await_approval','stage':stage,'reason':'Stage is outside the saved automation authorization','pending':pending}
    checkpoint=read_checkpoint(factory.root,project,stage)
    return {'action':'await_approval' if checkpoint and checkpoint['status']=='awaiting_human' and not approval(factory,project,stage=stage) else 'execute_stage',
            'stage':stage,'next_tool':'factory_stage_context','policy':policy_for(factory,project),'pending':pending,
            'budget':{k:v for k,v in budget.items() if k!='entries'},'rule':'Read the stage instructions; use saved artifacts, never re-create completed stages. Uncertain jobs require reconciliation.'}


def enqueue(factory,project,plan,step,key,due=None,evidence=None):
    from content_factory.service import identifier
    for value in (plan,step,key): identifier(value)
    due=due or datetime.now(timezone.utc)
    if due.tzinfo is None: raise ValueError('Schedule requires timezone')
    with factory.db(project) as db:
        row=db.execute('SELECT data FROM plans WHERE id=?',(plan,)).fetchone()
        if not row or step not in {s['id'] for s in json.loads(row[0])['steps']}: raise ValueError('Unknown saved plan/step')
        existing=db.execute('SELECT * FROM pending_jobs WHERE id=?',(key,)).fetchone()
        if existing:
            if existing['plan_id']!=plan or existing['step_id']!=step: raise ValueError('Queue idempotency conflict')
            return dict(existing)
        db.execute('INSERT INTO pending_jobs VALUES (?,?,?,?,?,?,NULL,NULL)',(key,plan,step,evidence,due.isoformat(),'waiting'))
    return {'id':key,'status':'waiting','due':due.isoformat()}


def dispatch(factory,project):
    # Concurrent dispatchers are safe: submit uses the same durable idempotency key.
    with factory.db(project) as db:
        rows=db.execute("SELECT * FROM pending_jobs WHERE status='waiting' ORDER BY due,id").fetchall()
    results=[]
    for row in rows:
        if datetime.fromisoformat(row['due'])>datetime.now(timezone.utc): continue
        try:
            job=factory.submit(project,row['plan_id'],row['step_id'],row['id'],row['evidence'])
            with factory.db(project) as db: db.execute("UPDATE pending_jobs SET status='submitted',job_id=?,error=NULL WHERE id=?",(job['job_id'],row['id']))
            results.append({'id':row['id'],**job})
        except ValueError as exc:
            with factory.db(project) as db: db.execute('UPDATE pending_jobs SET error=? WHERE id=?',(str(exc),row['id']))
            results.append({'id':row['id'],'status':'waiting','reason':str(exc)})
    return {'items':results}


def validate_auto_checkpoint(factory,project,stage,artifacts):
    policy=policy_for(factory,project)
    if not policy or not policy['valid']: return
    p=policy['policy']
    if p['require_evidence'] and stage in {'research','script','compose','publish'}:
        from lib.research import validate_evidence
        evidence=records(factory,project,'evidence')
        if not any(validate_evidence(e['pack'],e['sources'])['ready'] for e in evidence.values()):
            raise ValueError('Automatic completion requires current reviewed research evidence')
        if stage=='script':
            script=[(s['id'],s['text']) for s in artifacts.get('script',{}).get('sections',[])]
            audits=records(factory,project,'script_audit')
            if not script or not any(a['ready'] and [(s['id'],s['text']) for s in a['source']['lines']]==script for a in audits.values()):
                raise ValueError('Automatic script completion requires a passing audit of these exact script sections')
    if p['require_quality_review'] and stage in {'compose','publish'}:
        from content_factory.workflow import project_file,digest
        reviews=records(factory,project,'quality')
        final=artifacts.get('final_review',{})
        if stage=='compose' and not final.get('output_path'):raise ValueError('Automatic compose completion requires final_review.output_path')
        candidates=[r for r in reviews.values() if r['approved'] and (stage!='compose' or r['video_path']==final['output_path'])]
        if not any(digest(project_file(factory,project,r['video_path']))==r['video_sha256'] for r in candidates):
            raise ValueError('Automatic completion requires a passing review for the current rendered bytes')


def approval_decision(factory,project):
    value=policy_for(factory,project)
    if not value or not value['valid']: return None
    return {'decision_id':f'automation-policy-{value["revision"]}','stage':'proposal','category':'approval_policy',
            'subject':'Automatic production authorization','options_considered':[{'option_id':'saved-policy','label':'Explicit saved automation policy','score':1,'reason':value['approval_evidence']}],
            'selected':'saved-policy','reason':value['approval_evidence'],'user_visible':True,'user_approved':True}
