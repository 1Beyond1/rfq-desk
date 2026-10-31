"""In-memory source-binding probes; no product pipeline, reserved or gold inputs."""
from pathlib import Path
import runpy,json,hashlib,time,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
helpers=runpy.run_path(str(ROOT/'tests/test_literal_binding.py'))
index=helpers['probe'](helpers['BODY']);normal=helpers['row'](index);expected=helpers['gold'](normal)
cases={}
from copy import deepcopy
for label,line in [('normal',None),('priority_as_quantity',6),('other_request_as_quantity',9)]:
 row=deepcopy(normal)
 if line:row['sources'][2]=helpers['citation'](index,line,'quantity','3')
 cases[label]=helpers['score'](index,row,expected)
checks=[]
for name,fn in helpers.items():
 if name.startswith('test_'):
  start=time.monotonic();fn();checks.append({'name':name,'passed':True,'seconds':time.monotonic()-start})
report={'kind':'independent-judge-binding-repair-not-model-performance','model_status':'not_run','reserved_used':False,'exact_probes':cases,'regression_checks':checks,'code_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['evals/judges/evidence.py','evals/judges/objective.py','tests/test_literal_binding.py']}}
out=ROOT/'evals/results';out.mkdir(exist_ok=True);(out/'literal-binding-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'exact_probes':{k:{'passed':v['passed'],'verified_source_fields':v['verified_source_fields'],'unsupported_fields':v['unsupported_fields']} for k,v in cases.items()},'checks':len(checks),'model_status':'not_run'}))
assert cases['normal']['passed'] and not cases['priority_as_quantity']['passed'] and not cases['other_request_as_quantity']['passed']
