"""Persist reviewed revision candidates without retaining stale downstream approvals."""
import json
from pathlib import Path
from lib.creator import RevisionRequest, fingerprint, revision_plan
from lib.checkpoint import write_checkpoint
from lib.pipeline_loader import get_stage_order, load_pipeline


def save_revision(factory, project_id, request: RevisionRequest):
    root=factory.project(project_id);marker=factory.marker(project_id)
    checkpoint_path=root/'checkpoint_scene_plan.json'
    from content_factory.automation import policy_for
    automation = policy_for(factory, project_id)
    # Hold the same database writer lock as submission while invalidating old routes.
    with factory.db(project_id) as db:
        db.execute('BEGIN IMMEDIATE')
        active=db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','cancelling')").fetchone()[0]
        if active: raise ValueError('Wait for active jobs to finish before saving a creative revision')
        previous=json.loads(checkpoint_path.read_text())
        current=previous['artifacts']['scene_plan']
        if fingerprint(current)!=request.expected_fingerprint: raise ValueError('Saved scene plan changed; read it again')
        persisted=previous.get('metadata',{}).get('creator_locks',{})
        locks={sid:sorted(set(persisted.get(sid,[])+request.locks.get(sid,[]))) for sid in set(persisted)|set(request.locks)}
        request=request.model_copy(update={'scene_plan':current,'locks':locks})
        result=revision_plan(request)
        if not result['changes']: return {**result,'saved':False}
        # Keep submission locked through filesystem changes. Commit invalidation even
        # on filesystem failure so saved routes remain fail-closed.
        previous_revision=db.execute('SELECT revision FROM settings WHERE id=1').fetchone()[0]
        db.execute('UPDATE settings SET revision=revision+1 WHERE id=1')
        # A bounded scene repair preserves an already authorized scene-plan policy.
        # Actual configuration changes still invalidate it normally.
        if automation and automation['valid'] and 'scene_plan' in automation['policy']['approved_stages']:
            repairs=db.execute("SELECT COUNT(*) FROM workflow_records WHERE kind='applied_repair'").fetchone()[0]
            if repairs < automation['policy']['max_repairs']:
                db.execute("INSERT OR IGNORE INTO workflow_records VALUES ('applied_repair',?,?)",(result['review']['fingerprint'],json.dumps({'from_revision':previous_revision})))
                db.execute('UPDATE automation_policy SET config_revision=? WHERE id=1 AND config_revision=?',(previous_revision+1,previous_revision))
        try:
            stages=get_stage_order(load_pipeline(marker['pipeline_type']))
            downstream=stages[stages.index('scene_plan')+1:]
            # Revoke downstream approvals before making the candidate visible. Old artifacts
            # remain in archived checkpoints, but cannot be presented as current approvals.
            for stage in downstream:
                path=root/f'checkpoint_{stage}.json'
                if path.exists():
                    old=json.loads(path.read_text())
                    write_checkpoint(factory.root,project_id,stage,'failed',old.get('artifacts',{}),pipeline_type=marker['pipeline_type'],error='Invalidated by scene revision; review dependencies before reuse',metadata={'invalidated_by_scene_revision':result['review']['fingerprint']})
            history=root/'artifacts'/'creator-revisions'
            history.mkdir(parents=True,exist_ok=True)
            snapshot=history/(request.expected_fingerprint+'.json')
            if not snapshot.exists(): snapshot.write_text(json.dumps(previous,indent=2))
            artifacts={**previous.get('artifacts',{}),'scene_plan':result['candidate']}
            artifacts.pop('final_review',None)
            # in_progress deliberately removes prior approval. The creator must review the
            # new animatic and explicitly advance the normal gate.
            path=write_checkpoint(factory.root,project_id,'scene_plan','in_progress',artifacts,pipeline_type=marker['pipeline_type'],metadata={'creator_locks':locks,'revision':{k:v for k,v in result.items() if k!='candidate'}})
            return {**result,'saved':True,'checkpoint':str(path),'invalidated_stages':downstream,'next_action':'Render the updated animatic, review, and advance the scene-plan approval gate. Save fresh routes.'}
        finally:
            db.commit()
