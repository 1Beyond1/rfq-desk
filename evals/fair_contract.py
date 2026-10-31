"""Shared DEV task contract and cumulative accounting; no live readiness is manufactured."""
from dataclasses import dataclass
from decimal import Decimal,InvalidOperation
from pathlib import Path
import hashlib,json,time
from apps.api.model_config import ModelSettings
ROOT=Path(__file__).resolve().parents[1]
def hash_value(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
class StopRun(ValueError):
 def __init__(self,status):self.status=status;super().__init__(status)
class BeforeSendError(Exception):pass

def code_hash():
 files=['evals/fair_contract.py','evals/fair_paths.py','evals/baselines/protocol.py','apps/api/semantic.py','apps/api/materials.py','apps/api/domain.py','apps/api/model_config.py','evals/baselines/code_worker.py','evals/baselines/windows_job.py','evals/judges/evidence.py','evals/judges/objective.py','evals/compare_dev.py']
 return hash_value({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files if (ROOT/p).exists()})

def validate_budget(b):
 for key in ('max_tokens','max_calls','max_tools','max_human','max_retries'):
  if type(b.get(key)) is not int or b[key]<0:raise StopRun('invalid_budget')
 if not b['max_tokens'] or not b['max_calls'] or not b['max_tools']:raise StopRun('invalid_budget')
 for key in ('max_seconds','request_seconds'):
  if type(b.get(key)) not in (int,float) or not 0<b[key]<100000:raise StopRun('invalid_budget')
 try:
  values=[Decimal(str(b[k])) for k in ('max_cost','input_rate','output_rate')]
  if any(not n.is_finite() or n<0 for n in values) or values[0]<=0:raise ValueError()
 except (KeyError,InvalidOperation,ValueError):raise StopRun('pricing_or_budget_missing')

def manifest(task):
 if set(task)-{'id','split','family','lineage','title','as_of','files','rules','events'}:raise StopRun('task_private_fields_not_allowed')
 def private_keys(value):
  if isinstance(value,dict):return any(k in {'source_binding','gold','expected','authorizations','judge_only'} or private_keys(v) for k,v in value.items())
  if isinstance(value,list):return any(private_keys(v) for v in value)
  return False
 if private_keys(task):raise StopRun('judge_data_not_allowed_in_task')
 for event in task.get('events',[]):
  if not isinstance(event,dict) or set(event)-{'id','price_version','prices','instruction','answers'}:raise StopRun('event_private_fields_not_allowed')
 if task.get('split')!='dev' or task.get('id')!='FAIR-DEV-01':raise StopRun('dev_task_not_allowed')
 allowed={'data/synthetic/fair-dev/request.eml'}
 if set(task.get('files',[]))!=allowed:raise StopRun('dev_files_not_allowed')
 return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in task['files']}

def live_preflight(task,budget,settings,live=False,freeze=None):
 reasons=[]
 if not live:reasons.append('explicit_live_required')
 if not settings.configured:reasons.append('model_not_configured')
 if not settings.enabled:reasons.append('model_requests_disabled')
 if budget.get('pricing_kind')!='provider_verified':reasons.append('provider_pricing_unverified')
 if budget.get('spend_authorized') is not True:reasons.append('explicit_spend_authorization_missing')
 try:validate_budget(budget)
 except StopRun as e:reasons.append(e.status)
 try:data_hash=hash_value({'task':task,'files':manifest(task)})
 except StopRun as e:reasons.append(e.status);data_hash=None
 expected={'model':settings.model,'endpoint_hash':hash_value(settings.endpoint),'budget_hash':hash_value(budget),'data_hash':data_hash,'code_hash':code_hash()}
 if not isinstance(freeze,dict) or freeze.get('state')!='real_tuning_completed_and_frozen':reasons.append('real_tuning_and_freeze_not_completed')
 else:
  for k,v in expected.items():
   if freeze.get(k)!=v:reasons.append('freeze_mismatch:'+k)
 # Current host remains a cooperative audit environment; neither flag nor fixture can release it.
 reasons+=['hostile_code_host_isolation_unverified','provider_token_cost_reservation_unverified']
 return {'status':'blocked_prerequisite','ready':False,'reasons':reasons,'expected_hashes':expected,'real_requests':0,'model_status':'not_run'}

