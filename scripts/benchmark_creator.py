#!/usr/bin/env python3
"""Bounded OpenRouter revision-contract benchmark. No media production or publishing."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.creator import RevisionRequest, RevisionEdit, fingerprint, revision_plan


def cases():
    plan={'version':'1.1','scenes':[{'id':f's{i}','type':'animation','description':f'Beat {i}','start_seconds':(i-1)*2,'end_seconds':i*2,'shot_intent':'Explain the product','narrative_role':'evidence','metadata':{'voice':'approved','background':'navy','captions':'enabled'}} for i in range(1,4)]}
    specs=[
      ('hook','Change only s1 description to "Open with the result".',{'s1':{'description':'Open with the result'}},False),
      ('background','Change only s2 metadata.background to cream. Preserve its other metadata.',{'s2':{'metadata':{**plan['scenes'][1]['metadata'],'background':'cream'}}},False),
      ('shorten','Shorten s1 to one second by setting end_seconds=1. Ripple later shots.',{'s1':{'end_seconds':1}},True),
      ('extend','Extend s2 to three seconds by setting end_seconds=5. Ripple later shots.',{'s2':{'end_seconds':5}},True),
      ('cta','Change only s3 narrative_role to call_to_action.',{'s3':{'narrative_role':'call_to_action'}},False),
      ('intent','Change only s2 shot_intent to "Demonstrate the speed benefit".',{'s2':{'shot_intent':'Demonstrate the speed benefit'}},False),
      ('two_notes','Change s1 description to "Before" and s3 description to "After". No other changes.',{'s1':{'description':'Before'},'s3':{'description':'After'}},False),
      ('captions','Change only s3 metadata.background to white; preserve accessibility captions and voice.',{'s3':{'metadata':{**plan['scenes'][2]['metadata'],'background':'white'}}},False),
      ('recurring','Change s2 description to "Same product, closer framing". Recurring products are allowed.',{'s2':{'description':'Same product, closer framing'}},False),
      ('retime','Shorten s1 to one second and s2 to one second (set s1 end_seconds=1 and s2 end_seconds=3 before ripple). Ripple later shots.',{'s1':{'end_seconds':1},'s2':{'end_seconds':3}},True),
    ]
    locks={f's{i}':['metadata.voice','metadata.captions'] for i in range(1,4)}
    for name,prompt,updates,ripple in specs:
        expected=RevisionRequest(scene_plan=plan,expected_fingerprint=fingerprint(plan),changes=[{'shot_id':sid,'note':'Requested revision','set_fields':fields} for sid,fields in updates.items()],locks=locks,ripple=ripple)
        yield name,prompt,expected


def evaluate(value,expected):
    edit=RevisionEdit.model_validate(value)
    request=RevisionRequest(scene_plan=expected.scene_plan, **edit.model_dump())
    if request.scene_plan!=expected.scene_plan or request.locks!=expected.locks: raise ValueError('Preserve the supplied source plan and all locks')
    result=revision_plan(request);gold=revision_plan(expected)
    if result['candidate']!=gold['candidate']: raise ValueError('Candidate does not match the requested exact change; preserve unrelated fields')
    return {k:result[k] for k in ('rerender_shot_ids','retime_shot_ids','reuse_shot_ids')}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);parser.add_argument('--output',required=True);parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    if args.self_test:
        for _,_,e in cases(): evaluate(e.model_dump(exclude={"scene_plan"}),e)
        print('10 benchmark oracles passed');return
    key=os.environ.get('OPENROUTER_API_KEY') or (Path.home()/'.config/openrouter/api-key').read_text().strip()
    results=[]
    for name,prompt,expected in cases():
        messages=[{'role':'system','content':'Return only JSON matching this RevisionEdit schema. The server holds the source plan: do NOT return scene_plan. Send only expected_fingerprint, changes, locks and ripple. set_fields accepts dot paths, e.g. {"metadata.background":"cream"}. Preserve all supplied locks. '+json.dumps(RevisionEdit.model_json_schema())}, {'role':'user','content':json.dumps({'task':prompt,'scene_plan':expected.scene_plan,'expected_fingerprint':expected.expected_fingerprint,'locks':expected.locks})}]
        record={'case':name,'passed':False,'attempts':[]}
        for attempt in range(2):
            start=time.monotonic()
            body={'model':args.model,'messages':messages,'temperature':0,'reasoning':{'enabled':False},'max_tokens':3000,'response_format':{'type':'json_object'},'provider':{'allow_fallbacks':False}}
            req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            # No automatic network retry: a failed transport could already have billed.
            try:
                with urllib.request.urlopen(req,timeout=90) as response: result=json.load(response)
            except Exception as exc:
                record['attempts'].append({'transport_error':type(exc).__name__});break
            content=result['choices'][0]['message']['content'];item={'elapsed_seconds':time.monotonic()-start,'usage':result.get('usage',{}),'model':result.get('model'),'finish_reason':result['choices'][0].get('finish_reason'),'response':content}
            try:
                item['impact']=evaluate(json.loads(content),expected);record['passed']=True
            except Exception as exc: item['error']=str(exc)[:1500]
            record['attempts'].append(item)
            if record['passed']: break
            messages += ([{'role':'assistant','content':content}] if content else []) + [{'role':'user','content':'Return a complete JSON edit. Repair: '+item['error']}]
        results.append(record)
        report={'model_requested':args.model,'reasoning_enabled':False,'scope':'10 synthetic shot-revision contract tasks; not visual quality or end-to-end production','passed':sum(r['passed'] for r in results),'total':len(results),'results':results}
        output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2))
        print(name,record['passed'],len(record['attempts']),flush=True)
if __name__=='__main__': main()
