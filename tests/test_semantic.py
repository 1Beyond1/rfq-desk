from pathlib import Path
from copy import deepcopy
import asyncio
import pytest
from fastapi.testclient import TestClient
from apps.api import main,semantic
from apps.api.materials import read_materials
from evals.judges.evidence import EvidenceIndex
from evals.judges.objective import judge
ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture
def client(tmp_path,monkeypatch):
 monkeypatch.setattr(main,'DB',tmp_path/'semantic.sqlite')
 yield TestClient(main.app)
 main.app.dependency_overrides.clear()
def create(c,name='prose'):return c.post('/api/semantic-demo/'+name).json()
def propose(c,case,mode='offline'):
 return c.post(f"/api/cases/{case['id']}/candidates/propose",json={'revision':case['revision'],'values':{'mode':mode}})
def accept(c,case,index=0,**extra):
 b=case['candidate_batches'][-1];r=b['candidates'][index]
 return c.post(f"/api/cases/{case['id']}/candidates/{b['id']}/{r['id']}/review",json={'revision':case['revision'],'values':{'action':'accept','actor':'synthetic reviewer','reason':'Synthetic explicitly reviewed request/version','confirm_association':True,**extra}})
class FixtureAdapter:
 status='test_dependency'
 def __init__(self,change=lambda p:p,tokens=10):self.change=change;self.tokens=tokens;self.calls=0
 async def extract(self,m,b):
  self.calls+=1
  return semantic.AdapterReply(self.change(semantic.offline_extract(m)),self.tokens,0,'not_run','test_dependency')

def test_no_configuration_zero_requests(client,monkeypatch):
 for k in ('RFQ_MODEL_URL','RFQ_MODEL_KEY','RFQ_MODEL_NAME','RFQ_ENABLE_MODEL_REQUESTS'):monkeypatch.delenv(k,raising=False)
 c=create(client);r=propose(client,c,'model').json()
 assert r['extraction']['status']=='not_configured' and r['extraction']['requests']==0
 assert r['case']['rows']==[] and r['case']['revision']==c['revision']

def test_two_formats_are_candidates_not_rows(client):
 for name,count in [('prose',1),('revision',2)]:
  c=create(client,name);r=propose(client,c).json();c=r['case']
  assert c['rows']==[] and len(c['candidate_batches'][-1]['candidates'])==count
  assert r['extraction']['model_status']=='not_run'

def test_adversarial_model_payloads_are_atomic(client):
 def bad(mode):
  def edit(p):
   f=p['candidates'][0]['fields']
   if mode=='hash':f['quantity']['evidence']['sha256']='0'*64
   if mode=='file':f['quantity']['evidence']['file']='other.eml'
   if mode=='location':f['quantity']['evidence']['location']='page 9 / line 1'
   if mode=='span':f['quantity']['evidence']['end']=9999
   if mode=='unsupported':f['quantity']['value']='999'
   if mode=='type':f['quantity']['value']=3
   if mode=='wrong-field':f['quantity']=deepcopy(f['unit'])
   if mode=='price':f['price']={'value':'100','evidence':{}}
   if mode=='malformed':return []
   return p
  return edit
 for mode in ('hash','file','location','span','unsupported','type','price','malformed','wrong-field'):
  c=create(client);fixture=FixtureAdapter(bad(mode));main.app.dependency_overrides[semantic.get_adapter]=lambda:fixture
  r=propose(client,c,'model');assert r.status_code==422,(mode,r.text)
  stored=client.get('/api/cases/'+c['id']).json();assert not stored.get('candidate_batches') and stored['rows']==[] and stored['revision']==c['revision']

def test_cross_revision_splicing_rejected(client):
 def splice(p):p['candidates'][0]['fields']['quantity']=p['candidates'][1]['fields']['quantity'];return p
 fixture=FixtureAdapter(splice);main.app.dependency_overrides[semantic.get_adapter]=lambda:fixture
 r=propose(client,create(client,'revision'),'model');assert r.status_code==200
 batch=r.json()['case']['candidate_batches'][-1]
 assert len(batch['candidates'])==1 and batch['metrics']['rejected_candidates']==1 and r.json()['extraction']['rejected_candidates']==1

@pytest.mark.parametrize('value',['','0','-1','NaN','1e99999'])
def test_invalid_corrected_quantity_cannot_enter_formal_rows(client,value):
 c=propose(client,create(client)).json()['case'];r=accept(client,c,fields={'quantity':value})
 assert r.status_code==422 and client.get('/api/cases/'+c['id']).json()['rows']==[]

