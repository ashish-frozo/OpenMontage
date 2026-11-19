#!/usr/bin/env python3
"""Dispatch authorized queued jobs and due deliveries. No creative planning or automatic retries."""
import argparse,json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from content_factory.service import Factory
from content_factory.automation import dispatch,policy_for
from content_factory.publishing import db_init,publish

def tick(factory,signer=None):
    results=[]
    for marker in sorted(factory.root.glob('*/project.json')):
        project=marker.parent.name
        if not (marker.parent/'factory.sqlite3').is_file():continue
        try:
            policy=policy_for(factory,project)
            if not policy or not policy['valid']:continue
            queued=dispatch(factory,project)
            with factory.db(project) as db:
                db_init(db);ids=[r[0] for r in db.execute("SELECT id FROM deliveries WHERE status IN ('prepared','container_ready')")]
            for id in ids:
                result=publish(factory,project,id,signer)
                results.append({'project':project,'delivery':id,'status':result['status']})
            if queued['items']:results.append({'project':project,'queue':queued})
        except Exception as exc:results.append({'project':project,'error':str(exc)})
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--projects-dir');p.add_argument('--remote-config');p.add_argument('--once',action='store_true');p.add_argument('--interval',type=int,default=30);args=p.parse_args()
    if not 5<=args.interval<=300:p.error('interval must be 5..300 seconds')
    signer=None
    if args.remote_config:
        from content_factory.remote import load_config,DownloadSigner
        c=load_config(Path(args.remote_config).expanduser());signer=DownloadSigner(c['base_url'],c['client_secret'])
    factory=Factory(projects_dir=args.projects_dir)
    while True:
        print(json.dumps(tick(factory,signer),default=str),flush=True)
        if args.once:break
        time.sleep(args.interval)
