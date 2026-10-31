"""Engineering validation report only; no model, reserved packs or gold is loaded."""
from pathlib import Path
import hashlib,json,subprocess,sys,time,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'evals/results';out.mkdir(exist_ok=True)
start=time.monotonic();r=subprocess.run([sys.executable,'-m','pytest','tests/test_semantic.py','-q','--junitxml='+str(out/'semantic-validation.xml')],cwd=ROOT,capture_output=True,text=True)
suites=ET.parse(out/'semantic-validation.xml').getroot();suite=suites.find('testsuite')
report={'kind':'semantic-engineering-regression-not-model-comparison','model_status':'not_run','source':'two authored synthetic development formats, not independent customers','tests':int(suite.attrib['tests']),'failures':int(suite.attrib['failures']),'errors':int(suite.attrib['errors']),'elapsed_seconds':time.monotonic()-start,'code_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['apps/api/semantic.py','apps/api/materials.py','tests/test_semantic.py','evals/judges/evidence.py','evals/judges/objective.py']},'reserved_used':False}
(out/'semantic-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report));raise SystemExit(r.returncode)