def test_manual_adjudication_independent_ledger(client):
 c=propose(client,create(client)).json()['case'];r=accept(client,c,fields={'quantity':'6'});assert r.status_code==200,r.text
 c=r.json();row=c['rows'][0];p=ROOT/'data/synthetic/semantic/prose-cn.eml';index=EvidenceIndex();index.add(p.name,p.read_bytes())
 assert not index.verify('quantity','6',row['sources'])['supported']
 assert not index.verify_claim(row,'quantity',{})['supported']
 auth={d['id']:d for d in c['human_decisions']};claim=index.verify_claim(row,'quantity',auth)
 assert claim['supported'] and claim['kind']=='human'
 gold={'rows':[{'rfq':'000301','part':'SEM-101','quantity':'6','status':'unpriced','source_required':True,'evidence_modes':{'quantity':'human'}}],'export_allowed':False}
 actual={'rows':[{**row,'status':'unpriced'}],'export_allowed':False}
 assert judge(gold,actual,index,authorizations=auth)['passed']
 assert not judge(gold,actual,index)['passed']

def test_explicit_association_and_target_reassignment(client):
 c=propose(client,create(client)).json()['case'];assert accept(client,c,confirm_association=False).status_code==422
 c=accept(client,c).json();row=c['rows'][0]
 c=propose(client,c).json()['case']
 assert accept(client,c,target_row_id=row['id'],fields={'rfq':'DIFFERENT'}).status_code==422
 assert accept(client,c,target_row_id='other-case-row').status_code==422
 assert accept(client,c,target_row_id=row['id'],fields={'rfq':'DIFFERENT'},confirm_reassignment=True).status_code==200

def test_stale_revision_batch_and_changed_original(client):
 c=propose(client,create(client)).json()['case'];old=deepcopy(c)
 newer=client.post(f"/api/cases/{c['id']}/review",json={'revision':c['revision'],'values':{'note':'synthetic review'}}).json()
 assert accept(client,old).status_code==409
 assert accept(client,newer).status_code==422
 c=propose(client,newer).json()['case'];p=ROOT/'var/uploads'/c['id']/'prose-cn.eml';original=p.read_bytes()
 try:
  p.write_bytes(original+b'\nchanged')
  assert accept(client,c).status_code==422
 finally:p.write_bytes(original)

def test_unknown_unit_confirmation_is_not_inferred(client):
 c=propose(client,create(client)).json()['case'];c=accept(client,c,fields={'unit':'MYSTERY','condition':'ZZ'}).json()
 assert c['rows'][0]['pending_confirmations']==['unit','condition']
 # Explicit re-review can confirm raw unknown tokens without inventing an expansion.
 c=propose(client,c).json()['case'];r=accept(client,c,target_row_id=c['rows'][0]['id'],fields={'unit':'MYSTERY','condition':'ZZ'},confirmed_fields=['unit','condition'])
 assert r.status_code==200 and r.json()['rows'][0]['pending_confirmations']==[]

def test_timeout_budget_and_remote_material_gate(client,monkeypatch):
 fixture=FixtureAdapter(tokens=semantic.BUDGET['max_tokens']+1);main.app.dependency_overrides[semantic.get_adapter]=lambda:fixture
 assert propose(client,create(client),'model').status_code==422
 class Slow(FixtureAdapter):
  async def extract(self,m,b):await asyncio.sleep(.1)
 fixture=Slow();main.app.dependency_overrides[semantic.get_adapter]=lambda:fixture
 monkeypatch.setitem(semantic.BUDGET,'max_seconds',.01)
 assert propose(client,create(client),'model').status_code==422
 c=client.post('/api/import',files={'file':('unknown.txt',b'Part: X\nQuantity: 2')}).json()
 r=propose(client,c,'model').json();assert r['extraction']['status']=='blocked_material' and fixture.calls==0

