"""YouTube/Instagram delivery via the authenticated local Composio CLI.

Every external mutation is journalled BEFORE invocation. Unknown outcomes are
never replayed. A background scheduler/agent calls publish_due after restart.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from datetime import date,datetime,timezone
from typing import Literal
from pydantic import Field
from content_factory.models import Model
from content_factory.automation import policy_for,records,record
from content_factory.workflow import project_file,digest
from lib.research import validate_evidence


class Delivery(Model):
    platform: Literal['youtube','instagram']
    account: str=Field(min_length=1,max_length=200)
    video_path: str
    quality_id: str
    title: str=Field(min_length=1,max_length=100)
    description: str=Field(default='',max_length=5000)
    tags: list[str]=Field(default_factory=list,max_length=30)
    privacy: Literal['private','unlisted','public']='private'
    instagram_user_id: str=Field(default='me',pattern=r'^(me|[0-9]+)$')
    due_at: datetime
    category_id: str='22'


def cli(slug,params,account,file=None):
    from pathlib import Path
    executable=shutil.which('composio') or (str(Path.home()/'.local/bin/composio') if (Path.home()/'.local/bin/composio').is_file() else None)
    if not executable: raise ValueError('Composio CLI is not installed on the MCP host')
    args=[executable,'execute',slug,'-d','-']
    if account: args+=['--account',account]
    if file: args+=['--file',str(file)]
    result=subprocess.run(args,input=json.dumps(params),capture_output=True,text=True,timeout=600)
    # Do not expose CLI stderr: it may contain temporary upload URLs or auth data.
    if result.returncode: raise ValueError('Composio execution failed; inspect provider state before retrying any write')
    data=json.loads(result.stdout)
    if data.get('successful') is False or data.get('success') is False or data.get('error'):
        raise ValueError('Provider reported failure; inspect provider state before retrying any write')
    return data


def body(result):
    data=result.get('data',result)
    if isinstance(data,dict) and isinstance(data.get('data'),dict): data=data['data']
    return data


def db_init(db):
    db.execute('CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, data TEXT, status TEXT, remote_id TEXT, container_id TEXT, error TEXT)')


def check(factory,project,p):
    policy=policy_for(factory,project)
    if not policy or not policy['valid'] or 'publish' not in policy['policy']['approved_stages'] or p.platform not in policy['policy']['publish_platforms'] or policy['policy']['publishing_accounts'].get(p.platform)!=p.account:
        raise ValueError('Publishing requires an active saved policy naming this platform and connected account')
    from lib.checkpoint import read_checkpoint
    from lib.pipeline_loader import load_pipeline
    manifest=load_pipeline(factory.marker(project)['pipeline_type'])
    for stage in manifest['stages']:
        if stage['name']=='publish': break
        checkpoint=read_checkpoint(factory.root,project,stage['name'])
        if not checkpoint or checkpoint['status']!='completed': raise ValueError('Finish production checkpoints before publishing')
    video=project_file(factory,project,p.video_path)
    quality=records(factory,project,'quality').get(p.quality_id)
    if not quality or not quality['approved'] or digest(video)!=quality['video_sha256']: raise ValueError('A passing final review for these exact video bytes is required')
    evidence=records(factory,project,'evidence')[quality['evidence_id']]
    if not validate_evidence(evidence['pack'],evidence['sources'])['ready']: raise ValueError('Evidence expired or needs review')
    if p.platform=='instagram' and p.privacy!='public': raise ValueError('Instagram publishing is public; explicitly select privacy=public')
    return video


def prepare(factory,project,id,p):
    from content_factory.service import identifier
    identifier(id)
    if p.due_at.tzinfo is None: raise ValueError('due_at requires a timezone')
    video=project_file(factory,project,p.video_path)
    quality=records(factory,project,'quality').get(p.quality_id)
    if not quality or not quality['approved'] or quality['video_sha256']!=digest(video): raise ValueError('Review the final video before preparing delivery')
    from lib.creator_media import probe
    info=probe(video);stream=next((s for s in info['streams'] if s['codec_type']=='video'),None)
    if not stream: raise ValueError('Delivery file has no video')
    if p.platform=='instagram' and stream['width']>=stream['height']: raise ValueError('This Reels workflow requires a portrait rendition; render a reviewed 9:16 variant')
    fingerprint=f'{p.platform}:{p.account}:{quality["video_sha256"]}'
    revision,_=factory.settings(project)
    profile=factory.customer_profile_for_project(project)
    data={**p.model_dump(mode='json'),'video_sha256':quality['video_sha256'],'config_revision':revision,'profile_revision':profile['revision'] if profile else None}
    with factory.db(project) as db:
        db_init(db)
        old=db.execute('SELECT id,data,status,remote_id,fingerprint FROM deliveries WHERE id=? OR fingerprint=?',(id,fingerprint)).fetchone()
        if old:
            if old['data']!=json.dumps(data,sort_keys=True):
                if old['id']==id and old['fingerprint']==fingerprint and old['status'] in {'prepared','blocked'} and not old['remote_id']:
                    import hashlib
                    version=id+'-'+hashlib.sha256(old['data'].encode()).hexdigest()[:24]
                    db.execute("INSERT OR IGNORE INTO workflow_records VALUES ('delivery_history',?,?)",(version,old['data']))
                    db.execute("UPDATE deliveries SET data=?,status='prepared',container_id=NULL,error=NULL WHERE id=?",(json.dumps(data,sort_keys=True),id))
                    return {'id':id,'status':'prepared','updated':True}
                raise ValueError('Duplicate video delivery or immutable submitted work; update the original prepared delivery id')
            return {'id':old['id'],'status':'already_prepared'}
        db.execute('INSERT INTO deliveries VALUES (?,?,?, ?,NULL,NULL,NULL)',(id,fingerprint,json.dumps(data,sort_keys=True),'prepared'))
    return {'id':id,'status':'prepared','due_at':p.due_at.isoformat(),'note':'No upload or publication occurred. A valid account-scoped policy is required at execution.'}


def status(factory,project,id):
    with factory.db(project) as db:
        db_init(db);r=db.execute('SELECT * FROM deliveries WHERE id=?',(id,)).fetchone()
    if not r: raise ValueError('Unknown delivery')
    return dict(r)


def update(factory,project,id,**values):
    assert set(values)<= {'status','remote_id','container_id','error'}
    with factory.db(project) as db:
        db.execute('UPDATE deliveries SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),id))


def publish(factory,project,id,signer=None):
    row=status(factory,project,id);data=json.loads(row['data']);p=Delivery.model_validate({k:v for k,v in data.items() if k not in {'video_sha256','config_revision','profile_revision'}})
    if row['status'] in {'published','uploaded','uncertain','sending','publishing'}: return row
    if p.due_at>datetime.now(timezone.utc): return {'id':id,'status':'scheduled','due_at':p.due_at.isoformat()}
    if factory.settings(project)[0]!=data['config_revision']: raise ValueError('Project changed; delivery must be reviewed again')
    profile=factory.customer_profile_for_project(project)
    if data.get('profile_revision')!=(profile['revision'] if profile else None): raise ValueError('Customer profile changed; review and prepare the delivery again')
    video=check(factory,project,p)
    if p.platform=='instagram' and signer is None: raise ValueError('Instagram needs remote signed media serving; use the remote MCP endpoint')
    from pathlib import Path
    if not (shutil.which('composio') or (Path.home()/'.local/bin/composio').is_file()): raise ValueError('Install and authenticate Composio CLI on the host before publishing')
    expected='container_ready' if row['container_id'] else 'prepared'
    with factory.db(project) as db:
        claimed=db.execute("UPDATE deliveries SET status='sending' WHERE id=? AND status=?",(id,expected)).rowcount
    if not claimed: return status(factory,project,id)
    try:
        if p.platform=='youtube':
            result=cli('YOUTUBE_UPLOAD_VIDEO',{'title':p.title,'description':p.description,'tags':p.tags,'categoryId':p.category_id,'privacyStatus':p.privacy},p.account,file=video)
            remote=body(result).get('id')
            if not remote: raise ValueError('Upload response has no video id; outcome unknown')
            update(factory,project,id,status='uploaded',remote_id=remote)
        else:
            container=row['container_id']
            if not container:
                relative=video.relative_to(factory.project(project)).as_posix()
                result=cli('INSTAGRAM_POST_IG_USER_MEDIA',{'ig_user_id':p.instagram_user_id,'media_type':'REELS','video_url':signer.sign(project,relative,ttl_seconds=3600),'caption':p.description},p.account)
                container=body(result).get('id')
                if not container: raise ValueError('Container response has no id; outcome unknown')
                update(factory,project,id,container_id=container,status='container_ready')
                # Persist the container and return; polling is read-only and restart-safe.
                return status(factory,project,id)
            state=body(cli('INSTAGRAM_GET_POST_STATUS',{'creation_id':container},p.account))
            if state.get('status_code')!='FINISHED':
                waiting=state.get('status_code')=='IN_PROGRESS'
                update(factory,project,id,status='container_ready' if waiting else ('blocked' if state.get('status_code') in {'ERROR','EXPIRED'} else 'uncertain'),error='Container state: '+str(state.get('status_code','unknown')))
                return status(factory,project,id)
            update(factory,project,id,status='publishing')
            result=cli('INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH',{'ig_user_id':p.instagram_user_id,'creation_id':container,'max_wait_seconds':60},p.account)
            remote=body(result).get('id')
            if not remote: raise ValueError('Publish response has no media id; outcome unknown')
            update(factory,project,id,status='published',remote_id=remote,error=None)
    except Exception as exc:
        update(factory,project,id,status='uncertain',error=str(exc))
    return status(factory,project,id)


def metrics(factory,project,id,start,end):
    row=status(factory,project,id);data=json.loads(row['data']);remote=row['remote_id']
    if not remote: raise ValueError('Delivery has no verified remote id')
    if end<start: raise ValueError('end must not precede start')
    if data['platform']=='youtube':
        result=cli('YOUTUBE_QUERY_ANALYTICS',{'ids':'channel==MINE','startDate':start.isoformat(),'endDate':end.isoformat(),'metrics':'views,likes,comments,shares,averageViewDuration','filters':'video=='+remote},data['account'])
    else:
        result=cli('INSTAGRAM_GET_IG_MEDIA_INSIGHTS',{'ig_media_id':remote,'metric':['views','reach','saved','shares','ig_reels_avg_watch_time']},data['account'])
    key=id+'-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    return record(factory,project,'performance',key,{'delivery_id':id,'platform':data['platform'],'collected_at':datetime.now(timezone.utc).isoformat(),'window':{'start':str(start),'end':str(end)},'raw':result,
            'note':'Instagram metrics are lifetime; YouTube uses the requested window. Compare only matching platform, metric definitions and observation windows.'})


def verify(factory,project,id):
    row=status(factory,project,id);data=json.loads(row['data'])
    if not row['remote_id']: raise ValueError('Remote id unknown; reconcile provider state before verification')
    if data['platform']=='youtube':
        result=body(cli('YOUTUBE_GET_VIDEO_DETAILS_BATCH',{'id':[row['remote_id']],'parts':['snippet','status']},data['account']))
        items=result.get('items',[])
        if not items or items[0].get('id')!=row['remote_id']: raise ValueError('Uploaded video not visible to the connected account')
        remote=items[0]
        if remote.get('snippet',{}).get('title')!=data['title']: raise ValueError('Remote title differs from delivery')
        upload=remote.get('status',{}).get('uploadStatus')
        if upload in {'failed','rejected','deleted'}:
            update(factory,project,id,status='blocked',error='YouTube processing status: '+upload)
            return {'id':id,'verified':False,'status':'blocked'}
        if upload=='uploaded': return {'id':id,'verified':False,'status':'processing'}
        visibility=remote.get('status',{}).get('privacyStatus')
        if visibility!=data['privacy']: raise ValueError('Remote privacy differs from delivery')
        state='published' if visibility=='public' else 'uploaded'
        receipt={'id':row['remote_id'],'url':'https://www.youtube.com/watch?v='+row['remote_id'],'visibility':visibility}
    else:
        remote=body(cli('INSTAGRAM_GET_IG_MEDIA',{'ig_media_id':row['remote_id'],'fields':'id,permalink,caption,media_type'},data['account']))
        if remote.get('id')!=row['remote_id']: raise ValueError('Published media not visible to connected account')
        state='published';receipt={'id':remote['id'],'url':remote.get('permalink'),'visibility':'public'}
    update(factory,project,id,status=state,error=None)
    return record(factory,project,'publication_receipt',id,receipt)


def reconcile(factory,project,id,remote_id,evidence):
    if not evidence.strip(): raise ValueError('Provide actual operator verification of the remote item')
    row=status(factory,project,id)
    if row['status'] not in {'uncertain','sending','publishing'}: raise ValueError('Only uncertain delivery writes need reconciliation')
    # Persist known identifier without issuing a new write to the provider.
    update(factory,project,id,remote_id=remote_id)
    receipt=verify(factory,project,id)
    record(factory,project,'delivery_reconciliation',id,{'remote_id':remote_id,'evidence':evidence})
    return receipt