class Meter:
 def __init__(self,budget,clock=time.monotonic):
  validate_budget(budget);self.b=dict(budget);self.clock=clock;self.start=clock();self.calls=0;self.tools=0;self.human=0;self.retries=0;self.tokens=0;self.cost=Decimal(0);self.unknown=0;self.trace=[];self._terminal_reason=None
 @property
 def terminal_reason(self):return self._terminal_reason
 def _active(self):
  if self._terminal_reason is not None:raise StopRun(self._terminal_reason)
 def _fail(self,status):
  if self._terminal_reason is None:self._terminal_reason=status
  raise StopRun(self._terminal_reason)
 def remaining(self):
  self._active()
  left=self.b['max_seconds']-(self.clock()-self.start)
  if left<=0:self._fail('wall_time_exhausted')
  return left
 def tool(self,human=False):
  self._active()
  self.remaining()
  if self.tools>=self.b['max_tools']:self._fail('tool_budget_exhausted')
  if human and self.human>=self.b['max_human']:self._fail('human_budget_exhausted')
  self.tools+=1;self.human+=bool(human)
 def invoke(self,transport,messages,model):
  self._active()
  while True:
   left=self.remaining()
   if self.calls>=self.b['max_calls']:self._fail('call_budget_exhausted')
   if not hasattr(transport,'reserve_usage'):self._fail('provider_reservation_unverified')
   try:reserved=transport.reserve_usage(messages)
   except Exception:self._fail('reservation_failed_before_send')
   self._usage(reserved,check_only=True)
   self.calls+=1
   call_start=self.clock()
   try:response=transport.complete(messages,model=model,timeout=min(left,self.b['request_seconds']))
   except BeforeSendError:
    if self.retries>=self.b['max_retries']:self._fail('retry_budget_exhausted')
    self.retries+=1;continue
   except Exception:
    self.unknown+=1;self._fail('request_failed_usage_unknown')
   if not isinstance(response,dict):self.unknown+=1;self._fail('invalid_response_usage_unknown')
   try:self._usage(response.get('usage'))
   except StopRun as exc:
    if exc.status in ('usage_missing','usage_invalid'):self.unknown+=1
    raise
   if any(response['usage'][k]>reserved[k] for k in ('prompt_tokens','completion_tokens')):self._fail('usage_reservation_violated')
   self.remaining()
   if self.clock()-call_start>min(left,self.b['request_seconds']):self._fail('request_timeout')
   return response
 def _usage(self,usage,check_only=False):
  self._active()
  if not isinstance(usage,dict):self._fail('usage_missing')
  keys=('prompt_tokens','completion_tokens','total_tokens')
  if any(type(usage.get(k)) is not int or usage[k]<0 for k in keys) or usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens']:self._fail('usage_invalid')
  n=usage['total_tokens'];cost=(Decimal(usage['prompt_tokens'])*Decimal(str(self.b['input_rate']))+Decimal(usage['completion_tokens'])*Decimal(str(self.b['output_rate'])))/Decimal(1000000)
  exceeded=self.tokens+n>self.b['max_tokens'] or self.cost+cost>Decimal(str(self.b['max_cost']))
  if not check_only:self.tokens+=n;self.cost+=cost;self.trace.append(dict(usage))
  if exceeded:self._fail('token_or_cost_budget_exhausted')
 def report(self):
  return {'terminated':self._terminal_reason is not None,'terminal_reason':self._terminal_reason,'calls':self.calls,'tools':self.tools,'human_answers':self.human,'retries':self.retries,'known_tokens':self.tokens,'actual_tokens':None if self.unknown else self.tokens,'known_fixture_cost':str(self.cost),'actual_cost':None,'usage_unknown_requests':self.unknown,'elapsed_seconds':self.clock()-self.start,'usage_trace':[dict(entry) for entry in self.trace]}

DEFAULT_BUDGET={'max_tokens':24000,'max_cost':'1.00','input_rate':'1.00','output_rate':'2.00','max_seconds':180,'request_seconds':30,'max_calls':32,'max_tools':60,'max_human':8,'max_retries':1,'pricing_kind':'synthetic_fixture_only'}
