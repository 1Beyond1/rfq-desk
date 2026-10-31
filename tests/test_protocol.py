from copy import deepcopy
from pathlib import Path
import json
import httpx
import pytest
from evals.baselines.protocol import ToolSession,run
from evals.baselines.fixture_transport import ScriptedTransport

ROOT=Path(__file__).resolve().parents[1]
def config():return json.loads((ROOT/'evals/configs/strong-agent.json').read_text(encoding='utf-8-sig'))
def task():return json.loads((ROOT/'evals/cases/tasks/lifecycle.json').read_text(encoding='utf-8-sig'))

def test_real_python_statements_files_and_denied_access(tmp_path):
    session=ToolSession(task(),tmp_path,config())
    result=session.call('code',{'code':"import pathlib,json\ndef f(xs):\n return sum(x*x for x in xs)\np=pathlib.Path('calc.json')\np.write_text(json.dumps({'n':f(data['xs'])}))\nprint(p.read_text())",'data':{'xs':[2,3]}})
    assert result['status']=='completed',result
    assert '13' in result['stdout']
    for code in (f"print(open({str(ROOT/'evals/gold/lifecycle.json')!r}).read())",'import socket','import subprocess','import os'):
        denied=session.call('code',{'code':code,'data':{}})
        assert denied['status']=='failed' and 'PermissionError' in denied['stdout']
    assert not (session.scratch/'lifecycle.json').exists()

def test_code_timeout_and_output_budget(tmp_path):
    cfg=config();cfg['max_code_seconds']=.2;session=ToolSession(task(),tmp_path,cfg)
    assert session.call('code',{'code':'while True: pass','data':{}})['status']=='timeout'
    session.budget['max_code_seconds']=3
    output=session.call('code',{'code':"print('x'*40000)",'data':{}})
    assert output['status']=='failed' and len(output['stdout'])<=cfg['max_output_bytes']
    written=session.call('code',{'code':"with open('large.bin','wb') as f:\n for i in range(20): f.write(b'x'*100000)",'data':{}})
    assert written['status']=='failed' and 'Scratch write byte budget' in written['stdout']
    assert (session.scratch/'large.bin').stat().st_size<=1048576

def test_answers_are_not_leaked_and_human_budget_enforced(tmp_path):
    cfg=config();cfg['human_answer_budget']=1;session=ToolSession(task(),tmp_path,cfg)
    assert 'SYN-AUTH-1' not in json.dumps(session.state())
    assert session.call('ask',{'key':'approve'})['id']=='SYN-AUTH-1'
    with pytest.raises(ValueError):session.call('ask',{'key':'approve'})
    bad=task();bad['files']=['evals/gold/lifecycle.json']
    with pytest.raises(ValueError):ToolSession(bad,tmp_path,cfg)

def test_paginated_parse_preserves_source_and_tool_budget(tmp_path):
    spec=task();spec['files']=['data/synthetic/demo.eml'];cfg=config();cfg['max_tool_calls']=2
    session=ToolSession(spec,tmp_path,cfg)
    first=session.call('parse',{'index':0,'offset':0,'limit':1})
    second=session.call('parse',{'index':0,'offset':1,'limit':1})
    assert first['row_count']==6 and len(first['rows'])==1
    assert first['rows'][0]['source']['location']!=second['rows'][0]['source']['location']
    with pytest.raises(ValueError):session.call('parse',{'index':0})

def test_full_dynamic_protocol_is_not_a_model_run(tmp_path):
    report=run(task(),ScriptedTransport(),config(),tmp_path)
    assert report['model_status']=='not_run' and report['protocol_status']=='completed'
    assert len(report['checkpoints'])==3 and report['human_interventions']==3
    assert report['code_runs']==3 and all(t['status']=='completed' for t in report['tool_trace'] if t['tool']=='code')
    assert [p['output']['export_allowed'] for p in report['checkpoints']]==[True,False,True]

def test_missing_usage_token_cost_and_retry_budgets(tmp_path):
    class Fake:
        real=False
        def __init__(self,mode):self.mode=mode;self.calls=0
        def complete(self,*args):
            self.calls+=1
            if self.mode=='retry':raise httpx.ConnectError('offline fixture')
            return {'usage':{'total_tokens':100} if self.mode!='missing' else {},'choices':[{'message':{'role':'assistant','content':'{}'}}]}
    for mode,status in [('missing','usage_unavailable'),('token','budget_exhausted'),('cost','budget_exhausted'),('retry','transport_failed')]:
        cfg=config();transport=Fake(mode)
        if mode=='token':cfg['max_tokens']=1
        if mode=='cost':cfg.update(cost_per_million_tokens='1000',max_cost='0.001')
        report=run(task(),transport,cfg,tmp_path)
        assert report['protocol_status']==status
        if mode=='retry':assert report['retries']==1 and transport.calls==2
