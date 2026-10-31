"""Reproducible dev event replay. Product and protocol-test outputs scored separately.
This is not a real-model comparison. Gold is loaded only after outputs are produced.
"""
import json,sys,tempfile,time,hashlib
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from apps.api import main
from evals.baselines.protocol import run,digest
from evals.baselines.fixture_transport import ScriptedTransport
from evals.judges.evidence import EvidenceIndex
from evals.judges.objective import judge

def product_replay(task):
 old=main.DB;folder=ROOT/'var/replay';folder.mkdir(exist_ok=True)
 main.DB=folder/('run-'+str(time.time_ns())+'.sqlite3');client=TestClient(main.app);started=time.monotonic();checkpoints=[];questions=0
 try:
  p=ROOT/task['files'][0];response=client.post('/api/import',files={'file':(p.name,p.read_bytes(),'message/rfc822')});assert response.status_code==200,response.text
  case=response.json();id=case['id']
  for stage,event in enumerate(task['events']):
   response=client.post(f'/api/cases/{id}/prices',json={'revision':case['revision'],'values':{'prices':event['prices']}});assert response.status_code==200,response.text;case=response.json()
   if stage:assert client.get(f'/api/cases/{id}/export').status_code==409,'old approval exported changed prices'
   answer=event['answers'].get('approve');questions+=1
   if answer:
    response=client.post(f'/api/cases/{id}/approve',json={'revision':case['revision'],'values':{'actor':answer['actor']}});assert response.status_code==200,response.text;case=response.json()
   else:
    draft=client.get(f'/api/cases/{id}/draft').json()['text'];assert '价格' in draft
    assert client.post(f'/api/cases/{id}/approve',json={'revision':case['revision'],'values':{'actor':'test'}}).status_code==422
   exported=client.get(f'/api/cases/{id}/export');allowed=exported.status_code==200
   rows=[]
   for r in case['rows']:
    p=r['price'];ref={'sha256':digest(event['prices']),'index':event['prices'].index(p)} if p in event['prices'] and p else None
    rows.append({**{k:r[k] for k in ('rfq','part','quantity','unit','condition','sources','total')},'price':p,'price_source':ref,'status':'ready' if r['approved'] else 'unpriced','approval':{'price_version':event['price_version'],'answer_id':answer['id']} if r['approved'] and answer else {}})
   checkpoints.append({'stage':stage,'output':{'rows':rows,'export_allowed':allowed,'approval_snapshot':digest(event['prices']) if allowed else None}})
  return {'kind':'product-offline-event-replay','model_status':'not_run','checkpoints':checkpoints,'human_interventions':questions,'elapsed_seconds':time.monotonic()-started,'database':str(main.DB)}
 finally:main.DB=old

def main_run():
 task=json.loads((ROOT/'evals/cases/tasks/lifecycle.json').read_text(encoding='utf-8-sig'));cfg=json.loads((ROOT/'evals/configs/strong-agent.json').read_text(encoding='utf-8-sig'))
 product=product_replay(task);fixture=run(task,ScriptedTransport(),cfg)
 # No judge/gold is passed to either runner or its tools.
 gold=json.loads((ROOT/'evals/gold/lifecycle.json').read_text(encoding='utf-8-sig'));index=EvidenceIndex()
 for file in task['files']:
  p=ROOT/file;index.add(p.name,p.read_bytes())
 report={'kind':'offline-engine-and-transport-regression-not-model-comparison','task_id':task['id'],'family':task['family'],'split':task['split'],'task_hash':digest(task),'product':product,'fixture_transport':fixture}
 report['code_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'apps/api/main.py',ROOT/'apps/api/domain.py',ROOT/'apps/api/parsing.py',ROOT/'evals/judges/objective.py',ROOT/'evals/judges/evidence.py']}
 for key in ('product','fixture_transport'):
  report[key]['judgments']=[judge(gold['checkpoints'][c['stage']],c['output'],index,{'records':task['events'][c['stage']]['prices'],'as_of':task['as_of']}) for c in report[key]['checkpoints']]
 output=ROOT/'evals/results';output.mkdir(exist_ok=True);(output/'dynamic-replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'kind':report['kind'],'product':[j['passed'] for j in product['judgments']],'fixture':[j['passed'] for j in fixture['judgments']],'model_status':'not_run'},ensure_ascii=False))
 if not all(j['passed'] for key in ('product','fixture_transport') for j in report[key]['judgments']):raise SystemExit(1)
if __name__=='__main__':main_run()
