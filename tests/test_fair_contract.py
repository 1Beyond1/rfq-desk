from copy import deepcopy
import json,subprocess,sys
from pathlib import Path
import pytest
from apps.api.model_config import ModelSettings
from evals.fair_contract import Meter,StopRun,BeforeSendError,DEFAULT_BUDGET,live_preflight,hash_value
from evals.fair_paths import run_path
from evals.fair_fixture import ProductFixture,BaselineFixture
from evals.compare_dev import load_task,judge_packets
ROOT=Path(__file__).resolve().parents[1]
SETTINGS=ModelSettings('https://fixture.invalid/chat','test-only','fixture-model',False)

def test_same_task_settings_original_hash_and_cumulative_limits(tmp_path):
 task=load_task();a,b=ProductFixture(),BaselineFixture()
 paths=[run_path('product',task,a,dict(DEFAULT_BUDGET),SETTINGS,tmp_path),run_path('baseline',task,b,dict(DEFAULT_BUDGET),SETTINGS,tmp_path)]
 for key in ('task_hash','raw_file_hashes','task_budget','settings','as_of'):
  assert paths[0][key]==paths[1][key]
 assert a.contexts[0]['context']==b.contexts[0]['context']
 for context in a.contexts+b.contexts:
  assert context['model']==SETTINGS.model
  text=json.dumps(context)
  assert 'source_binding' not in text and 'judge' not in text and 'SYN-APPROVE' not in text and '"answers"' not in text
 for p in judge_packets(task,paths):
  assert p['status']=='completed' and [c['output']['export_allowed'] for c in p['checkpoints']]==[True,False,True]
  assert len(p['judgments'])==3 and all(j['passed'] for j in p['judgments'])
  assert p['meter']['calls']>1 and p['meter']['known_tokens']==120*p['meter']['calls']
  assert p['meter']['human_answers']==6 and p['real_requests']==0
 assert paths[0]['meter']['calls']==3 and paths[1]['meter']['calls']==21
 # Limits are task-wide: no reset at the next event.
 for path,transport in [('product',ProductFixture()),('baseline',BaselineFixture())]:
  cfg={**DEFAULT_BUDGET,'max_human':3}
  report=run_path(path,task,transport,cfg,SETTINGS,tmp_path)
  assert report['status']=='human_budget_exhausted' and report['meter']['human_answers']==3
  assert len(report['checkpoints'])==1

@pytest.mark.parametrize('change,status',[({'max_tokens':239},'token_or_cost_budget_exhausted'),({'max_cost':'0.00015'},'token_or_cost_budget_exhausted'),({'max_tools':2},'tool_budget_exhausted'),({'max_calls':1},'call_budget_exhausted')])
def test_both_paths_fail_on_shared_task_budget(tmp_path,change,status):
 for name,transport in [('product',ProductFixture()),('baseline',BaselineFixture())]:
  r=run_path(name,load_task(),transport,{**DEFAULT_BUDGET,**change},SETTINGS,tmp_path)
  assert r['status']==status

class Clock:
 def __init__(self):self.t=0
 def __call__(self):return self.t

class Fault(ProductFixture):
 def __init__(self,usage=None,exception=None,delay=0,clock=None):super().__init__();self.usage=usage;self.exception=exception;self.delay=delay;self.clock=clock;self.attempts=0
 def complete(self,*args,**kwargs):
  self.attempts+=1
  if self.clock:self.clock.t+=self.delay
  if self.exception:raise self.exception
  return {'usage':self.usage}

@pytest.mark.parametrize('usage,status',[(None,'usage_missing'),({},'usage_invalid'),({'prompt_tokens':True,'completion_tokens':20,'total_tokens':21},'usage_invalid'),({'prompt_tokens':-1,'completion_tokens':20,'total_tokens':19},'usage_invalid'),({'prompt_tokens':100,'completion_tokens':20,'total_tokens':121},'usage_invalid')])
def test_usage_failures_never_report_unknown_as_zero(usage,status):
 meter=Meter(dict(DEFAULT_BUDGET))
 with pytest.raises(StopRun,match=status):meter.invoke(Fault(usage),[],SETTINGS.model)
 assert meter.report()['actual_tokens'] is None and meter.report()['usage_unknown_requests']==1

def test_valid_overrun_request_timeout_wallclock_and_retries():
 meter=Meter({**DEFAULT_BUDGET,'max_tokens':150})
 with pytest.raises(StopRun,match='token_or_cost_budget_exhausted'):meter.invoke(Fault({'prompt_tokens':130,'completion_tokens':30,'total_tokens':160}),[],SETTINGS.model)
 assert meter.report()['actual_tokens']==160
 for delay,budget,status in [(31,dict(DEFAULT_BUDGET),'request_timeout'),(181,{**DEFAULT_BUDGET,'request_seconds':200},'wall_time_exhausted')]:
  clock=Clock();meter=Meter(budget,clock)
  with pytest.raises(StopRun,match=status):meter.invoke(Fault({'prompt_tokens':100,'completion_tokens':20,'total_tokens':120},delay=delay,clock=clock),[],SETTINGS.model)
  assert meter.tokens==120
 retry=Fault(exception=BeforeSendError());meter=Meter(dict(DEFAULT_BUDGET))
 with pytest.raises(StopRun,match='retry_budget_exhausted'):meter.invoke(retry,[],SETTINGS.model)
 assert retry.attempts==2 and meter.retries==1 and meter.report()['usage_unknown_requests']==0
 failure=Fault(exception=TimeoutError());meter=Meter(dict(DEFAULT_BUDGET))
 with pytest.raises(StopRun,match='request_failed_usage_unknown'):meter.invoke(failure,[],SETTINGS.model)
 assert failure.attempts==1 and meter.report()['actual_tokens'] is None

