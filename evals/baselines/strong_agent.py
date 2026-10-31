"""Independent Agent CLI. Deterministic mode tests protocol, never model quality."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from evals.baselines.protocol import run,HTTPTransport
from apps.api.model_config import ModelSettings
from evals.baselines.fixture_transport import ScriptedTransport

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--dry-run',action='store_true');parser.add_argument('--live',action='store_true');parser.add_argument('--task',default='evals/cases/tasks/lifecycle.json');args=parser.parse_args()
 path=(ROOT/args.task).resolve()
 if not path.is_relative_to(ROOT/'evals/cases/tasks'):raise SystemExit('Reserved/gold tasks are not released to this development runner')
 task=json.loads(path.read_text(encoding='utf-8-sig'));config=json.loads((ROOT/'evals/configs/strong-agent.json').read_text(encoding='utf-8-sig'))
 if args.dry_run:transport=ScriptedTransport()
 else:
  from evals.fair_contract import live_preflight
  gate=live_preflight(task,config,ModelSettings.from_env(),args.live,None)
  print(json.dumps({'kind':'readiness-only','model_status':'not_run','real_requests':0,'preflight':gate}))
  raise SystemExit(2)
 report=run(task,transport,config)
 folder=ROOT/'evals/results';folder.mkdir(exist_ok=True)
 output=folder/('protocol-fixture.json' if args.dry_run else 'strong-agent-local.json');output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:report[k] for k in ('kind','model_status','protocol_status','turns','tool_calls','code_runs','human_interventions')},ensure_ascii=False))
 if report['protocol_status']!='completed':raise SystemExit(1)
if __name__=='__main__':main()
