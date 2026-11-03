import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import agent, main, semantic
from apps.api.model_config import ModelSettings

MAIL='询价单 RFQ-77，件号 PL-9 数量 2 EA 件状 NE。\n麻烦尽快。'

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',tmp_path/'agent.sqlite')
    monkeypatch.setattr(main,'ROOT',tmp_path)
    (tmp_path/'var/uploads').mkdir(parents=True)
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()

def call(name,**args):return {'id':'c-'+name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}

class Script:
    """Plays the model: each step is a list of tool calls or the final text. Records what the tools returned."""
    def __init__(self,*steps):self.steps=list(steps);self.seen=[];self.tokens=7;self.requests=0
    async def call(self,messages,final,deadline):
        self.seen=messages;self.requests+=1;self.final=final
        step=self.steps.pop(0)
        if isinstance(step,Exception):raise step
        return {'role':'assistant','content':step} if isinstance(step,str) else {'role':'assistant','content':'','tool_calls':step}
    def results(self):return [json.loads(m['content']) for m in self.seen if m['role']=='tool']

class Extractor:
    status='test'
    def __init__(self,fields=None):self.fields=fields;self.calls=0
    async def extract(self,m,b):
        self.calls+=1
        fields=self.fields or {'rfq':'RFQ-77','part':'PL-9','quantity':'2','unit':'EA','condition':'NE'}
        unit=next(u for f in m['files'] for u in f['units'] if all(v in u['text'] for v in fields.values()))
        cite=lambda v:{'value':v,'evidence':{k:unit[k] for k in ('file','sha256','location')}|{'start':unit['text'].index(v),'end':unit['text'].index(v)+len(v),'quote':v}}
        return semantic.AdapterReply({'candidates':[{'fields':{k:cite(v) for k,v in fields.items()}}]},10,1,'real_call','test')

def install(script,extractor=None):
    main.app.dependency_overrides[main.get_agent_session]=lambda:script
    main.app.dependency_overrides[semantic.get_adapter]=lambda:extractor or Extractor()

def open_case(client):return client.post('/api/import',files={'file':('mail.txt',MAIL.encode())}).json()
def say(client,case,message='请处理',**extra):return client.post(f"/api/cases/{case['id']}/agent",json={'message':message,'consent':True,**extra})

def test_a_turn_extracts_prices_and_reports_without_touching_formal_lines(client):
    install(Script([call('extract_candidates')],[call('check_prices',part='PL-9',unit='EA',condition='NE',quantity='2')],'提到 1 行，价表是空的。'))
    case=open_case(client)
    r=say(client,case);assert r.status_code==200,r.text
    body=r.json();turn=body['turn']
    assert turn['reply']=='提到 1 行，价表是空的。' and turn['tools']==['extract_candidates','check_prices']
    assert turn['next_step']=='审阅 1 条候选'
    after=body['case']
    assert after['rows']==[] and after['candidate_batches'][0]['candidates'][0]['status']=='pending'
    assert client.get(f"/api/cases/{case['id']}/agent").json()['turns'][0]['reply']==turn['reply']

def test_no_tool_can_accept_price_approve_or_send():
    names={t['function']['name'] for t in agent.TOOLS}
    assert names=={'get_case_state','read_original','extract_candidates','add_mail_to_case','check_prices','explain_row','draft_clarification','search_rules'}

def test_unknown_tool_changes_nothing(client):
    script=Script([call('approve_case',actor='x')],'做不了。')
    install(script);case=open_case(client)
    body=say(client,case,'批准').json()
    assert script.results()[0]=={'error':'没有这个工具'}
    assert body['case']['revision']==case['revision'] and not any(e['action']=='approve' for e in body['case']['events'])

def test_extracting_twice_reuses_pending_candidates(client):
    extractor=Extractor();script=Script([call('extract_candidates')],[call('extract_candidates')],'好')
    install(script,extractor);say(client,open_case(client))
    assert extractor.calls==1 and script.results()[1]['already_pending'] is True

def test_consent_is_required_for_a_persons_own_material(client):
    install(Script('x'));case=open_case(client)
    r=client.post(f"/api/cases/{case['id']}/agent",json={'message':'处理','consent':False})
    assert r.status_code==422 and '同意' in r.json()['detail']