@pytest.mark.parametrize('settings,live,reason',[(ModelSettings(),False,'model_not_configured'),(SETTINGS,True,'model_requests_disabled'),(ModelSettings('x','k','m',True),False,'explicit_live_required')])
def test_live_gates_are_zero_request(settings,live,reason):
 gate=live_preflight(load_task(),DEFAULT_BUDGET,settings,live)
 assert reason in gate['reasons'] and gate['real_requests']==0 and not gate['ready']

def test_pricing_budget_freeze_identity_and_data_changes_are_blocked(monkeypatch):
 task=load_task();settings=ModelSettings('endpoint','placeholder','model',True)
 assert 'pricing_or_budget_missing' in live_preflight(task,{**DEFAULT_BUDGET,'input_rate':None},settings,True)['reasons']
 assert 'invalid_budget' in live_preflight(task,{**DEFAULT_BUDGET,'max_tokens':None},settings,True)['reasons']
 gate=live_preflight(task,DEFAULT_BUDGET,settings,True)
 assert 'real_tuning_and_freeze_not_completed' in gate['reasons']
 # In-memory gate-branch fixture only. No real freeze file is generated or persisted.
 freeze={**gate['expected_hashes'],'state':'real_tuning_completed_and_frozen'}
 for key in ('model','endpoint_hash','budget_hash','data_hash','code_hash'):
  bad={**freeze,key:'mismatched'}
  assert 'freeze_mismatch:'+key in live_preflight(task,DEFAULT_BUDGET,settings,True,bad)['reasons']
 changed=deepcopy(task);changed['events'][0]['instruction']='changed public task'
 assert 'freeze_mismatch:data_hash' in live_preflight(changed,DEFAULT_BUDGET,settings,True,freeze)['reasons']
 assert 'freeze_mismatch:model' in live_preflight(task,DEFAULT_BUDGET,ModelSettings('endpoint','placeholder','different-model',True),True,freeze)['reasons']
 assert 'freeze_mismatch:budget_hash' in live_preflight(task,{**DEFAULT_BUDGET,'max_tokens':23999},settings,True,freeze)['reasons']
 matched=live_preflight(task,DEFAULT_BUDGET,settings,True,freeze)
 assert 'provider_pricing_unverified' in matched['reasons'] and 'explicit_spend_authorization_missing' in matched['reasons']
 from evals import fair_contract
 monkeypatch.setattr(fair_contract,'code_hash',lambda:'changed-runtime')
 assert 'freeze_mismatch:code_hash' in live_preflight(task,DEFAULT_BUDGET,settings,True,freeze)['reasons']
 assert not matched['ready'] and 'hostile_code_host_isolation_unverified' in matched['reasons'] and 'provider_token_cost_reservation_unverified' in matched['reasons']

def test_legacy_baseline_cli_and_direct_real_runner_cannot_bypass_live_gate(monkeypatch):
 from evals.baselines.protocol import run
 class Spy:
  real=True
  def complete(self,*args):raise AssertionError('must not issue request')
 r=run(load_task(),Spy(),dict(DEFAULT_BUDGET),settings=SETTINGS)
 assert r['protocol_status']=='blocked_prerequisite' and r['real_requests']==0
 monkeypatch.setenv('RFQ_MODEL_URL','https://never-call.invalid');monkeypatch.setenv('RFQ_MODEL_KEY','test-only');monkeypatch.setenv('RFQ_MODEL_NAME','fake-model');monkeypatch.setenv('RFQ_ENABLE_MODEL_REQUESTS','0')
 r=subprocess.run([sys.executable,'evals/baselines/strong_agent.py','--live'],cwd=ROOT,capture_output=True,text=True)
 assert r.returncode==2 and 'model_requests_disabled' in r.stdout and '"real_requests": 0' in r.stdout
 r=subprocess.run([sys.executable,'evals/compare_dev.py'],cwd=ROOT,capture_output=True,text=True)
 assert r.returncode==2 and 'explicit_live_required' in r.stdout


def test_reservation_actual_usage_and_invalid_response_fail_safely():
 meter=Meter(dict(DEFAULT_BUDGET))
 with pytest.raises(StopRun,match='usage_reservation_violated'):meter.invoke(Fault({'prompt_tokens':101,'completion_tokens':20,'total_tokens':121}),[],SETTINGS.model)
 assert meter.report()['actual_tokens']==121
 class Invalid(ProductFixture):
  def complete(self,*args,**kwargs):return []
 meter=Meter(dict(DEFAULT_BUDGET))
 with pytest.raises(StopRun,match='invalid_response_usage_unknown'):meter.invoke(Invalid(),[],SETTINGS.model)
 assert meter.report()['actual_tokens'] is None


def test_real_transport_never_called_by_either_fixture_path(tmp_path):
 class Never:
  real=True
  def complete(self,*args,**kwargs):raise AssertionError('real request forbidden')
 for name in ('product','baseline'):
  report=run_path(name,load_task(),Never(),dict(DEFAULT_BUDGET),SETTINGS,tmp_path)
  assert report['status']=='blocked_prerequisite' and report['real_requests']==0


def test_task_cannot_carry_judge_contract_into_messages_or_tools(tmp_path):
 for placement in ('event','answer','task'):
  task=load_task()
  if placement=='event':task['events'][0]['source_binding']={'private':'reference'}
  if placement=='answer':task['events'][0]['answers']['review']['authorizations']={'private':'reference'}
  if placement=='task':task['expected']={'rows':[]}
  with pytest.raises(StopRun):run_path('baseline',task,BaselineFixture(),dict(DEFAULT_BUDGET),SETTINGS,tmp_path)
