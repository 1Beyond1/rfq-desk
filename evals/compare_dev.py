"""DEV fixture connectivity and readiness only. This cannot release live comparison."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from apps.api.model_config import ModelSettings
from evals.fair_contract import DEFAULT_BUDGET,live_preflight,manifest,hash_value
from evals.fair_paths import run_path
from evals.fair_fixture import ProductFixture,BaselineFixture
from evals.judges.evidence import EvidenceIndex
from evals.judges.objective import judge

def load_task():return json.loads((ROOT/'evals/cases/tasks/fair-dev.json').read_text(encoding='utf-8'))

def judge_packets(task,packets):
 # Judge-only binding and expected result generated after both runners return. Never passed to transport/tools.
 index=EvidenceIndex()
 for f in task['files']:
  p=ROOT/f;index.add(p.name,p.read_bytes())
 binding=next(iter(index.bindings.values()))['binding']
 for packet in packets:
  packet['judgments']=[]
  for checkpoint in packet['checkpoints']:
   e=task['events'][checkpoint['stage']];ready=bool(e['prices'])
   expected={'rows':[{'rfq':'000501','part':'FAIR-001','quantity':'3','unit':'EA','condition':'FN','status':'ready' if ready else 'unpriced','source_required':True,'source_binding':binding,'total':str(__import__('decimal').Decimal('3')*__import__('decimal').Decimal(e['prices'][0]['amount'])) if ready else None,'forbid_total':not ready,'approval':{'answer_id':e['answers']['approve']['id'],'price_version':e['price_version']} if ready else {}}],'export_allowed':ready,'approval_snapshot':hash_value(e['prices']) if ready else None}
   packet['judgments'].append(judge(expected,checkpoint['output'],index,{'records':e['prices'],'as_of':task['as_of']}))
 return packets

def fixture_run(workspace=None):
 task=load_task();settings=ModelSettings('https://fixture.invalid/chat','fixture-placeholder','fixture-model',False)
 packets=[run_path('product',task,ProductFixture(),dict(DEFAULT_BUDGET),settings,workspace),run_path('baseline',task,BaselineFixture(),dict(DEFAULT_BUDGET),settings,workspace)]
 judge_packets(task,packets)
 return {'kind':'fixture-connectivity-and-readiness-not-performance','model_status':'not_run','task_id':task['id'],'reserved_used':False,'readiness':live_preflight(task,DEFAULT_BUDGET,ModelSettings.from_env()),'paths':packets,'freeze_created':False}

def main():
 parser=argparse.ArgumentParser();modes=parser.add_mutually_exclusive_group();modes.add_argument('--fixture',action='store_true');modes.add_argument('--live',action='store_true');args=parser.parse_args()
 if not args.fixture:
  report=live_preflight(load_task(),DEFAULT_BUDGET,ModelSettings.from_env(),args.live,None);print(json.dumps(report));raise SystemExit(2)
 report=fixture_run();out=ROOT/'evals/results';out.mkdir(exist_ok=True);(out/'fair-dev-connectivity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'kind':report['kind'],'model_status':report['model_status'],'paths':[{ 'path':p['path'],'status':p['status'],'tokens':p['meter']['known_tokens'],'tools':p['meter']['tools'],'human':p['meter']['human_answers'],'judgments':[j['passed'] for j in p['judgments']]} for p in report['paths']],'live_ready':report['readiness']['ready']}))
 if any(p['status']!='completed' or len(p['judgments'])!=3 or not all(j['passed'] for j in p['judgments']) for p in report['paths']):raise SystemExit(1)
if __name__=='__main__':main()
