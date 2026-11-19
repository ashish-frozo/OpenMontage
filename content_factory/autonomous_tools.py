"""Small, explicit MCP workflow surfaces; expensive operations still use saved routes."""
from datetime import datetime,date
from pydantic import Field
from content_factory.automation import AutomationPolicy,save_policy,policy_for,next_action,enqueue,dispatch,budget_snapshot,reserve,settle,record,records
from content_factory.workflow import ScriptAudit,ScriptLine,NarrationClip,AssetEntry,QualityDecision,save_evidence,audit_script,narration_timeline,save_asset,find_assets,save_quality,repair_plan
from content_factory.publishing import Delivery,prepare,publish,status,metrics,verify,reconcile
from lib.research import EvidencePack


def register(mcp,factory,signer=None):
    from content_factory.trends import register as register_trends
    register_trends(mcp,factory)
    read={'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False}
    write={**read,'readOnlyHint':False,'idempotentHint':False}

    @mcp.tool(annotations=read)
    def factory_next_action(project_id:str)->dict:
        """Get one bounded next action, current stage, jobs, policy validity and remaining budget context."""
        return next_action(factory,project_id)

    @mcp.tool(annotations=read)
    def factory_automation_policy(project_id:str)->dict:
        """Read current automation authorization; config/profile changes and expiry invalidate it."""
        return policy_for(factory,project_id) or {'valid':False,'reason':'No automation policy saved'}

    @mcp.tool(annotations=write)
    def factory_save_automation_policy(project_id:str,policy:AutomationPolicy,approval_evidence:str,expected_revision:int=0)->dict:
        """Save explicit user preauthorization for named stages/operations/accounts, bound to current configuration. Never invent approval."""
        return save_policy(factory,project_id,policy,approval_evidence,expected_revision)

    @mcp.tool(annotations=write)
    def factory_enqueue_job(project_id:str,plan_id:str,step_id:str,idempotency_key:str,due_at:datetime|None=None,approval_evidence:str|None=None)->dict:
        """Persist a saved operation for later admission. Does not run it or bypass budget, dependencies or approval gates."""
        return enqueue(factory,project_id,plan_id,step_id,idempotency_key,due_at,approval_evidence)

    @mcp.tool(annotations=write)
    def factory_dispatch_queue(project_id:str)->dict:
        """Admit due queued operations through normal submit validation. Repeated calls reuse durable keys; blocked items retain reasons."""
        return dispatch(factory,project_id)

    @mcp.tool(annotations=read)
    def factory_budget(project_id:str)->dict:
        """Read production reservations and reported actual costs, including uncertain work."""
        with factory.db(project_id) as db: result=budget_snapshot(db)
        limit=factory.settings(project_id)[1].max_project_estimate_usd
        return {**result,'limit_usd':limit,'remaining_usd':None if limit is None else max(0,limit-result['committed_usd'])}

    @mcp.tool(annotations=write)
    def factory_reserve_external_cost(project_id:str,cost_id:str,amount_usd:float,note:str)->dict:
        """Reserve a finite cost before an external LLM/research call. Use stable ids; this does not perform the external call."""
        from content_factory.service import identifier
        identifier(cost_id)
        with factory.db(project_id) as db:
            db.execute('BEGIN IMMEDIATE')
            from content_factory.models import ProjectConfig
            config=ProjectConfig.model_validate_json(db.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
            reserve(db,'external:'+cost_id,amount_usd,config.max_project_estimate_usd,note)
        return factory_budget(project_id)

    @mcp.tool(annotations=write)
    def factory_report_external_cost(project_id:str,cost_id:str,actual_usd:float)->dict:
        """Record provider-reported cost for an existing external reservation; conservative reservations remain charged."""
        with factory.db(project_id) as db:
            if not db.execute('SELECT id FROM budget WHERE id=?',('external:'+cost_id,)).fetchone(): raise ValueError('Unknown reservation')
            settle(db,'external:'+cost_id,actual_usd)
        return factory_budget(project_id)

    @mcp.tool(annotations=write)
    def factory_save_evidence(project_id:str,evidence_id:str,pack:EvidencePack)->dict:
        """Save claims linked to exact passages from completed research_fetch jobs; reject invented quotes and flag stale/disputed evidence."""
        result=save_evidence(factory,project_id,evidence_id,pack)
        return {'id':evidence_id,'topic':pack.topic,'claim_count':len(pack.claims),'source_ids':list(result['sources']),'review':result['review']}

    @mcp.tool(annotations=read)
    def factory_workflow_records(project_id:str,kind:str,offset:int=0,limit:int=20)->dict:
        """Read saved evidence, script_audit, asset, quality, repair or performance records for reuse and research feedback."""
        from content_factory.models import Page,paginate
        if kind not in {'evidence','script_audit','asset','quality','repair','performance','narration','publication_receipt','delivery_reconciliation'}: raise ValueError('Unknown record kind')
        items=[]
        for id,data in records(factory,project_id,kind).items():
            if kind=='evidence': data={**data,'sources':{sid:{k:v for k,v in source.items() if k!='text'} for sid,source in data['sources'].items()}}
            items.append({'id':id,**data})
        return paginate(items,Page(offset=offset,limit=limit))

    @mcp.tool(annotations=write)
    def factory_audit_script(project_id:str,audit_id:str,script:ScriptAudit)->dict:
        """Check script claim references/freshness, prepare pronunciation substitutions and estimate narration duration."""
        result=audit_script(factory,project_id,script)
        return record(factory,project_id,'script_audit',audit_id,{**result,'source':script.model_dump()})

    @mcp.tool(annotations=write)
    def factory_narration_timeline(project_id:str,timeline_id:str,clips:list[NarrationClip])->dict:
        """Measure narration files and build shot/caption timings from actual audio and supplied transcriber word timestamps."""
        if not 1<=len(clips)<=200: raise ValueError('Supply 1..200 narration clips')
        return record(factory,project_id,'narration',timeline_id,narration_timeline(factory,project_id,clips))

    @mcp.tool(annotations=write)
    def factory_remember_asset(project_id:str,asset_id:str,asset:AssetEntry)->dict:
        """Save a reusable local asset with content hash, explicit approval, license and source provenance."""
        return save_asset(factory,project_id,asset_id,asset)

    @mcp.tool(annotations=read)
    def factory_find_assets(query:str='',limit:int=20)->dict:
        """Find approved unchanged assets across this single-owner installation; match tag text and reuse paths."""
        if not 1<=limit<=100: raise ValueError('limit must be 1..100')
        return {'items':find_assets(factory,query,limit)}

    @mcp.tool(annotations=write)
    def factory_save_quality_review(project_id:str,review_id:str,review:QualityDecision)->dict:
        """Bind final technical and agent semantic assessment to exact rendered bytes and current evidence; unresolved issues prevent approval."""
        return save_quality(factory,project_id,review_id,review)

    @mcp.tool(annotations=write)
    def factory_repair_plan(project_id:str,repair_id:str,report_path:str,shot_ids:list[str])->dict:
        """Persist a bounded shot repair request. Does not rerender or bypass locks; pauses once repair budget is exhausted."""
        return repair_plan(factory,project_id,repair_id,report_path,shot_ids)

    @mcp.tool(annotations=write)
    def factory_prepare_delivery(project_id:str,delivery_id:str,delivery:Delivery)->dict:
        """Prepare a reviewed YouTube or Instagram delivery and schedule. No external upload; duplicate video submissions are rejected."""
        return prepare(factory,project_id,delivery_id,delivery)

    @mcp.tool(annotations=read)
    def factory_delivery_status(project_id:str,delivery_id:str)->dict:
        """Inspect persisted upload/container/publish state. An uncertain write must be reconciled, never blindly replayed."""
        return status(factory,project_id,delivery_id)

    @mcp.tool(annotations={**write,'openWorldHint':True})
    def factory_publish_delivery(project_id:str,delivery_id:str)->dict:
        """Execute a due delivery ONLY under a valid account-scoped publishing policy. External writes are journalled; uncertain outcomes are not retried."""
        return publish(factory,project_id,delivery_id,signer)

    @mcp.tool(annotations={**write,'openWorldHint':True})
    def factory_collect_performance(project_id:str,delivery_id:str,start:date,end:date)->dict:
        """Fetch YouTube analytics or Instagram Reel insights and persist a dated research-feedback snapshot."""
        return metrics(factory,project_id,delivery_id,start,end)

    @mcp.tool(annotations={**write,'openWorldHint':True})
    def factory_verify_delivery(project_id:str,delivery_id:str)->dict:
        """Read the remote video to verify its id/title/privacy or Instagram permalink, then save a delivery receipt. Never uploads."""
        return verify(factory,project_id,delivery_id)

    @mcp.tool(annotations={**write,'openWorldHint':True})
    def factory_reconcile_delivery(project_id:str,delivery_id:str,remote_id:str,verification_evidence:str)->dict:
        """Resolve an uncertain write using an operator-verified remote id. Reads provider state; never reuploads or republishes."""
        return reconcile(factory,project_id,delivery_id,remote_id,verification_evidence)

    @mcp.tool(annotations=read)
    def factory_inspect_frame(project_id:str,path:str):
        """Return a project image as an MCP image for visual review. Accepts rendered frames under the project, resizes to 1280px, and never reads outside it."""
        import base64,io
        from PIL import Image
        from mcp.types import ImageContent
        from content_factory.workflow import project_file
        source=project_file(factory,project_id,path)
        if source.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}: raise ValueError('Choose an image frame')
        with Image.open(source) as image:
            image.thumbnail((1280,1280));buffer=io.BytesIO();image.convert('RGB').save(buffer,format='JPEG',quality=85)
        return ImageContent(type='image',mimeType='image/jpeg',data=base64.b64encode(buffer.getvalue()).decode())