def test_official_material_is_never_sent(client,tmp_path):
    folder=tmp_path/'data/raw/official-rfq';folder.mkdir(parents=True);(folder/'mail.txt').write_bytes(MAIL.encode())
    script=Script('x');install(script);case=open_case(client)
    r=say(client,case)
    assert r.status_code==422 and '官方' in r.json()['detail'] and script.requests==0

def test_model_off_is_reported_and_other_features_stay(client):
    main.app.dependency_overrides[main.get_agent_session]=lambda:None
    case=open_case(client)
    assert say(client,case).status_code==409
    assert client.post('/api/agent/start',json={'text':MAIL,'consent':True}).status_code==409

def test_start_files_the_mail_and_the_turn_does_not_add_it_again(client):
    script=Script([call('add_mail_to_case')],'好');install(script)
    case=client.post('/api/agent/start',json={'text':MAIL,'consent':True}).json()
    assert client.post('/api/agent/start',json={'text':MAIL}).status_code==422
    say(client,case,MAIL)
    assert 'error' in script.results()[0]

def test_new_mail_is_appended_verbatim_and_a_duplicate_is_refused(client,tmp_path):
    reply='对方回信：询价单 RFQ-77，PL-9 数量改成 5 EA。'
    script=Script([call('add_mail_to_case')],[call('add_mail_to_case')],'好');install(script);case=open_case(client)
    body=say(client,case,reply).json()
    files=list((tmp_path/'var/uploads'/case['id']).glob('邮件-*.txt'))
    assert len(files)==1 and files[0].read_text(encoding='utf-8')==reply
    assert body['case']['revision']==case['revision']+1
    assert 'error' in script.results()[1]

def test_failure_before_anything_happened_is_an_error(client):
    install(Script(agent.ModelUnavailable('模型服务暂时不可用')));case=open_case(client)
    r=say(client,case)
    assert r.status_code==503 and '没有变化' in r.json()['detail']
    assert client.get(f"/api/cases/{case['id']}/agent").json()['turns']==[]

def test_failure_after_extraction_keeps_the_candidates_and_says_so(client):
    install(Script([call('extract_candidates')],agent.ModelUnavailable('模型服务暂时不可用')));case=open_case(client)
    body=say(client,case).json()
    assert body['turn']['degraded'] is True and '1 条候选' in body['turn']['reply']
    assert body['case']['candidate_batches'][0]['candidates'][0]['status']=='pending'

def test_the_last_round_cannot_call_tools(client):
    script=Script(*[[call('search_rules',query='价格')] for _ in range(agent.LIMITS['calls']-1)],'结论');install(script)
    assert say(client,open_case(client)).json()['turn']['reply']=='结论' and script.final is True

def test_malformed_arguments_go_back_to_the_model(client):
    bad={'id':'x','type':'function','function':{'name':'check_prices','arguments':'{不是 json'}}
    script=Script([bad],'好');install(script);say(client,open_case(client))
    assert 'error' in script.results()[0]

PRICE={'part':'PL-9','unit':'EA','condition':'NE','currency':'USD','amount':'12.50','valid_from':'2020-01-01','valid_until':'2099-01-01','lead_time':'7 天','source':'合成','kind':'synthetic'}
def priced(*prices):return {'prices':list(prices)}

def test_prices_are_matched_on_part_unit_and_condition():
    one=agent.check_prices(priced(PRICE),'PL-9','EA','NE','3')
    assert one['verdict']=='有唯一有效价格' and one['subtotal']=='37.50'
    assert '不能直接用' in agent.check_prices(priced(PRICE),'PL-9','EA','OH','3')['verdict']
    assert '多条' in agent.check_prices(priced(PRICE,{**PRICE,'amount':'13'}),'PL-9','EA','NE')['verdict']
    assert '过期' in agent.check_prices(priced({**PRICE,'valid_until':'2021-01-01'}),'PL-9','EA','NE')['verdict']
    assert '没有这个件号' in agent.check_prices(priced(PRICE),'ZZ')['verdict'] and '空' in agent.check_prices(priced(),'ZZ')['verdict']

