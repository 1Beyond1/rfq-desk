"""Functional checks only. Not a model benchmark or a heldout experiment."""
import sys,json,time,copy,hashlib,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apps.api.domain import new_case,replace_prices,analyze,approve,export_data
from apps.api.parsing import parse_file
ROOT=Path(__file__).resolve().parents[1]
start=time.monotonic();results=[]
parsed=parse_file('demo.eml',(ROOT/'data/synthetic/demo.eml').read_bytes())
c=new_case('offline-synthetic',parsed);replace_prices(c,json.loads((ROOT/'data/synthetic/prices.json').read_text(encoding='utf-8')))
r=analyze(c)
results.append({'case':'same_part_different_rfq','passed':not r[0]['duplicate']})
results.append({'case':'exact_duplicate','passed':r[1]['duplicate'] and r[2]['duplicate']})
results.append({'case':'quantity_conflict','passed':r[3]['conflict'] and r[4]['conflict']})
results.append({'case':'missing_price','passed':r[5]['price'] is None and bool(r[5]['issues'])})
c['rows'][2]['excluded']=True;c['rows'][4]['excluded']=True;c['rows'][5]['excluded']=True
approve(c,'offline-test');results.append({'case':'decimal_total','passed':export_data(c)['rows'][0]['total']=='98.80'})
p=copy.deepcopy(c['prices']);p[1]['amount']='49.00';affected=replace_prices(c,p)
results.append({'case':'only_relevant_approvals_invalidated','passed':len(affected)==2 and analyze(c)[0]['approved'] and analyze(c)[3]['stale']})
try:export_data(c);blocked=False
except ValueError:blocked=True
results.append({'case':'stale_export_blocked','passed':blocked})
p[0]['valid_until']='2020-01-01';p[0]['valid_from']='2019-01-01';replace_prices(c,p)
results.append({'case':'expired_price','passed':analyze(c)[0]['price'] is None})
report={'kind':'offline-functional-not-agent-comparison','cases':results,'passed':sum(r['passed'] for r in results),'count':len(results),'duration_seconds':time.monotonic()-start,'data_hash':hashlib.sha256((ROOT/'data/synthetic/demo.eml').read_bytes()).hexdigest(),'model':None,'tokens':0,'cost':0,'human_interventions':'scripted exclusions in fixture; not user trial','heldout':False}
out=ROOT/'evals/results';out.mkdir(exist_ok=True);(out/'offline-functional.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if not all(r['passed'] for r in results):raise SystemExit(1)