def test_accepting_revision_invalidates_approved_row(client):
 c=propose(client,create(client,'revision')).json()['case'];c=accept(client,c,index=1).json();id=c['id'];row=c['rows'][0]
 price={'part':'SEM-202','unit':'EA','condition':'FN','currency':'USD','amount':'10.00','valid_from':'2026-01-01','valid_until':'2027-12-31','lead_time':'synthetic','source':'SYN-SEM-TEST','kind':'synthetic'}
 for path,values in [('prices',{'prices':[price]}),('review',{'note':'reviewed all material; use original first'}),('approve',{'actor':'test'})]:
  r=client.post(f'/api/cases/{id}/{path}',json={'revision':c['revision'],'values':values});assert r.status_code==200,r.text;c=r.json()
 assert client.get(f'/api/cases/{id}/export').status_code==200
 c=propose(client,c).json()['case'];c=accept(client,c,index=0,target_row_id=row['id']).json()
 assert c['rows'][0]['quantity']=='5' and c['rows'][0]['stale']
 assert client.get(f'/api/cases/{id}/export').status_code==409


def test_reject_candidate_and_missing_reviewer_are_not_acceptance(client):
 c=propose(client,create(client)).json()['case']
 assert accept(client,c,actor='').status_code==422
 b=c['candidate_batches'][-1];r=b['candidates'][0]
 response=client.post(f"/api/cases/{c['id']}/candidates/{b['id']}/{r['id']}/review",json={'revision':c['revision'],'values':{'action':'reject','reason':'Synthetic reviewer rejects unsupported interpretation'}})
 assert response.status_code==200 and response.json()['rows']==[]
 assert response.json()['candidate_batches'][-1]['candidates'][0]['status']=='rejected'
 assert accept(client,response.json()).status_code==422


def test_http_contract_uses_mock_transport_only(client):
 import httpx,json
 from apps.api.model_config import ModelSettings
 seen=[]
 c=create(client);materials=read_materials(ROOT/'var/uploads'/c['id'])
 def reply(request):
  seen.append(json.loads(request.content))
  return httpx.Response(200,json={'usage':{'total_tokens':10},'choices':[{'message':{'content':json.dumps(semantic.offline_extract(materials))}}]})
 adapter=semantic.HTTPExtractionAdapter(ModelSettings('https://model.example.invalid/chat','test-only-placeholder','test-model',True),httpx.MockTransport(reply))
 main.app.dependency_overrides[semantic.get_adapter]=lambda:adapter
 result=propose(client,c,'model').json()
 assert len(seen)==1 and seen[0]['model']=='test-model'
 assert result['extraction']['model_status']=='not_run' and result['extraction']['requests']==0
 assert result['case']['rows']==[] and result['extraction']['engine']=='http_test_transport'


def test_compact_values_are_cleaned_but_stay_literal():
    from apps.api.semantic import expand_compact_payload,validate_payload
    from apps.api.materials import material_file
    text='询价号：RQ-401  PL-19 数量 6 PCS 件状 FN\nPlease quote the following:\n'.encode()
    m={'files':[material_file('m.txt',text)],'snapshot':'s'}
    at=lambda value,line=1:{'value':value,'file':'m.txt','location':f'text / line {line}'}
    payload={'candidates':[{'fields':{'rfq':at('RQ-401'),'part':at('PL-19'),'quantity':at('6 PCS'),'condition':at('件状 FN')}}]}
    expanded,dropped=expand_compact_payload(payload,m);rows=validate_payload(expanded,m)
    assert dropped==0 and {k:rows[0]['fields'][k] for k in ('rfq','part','quantity','unit','condition')}=={'rfq':'RQ-401','part':'PL-19','quantity':'6','unit':'PCS','condition':'FN'}
    for bad in ('Please quote the following:','PL-19'):
        expanded,dropped=expand_compact_payload({'candidates':[{'fields':{'rfq':at(bad,2 if bad.startswith('Please') else 1),'part':at('PL-19')}}]},m)
        assert dropped==1 and 'rfq' not in expanded['candidates'][0]['fields']

def test_provider_rate_limit_is_retried_once_then_reported(client,monkeypatch):
 import httpx
 monkeypatch.setattr(semantic.asyncio,'sleep',lambda s:_noop())
 class Busy:
  status='configured';calls=0
  async def extract(self,m,b):
   Busy.calls+=1
   request=httpx.Request('POST','https://provider.invalid');raise httpx.HTTPStatusError('busy',request=request,response=httpx.Response(429,request=request))
 main.app.dependency_overrides[semantic.get_adapter]=lambda:Busy()
 r=client.post('/api/import',files={'file':('mail.txt','Part: X\nQuantity: 2'.encode())}).json()
 res=client.post(f"/api/cases/{r['id']}/candidates/propose",json={'revision':r['revision'],'values':{'mode':'model','remote_consent':True}})
 assert res.status_code==422 and '繁忙' in res.json()['detail'] and Busy.calls==2