def base(**rows):return {'id':'c','title':'t','revision':1,'rows':[],'prices':[],'warnings':[],'events':[],**rows}
def row(i,**f):return {'id':i,**{k:'' for k in agent.FIELDS},'rfq':'R1','part':'P1','quantity':'2','unit':'EA','condition':'NE','excluded':False,'resolution':'','revision':1,'approval':None,'raw_fields':{},'sources':[],**f}

def test_clarification_asks_about_gaps_and_conflicts_but_not_prices():
    case=base(rows=[row('a',quantity='2'),row('b',quantity='5'),row('c',part='P2',condition='')])
    text=agent.draft_clarification(case)['draft']
    assert '数量出现了 2 和 5' in text and '件号 P2' in text and '请告知件状' in text and '价格' not in text
    assert agent.draft_clarification(base(rows=[row('a')]))['questions']==[]

def test_clarification_covers_pending_candidates_and_unknown_codes():
    batch={'expected_revision':1,'candidates':[{'status':'pending','fields':{'rfq':'R9','part':'X-1','quantity':'2','unit':'EA','condition':'ZZ'},'unknown_fields':['condition']}]}
    text=agent.draft_clarification(base(candidate_batches=[batch]))['draft']
    assert '“ZZ”' in text and 'R9' in text

def test_next_step_follows_the_queue_order():
    assert agent.next_step(base())=='还没有询价行，先提取候选或人工核查原件'
    assert agent.next_step(base(warnings=['w']))=='核查解析警告'
    assert agent.next_step(base(rows=[row('a')]))=='给 1 行补价格依据'
    assert agent.next_step(base(rows=[row('a')],prices=[{**PRICE,'part':'P1'}]))=='批准当前版本'

def test_session_retries_once_on_busy_and_reports_after(monkeypatch):
    seen=[]
    def handler(request):
        seen.append(request);return httpx.Response(429,json={})
    async def go():
        session=agent.ModelSession(ModelSettings('https://x.invalid/v1/chat/completions','k','m'),transport=httpx.MockTransport(handler))
        import time
        await session.call([],False,time.monotonic()+30)
    monkeypatch.setattr(agent.asyncio,'sleep',lambda s:_none())
    with pytest.raises(agent.ModelUnavailable):agent.asyncio.run(go())
    assert len(seen)==2

async def _none():return None

def test_session_sends_tools_and_forbids_them_on_the_last_round():
    bodies=[]
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'好'}}],'usage':{'total_tokens':9}})
    async def go():
        session=agent.ModelSession(ModelSettings('https://x.invalid/v1/chat/completions','k','m'),transport=httpx.MockTransport(handler))
        import time
        answer=await session.call([],True,time.monotonic()+30)
        return answer,session.tokens
    answer,tokens=agent.asyncio.run(go())
    assert answer['content']=='好' and tokens==9 and bodies[0]['tool_choice']=='none' and bodies[0]['tools']

def test_a_reply_answers_what_the_original_left_open():
    def cand(fields,unknown=()):return {'status':'pending','fields':fields,'unknown_fields':list(unknown)}
    batch={'expected_revision':1,'candidates':[cand({'rfq':'R1','part':'A','quantity':'三','unit':'个'},['unit']),cand({'rfq':'R1','part':'A','condition':'NE'}),
                                               cand({'rfq':'R1','part':'B','quantity':'12','unit':'EA','condition':'AR'},['condition']),cand({'rfq':'R1','part':'B','quantity':'15','unit':'EA','condition':'FN'})]}
    assert agent.draft_clarification(base(candidate_batches=[batch]))['questions']==[]

def test_a_long_message_on_a_synthetic_case_still_needs_consent(client,tmp_path):
    install(Script('好'))
    source=Path(__file__).resolve().parents[1]/'data/synthetic/realistic-mail'
    target=tmp_path/'data/synthetic/realistic-mail';target.mkdir(parents=True)
    for f in source.glob('*.eml'):(target/f.name).write_bytes(f.read_bytes())
    case=client.post('/api/semantic-demo/mail-en').json()
    assert client.post(f"/api/cases/{case['id']}/agent",json={'message':'处理这张询价'}).status_code==200
    assert client.post(f"/api/cases/{case['id']}/agent",json={'message':'对方回信：'+'x'*200}).status_code==422

