"""Meter terminal-state probes; no task data, secrets, gold or network used."""
from copy import deepcopy
import pytest
from evals.fair_contract import Meter,DEFAULT_BUDGET,StopRun,BeforeSendError

RESERVED={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}
SMALL={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}
class Transport:
 real=False
 def __init__(self,responses):self.responses=iter(responses);self.calls=0;self.reservations=0
 def reserve_usage(self,messages):self.reservations+=1;return dict(RESERVED)
 def complete(self,*args,**kwargs):
  self.calls+=1;response=next(self.responses)
  if isinstance(response,Exception):raise response
  return response

def stable_report(meter):return {k:v for k,v in meter.report().items() if k!='elapsed_seconds'}

def assert_latched(meter,transport,reason):
 before=deepcopy(stable_report(meter));counts=(transport.calls,transport.reservations)
 for action in (lambda:meter.invoke(transport,[],'fixture-only'),lambda:meter.tool(),lambda:meter.tool(human=True),lambda:meter.remaining(),lambda:meter._usage(SMALL)):
  with pytest.raises(StopRun) as exc:action()
  assert exc.value.status==reason
  assert stable_report(meter)==before and (transport.calls,transport.reservations)==counts
 assert meter.terminal_reason==reason
 assert meter.report()['terminated']
 with pytest.raises(AttributeError):meter.terminal_reason=None


def test_coordinator_exact_missing_usage_then_known_usage_transport_only_once():
 transport=Transport([{'usage':None},{'usage':dict(SMALL)}]);meter=Meter(dict(DEFAULT_BUDGET))
 with pytest.raises(StopRun,match='usage_missing'):meter.invoke(transport,[],'fixture-only')
 assert_latched(meter,transport,'usage_missing')
 assert transport.calls==1 and meter.unknown==1
 assert meter.report()['actual_tokens'] is None and meter.report()['known_tokens']==0

@pytest.mark.parametrize('response,reason',[
 ({'usage':{}},'usage_invalid'),
 ({'usage':{'prompt_tokens':True,'completion_tokens':20,'total_tokens':21}},'usage_invalid'),
 (TimeoutError('fixture after-send unknown'),'request_failed_usage_unknown'),
 ([], 'invalid_response_usage_unknown'),
 ({'usage':{'prompt_tokens':101,'completion_tokens':20,'total_tokens':121}},'usage_reservation_violated'),
])
def test_response_failures_are_terminal_for_all_meter_operations(response,reason):
 meter=Meter(dict(DEFAULT_BUDGET));transport=Transport([response,{'usage':SMALL}])
 with pytest.raises(StopRun,match=reason):meter.invoke(transport,[],'fixture-only')
 assert_latched(meter,transport,reason)
 assert transport.calls==1
 if reason=='usage_reservation_violated':assert meter.report()['actual_tokens']==121
 else:assert meter.report()['actual_tokens'] is None

@pytest.mark.parametrize('change,reason',[
 ({'max_tokens':119},'token_or_cost_budget_exhausted'),
 ({'max_cost':'0.00001'},'token_or_cost_budget_exhausted'),
 ({'max_calls':1},'call_budget_exhausted'),
 ({'max_tools':1},'tool_budget_exhausted'),
 ({'max_human':0},'human_budget_exhausted'),
])
def test_task_budget_termination_cannot_be_reentered(change,reason):
 meter=Meter({**DEFAULT_BUDGET,**change});transport=Transport([{'usage':SMALL},{'usage':SMALL}])
 if 'max_calls' in change:meter.invoke(transport,[],'fixture-only')
 if 'max_tools' in change:meter.tool()
 with pytest.raises(StopRun,match=reason):
  if 'max_tools' in change:meter.tool()
  elif 'max_human' in change:meter.tool(human=True)
  else:meter.invoke(transport,[],'fixture-only')
 assert_latched(meter,transport,reason)


def test_actual_overbudget_records_known_usage_then_latches():
 meter=Meter({**DEFAULT_BUDGET,'max_tokens':150})
 transport=Transport([{'usage':{'prompt_tokens':130,'completion_tokens':30,'total_tokens':160}},{'usage':SMALL}])
 with pytest.raises(StopRun):meter.invoke(transport,[],'fixture-only')
 assert_latched(meter,transport,'token_or_cost_budget_exhausted')
 assert meter.report()['actual_tokens']==160 and meter.report()['known_tokens']==160

class Clock:
 def __init__(self):self.time=0
 def __call__(self):return self.time

@pytest.mark.parametrize('delay,reason',[(31,'request_timeout'),(181,'wall_time_exhausted')])
def test_time_termination_preserves_first_reason_after_clock_changes(delay,reason):
 clock=Clock();meter=Meter(dict(DEFAULT_BUDGET),clock)
 class Delayed(Transport):
  def complete(self,*args,**kwargs):clock.time+=delay;return super().complete(*args,**kwargs)
 transport=Delayed([{'usage':SMALL},{'usage':SMALL}])
 with pytest.raises(StopRun,match=reason):meter.invoke(transport,[],'fixture-only')
 clock.time=0 # Even a test clock rollback cannot revive a terminated task.
 assert_latched(meter,transport,reason)
 assert meter.report()['known_tokens']==15


def test_safe_before_send_retry_and_successful_multi_event_accumulation():
 meter=Meter(dict(DEFAULT_BUDGET))
 transport=Transport([BeforeSendError(),{'usage':SMALL},{'usage':SMALL},{'usage':SMALL}])
 for event in range(3):
  meter.tool(human=True);meter.invoke(transport,[{'event':event}],'fixture-only')
 assert meter.report()['terminal_reason'] is None and not meter.report()['terminated']
 assert meter.calls==4 and transport.calls==4 and meter.retries==1 and meter.tokens==45
 assert meter.human==3 and meter.tools==3 and meter.unknown==0
 report=meter.report();report['usage_trace'].clear()
 assert len(meter.report()['usage_trace'])==3


def test_retry_exhaustion_is_terminal_without_unknown_usage():
 meter=Meter(dict(DEFAULT_BUDGET));transport=Transport([BeforeSendError(),BeforeSendError(),{'usage':SMALL}])
 with pytest.raises(StopRun,match='retry_budget_exhausted'):meter.invoke(transport,[],'fixture-only')
 assert_latched(meter,transport,'retry_budget_exhausted')
 assert transport.calls==2 and meter.unknown==0


def test_known_usage_before_unknown_failure_is_retained():
 meter=Meter(dict(DEFAULT_BUDGET));transport=Transport([{'usage':SMALL},{'usage':None},{'usage':SMALL}])
 meter.invoke(transport,[],'fixture-only')
 with pytest.raises(StopRun):meter.invoke(transport,[],'fixture-only')
 assert_latched(meter,transport,'usage_missing')
 assert meter.report()['known_tokens']==15 and meter.report()['actual_tokens'] is None


def test_reservation_failure_latches_before_transport():
 meter=Meter(dict(DEFAULT_BUDGET))
 class BadReservation(Transport):
  def reserve_usage(self,messages):self.reservations+=1;raise ValueError('fixture invalid reservation')
 transport=BadReservation([{'usage':SMALL}])
 with pytest.raises(StopRun,match='reservation_failed_before_send'):meter.invoke(transport,[],'fixture-only')
 assert_latched(meter,transport,'reservation_failed_before_send')
 assert transport.calls==0 and meter.calls==0 and meter.unknown==0