async def _noop():return None

def _resolve(text,fields):
    from apps.api.semantic import expand_compact_payload
    from apps.api.materials import material_file
    m={'files':[material_file('m.txt',text.encode())],'snapshot':'s'}
    return expand_compact_payload({'candidates':[{'fields':{k:{'value':v,'file':'m.txt','location':f'text / line {n}'} for k,(v,n) in fields.items()}}]},m),m

def test_a_single_request_number_written_last_is_not_a_boundary():
    (expanded,_),m=_resolve('Part: LT-1\nQty: 15\nRFQ: R9\n',{'part':('LT-1',1),'quantity':('15',2),'rfq':('R9',3)})
    assert semantic.validate_payload(expanded,m)[0]['fields']['rfq']=='R9'
    text='Part: LT-1\nRFQ: R8\nQty: 15\nRFQ: R9\n'
    (expanded,_),m=_resolve(text,{'part':('LT-1',1),'quantity':('15',3),'rfq':('R9',4)})
    with pytest.raises(ValueError,match='跨越'):semantic.validate_payload(expanded,m)

def test_quantity_words_and_placeholders():
    (e,_),_m=_resolve('件号 P1 三个 FN',{'part':('P1',1),'quantity':('三个',1)})
    assert e['candidates'][0]['fields']['quantity']['value']=='三' and e['candidates'][0]['fields']['unit']['value']=='个'
    (e,_),_m=_resolve('件号 P1 十二',{'part':('P1',1),'quantity':('十二',1)})
    assert e['candidates'][0]['fields']['quantity']['value']=='十二' and 'unit' not in e['candidates'][0]['fields']
    (e,d),_m=_resolve('件号 P1 数量待定',{'part':('P1',1),'quantity':('待定',1)})
    assert d==1 and 'quantity' not in e['candidates'][0]['fields']

def test_candidate_without_a_cited_part_is_dropped():
    (e,d),_m=_resolve('询价 RQ-1 详见附件',{'rfq':('RQ-1',1)})
    assert e=={'candidates':[]} and d==1

def test_extraction_reports_how_many_candidates_it_found(client):
 class One:
  status='configured'
  async def extract(self,m,b):
   f=m['files'][0];unit=f['units'][0];start=unit['text'].index('X')
   return semantic.AdapterReply({'candidates':[{'fields':{'part':{'value':'X','evidence':{k:unit[k] for k in ('file','sha256','location')}|{'start':start,'end':start+1,'quote':'X'}}}}]},10,1,'parsed','test')
 main.app.dependency_overrides[semantic.get_adapter]=lambda:One()
 r=client.post('/api/import',files={'file':('mail.txt','Part: X\nQuantity: 2'.encode())}).json()
 res=client.post(f"/api/cases/{r['id']}/candidates/propose",json={'revision':r['revision'],'values':{'mode':'model','remote_consent':True}})
 assert res.status_code==200 and res.json()['extraction']['count']==1

def test_misplaced_identifier_and_unit_are_moved():
    (e,_),_m=_resolve('RFQ: please quote 66-4400-1 qty 8 EA.',{'rfq':('66-4400-1',1),'quantity':('8',1),'condition':('EA',1)})
    f=e['candidates'][0]['fields']
    assert f['part']['value']=='66-4400-1' and 'rfq' not in f and f['unit']['value']=='EA' and 'condition' not in f
    (e,_),_m=_resolve('询价 RFQ-2395 详见附件',{'rfq':('RFQ-2395',1)})
    assert e=={'candidates':[]}

def test_unit_right_after_the_quantity_is_filled_in():
    for text,qty,unit in (('P/N MR-5 要 8 个，有货吗','8','个'),('P/N MR-5 Qty: 六 EA Cond: NE','六','EA'),('50 units of part MR-5','50','units')):
        (e,_),m=_resolve(text,{'part':('MR-5',1),'quantity':(qty,1)})
        assert e['candidates'][0]['fields']['unit']['value']==unit
        assert semantic.validate_payload(e,m)[0]['fields']['unit']==unit
    (e,_),_m=_resolve('P/N MR-5 qty 8 NE',{'part':('MR-5',1),'quantity':('8',1)})
    assert 'unit' not in e['candidates'][0]['fields']