def test_a_reply_cannot_claim_a_draft_that_does_not_exist(client):
    install(Script('提到 1 行。澄清邮件已起草，请确认后发送。'));case=open_case(client)
    assert '更正' in say(client,case).json()['turn']['reply']
    batch_case=client.post('/api/import',files={'file':('b.txt','询价 R1，件号 P1'.encode())}).json()
    script=Script([call('extract_candidates')],'澄清邮件已起草。')
    install(script,Extractor({'rfq':'R1','part':'P1'}))
    turn=say(client,batch_case).json()['turn']
    assert '请告知单位' in turn['draft'] and '更正' not in turn['reply'] and script.results()[0]['clarification_draft_ready'] is True

def test_no_gaps_means_no_draft_and_the_model_is_told(client):
    script=Script([call('extract_candidates')],'提到 1 行。');install(script)
    turn=say(client,open_case(client)).json()['turn']
    assert turn['draft'] is None and script.results()[0]['clarification_draft_ready'] is False

def test_common_unit_words_are_not_questioned_but_unknown_codes_are():
    def cand(unit):return {'status':'pending','fields':{'rfq':'R1','part':'A','quantity':'2','unit':unit,'condition':'NE'},'unknown_fields':['unit']}
    for unit in ('ea','pieces','Units','个'):
        assert agent.draft_clarification(base(candidate_batches=[{'expected_revision':1,'candidates':[cand(unit)]}]))['questions']==[],unit
    assert '“ZZ”' in agent.draft_clarification(base(candidate_batches=[{'expected_revision':1,'candidates':[cand('ZZ')]}]))['draft']

def test_a_chinese_table_is_read_and_an_empty_file_is_refused(client):
    csv='询价号,件号,零件名称,数量,计量单位,件状,特殊要求\nQ-1,ABC-1,阀门,5,EA,NE,含证书\n'.encode()
    case=client.post('/api/import',files={'file':('t.csv',csv)}).json()
    row=case['rows'][0]
    assert (row['rfq'],row['part'],row['description'],row['quantity'],row['unit'],row['condition'],row['requirements'])==('Q-1','ABC-1','阀门','5','EA','NE','含证书')
    r=client.post('/api/import',files={'file':('empty.txt',b'  ')})
    assert r.status_code==422 and '空' in r.json()['detail']

def test_lines_already_formal_are_not_proposed_again(client):
    table='询价号,件号,数量,单位,件状\nRFQ-77,PL-9,2,EA,NE\n'.encode()
    case=client.post('/api/import',files={'file':('t.csv',table)}).json()
    assert len(case['rows'])==1
    script=Script([call('extract_candidates')],'已经是正式行。');install(script)
    body=say(client,case).json()
    assert '已经是正式询价行' in script.results()[0]['status'] and not body['case'].get('candidate_batches')

def test_attachments_and_spreadsheets_reach_the_model(client):
    from io import BytesIO
    from email.message import EmailMessage
    import openpyxl
    book=openpyxl.Workbook();book.active.append(['P/N',"Qty Req'd"]);book.active.append(['MS-1',5]);data=BytesIO();book.save(data)
    msg=EmailMessage();msg.set_content('见附件');msg.add_attachment(data.getvalue(),maintype='application',subtype='octet-stream',filename='list.xlsx')
    case=client.post('/api/import',files={'file':('m.eml',msg.as_bytes())}).json()
    units=[u for f in client.get(f"/api/cases/{case['id']}/materials").json()['files'] for u in f['units']]
    assert any(u['file']=='m.eml > list.xlsx' and u['text']=='MS-1\t5' for u in units)

def test_progress_shows_the_steps_of_a_running_turn_and_clears_after():
    seen=[]
    async def go():
        class Box:
            def case(self):return {'id':'c','title':'t','revision':1,'rows':[],'prices':[],'warnings':[],'events':[]}
        script=Script([call('search_rules',query='价格')],'好')
        await agent.run_turn(Box(),'问',[],script,on_step=seen.append)
    agent.asyncio.run(go())
    assert seen==['search_rules']

def test_progress_route_is_empty_when_nothing_runs(client):
    case=open_case(client)
    assert client.get(f"/api/cases/{case['id']}/agent/progress").json()=={'steps':None}
