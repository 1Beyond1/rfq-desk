from copy import deepcopy
import asyncio, hashlib, json
import pytest
from fastapi.testclient import TestClient
from apps.api import main, semantic
from apps.api.domain import new_case, analyze, approve, export_data, replace_prices, FIELDS
from apps.api.materials import material_file, digest
from evals.judges.evidence import EvidenceIndex

BASE='RFQ: DEV-R1\nPart: PATCH-771\nQuantity: 2\nUnit: EA\nCondition: FN\nDue date: 2027-10-30\nDescription: synthetic seal\nRequirements: synthetic dry pack\nPriority: normal\n'
SECOND=BASE.replace('DEV-R1','DEV-R2').replace('Quantity: 2','Quantity: 4')
PATCH='RFQ: DEV-R1\nPart: PATCH-771\nQuantity: 5\n'

def materials(files):
 fs=[material_file(n,b.encode()) for n,b in files.items()]
 return {'files':fs,'snapshot':digest([{k:f[k] for k in ('file','sha256')} for f in fs])}
def batch(c,m):
 b=asyncio.run(semantic.propose(c,m,'offline',None));c['revision']+=1;return b

def fixture():
 files={'base.txt':BASE+SECOND,'revision.txt':PATCH};m=materials(files)
 c=new_case('new synthetic partial DEV',{'rows':[],'warnings':[],'fragments':[]})
 b=batch(c,m)
 for candidate in b['candidates'][:2]:
  semantic.accept_candidate(c,b,candidate,m,{'actor':'synthetic reviewer','reason':'explicit synthetic original selection','confirm_association':True});c['revision']+=1
 c['prices']=[{'part':'PATCH-771','unit':'EA','condition':'FN','currency':'USD','amount':'10.00','valid_from':'2026-01-01','valid_until':'2027-12-31','lead_time':'synthetic','source':'synthetic DEV card','kind':'synthetic'}]
 approve(c,'synthetic reviewer',today='2026-10-23')
 return c,m,files

def options(c,**kw):
 return {'actor':'synthetic reviewer','reason':'synthetic card explicitly selects R1 revision', 'confirm_association':True,'target_row_id':c['rows'][0]['id'],'mode':'partial','base_revision':c['revision'],'base_row_revision':c['rows'][0]['revision'],'update_fields':['quantity'],'clear_fields':[],**kw}

def pending(c,m):
 b=batch(c,m);return b,b['candidates'][2]

def test_reproduce_old_full_replace_loses_omitted_fields():
 c,m,_=fixture();b,r=pending(c,m)
 semantic.accept_candidate(c,b,r,m,{'actor':'synthetic','reason':'reproduce full replacement','confirm_association':True,'target_row_id':c['rows'][0]['id']})
 assert c['rows'][0]['unit']=='' and c['rows'][0]['due']==''
 assert analyze(c,'2026-10-23')[0]['issues']

def test_partial_preserves_provenance_and_approval_scope():
 c,m,files=fixture();before=deepcopy(c['rows']);b,r=pending(c,m)
 semantic.accept_candidate(c,b,r,m,options(c))
 row=c['rows'][0]
 for f in FIELDS:
  assert row[f]==('5' if f=='quantity' else before[0][f])
  if f!='quantity':
   assert row['field_provenance'][f]['sources']==before[0]['field_provenance'][f]['sources']
   assert row['field_provenance'][f]['inherited_from']['row_revision']==before[0]['revision']
 index=EvidenceIndex()
 for name,data in files.items():index.add(name,data.encode())
 counts={'source':0,'human':0,'inherited':0}
 for f in FIELDS:
  name='revision.txt' if f=='quantity' else 'base.txt';line='text / line 2'
  binding={'file':name,'sha256':hashlib.sha256(files[name].encode()).hexdigest(),'record_id':line}
  assert index.verify_claim(row,f,{},expected_binding=binding)['supported'],f
  counts['source']+=1
  counts['inherited']+=f!='quantity'
 assert counts=={'source':9,'human':0,'inherited':8}
 a=analyze(c,'2026-10-23');assert a[0]['stale'] and a[1]['approved'] and c['rows'][1]==before[1]
 with pytest.raises(ValueError):export_data(c,'2026-10-23')
 approve(c,'synthetic reapproval','2026-10-23')
 assert [r['total'] for r in export_data(c,'2026-10-23')['rows']]==['50.00','40.00']

@pytest.mark.parametrize('override',[{'target_row_id':'missing'}, {'base_revision':-1},{'base_row_revision':-1},{'update_fields':[]},{'update_fields':['quantity','due']},{'fields':{'quantity':'0'}},{'clear_fields':['quantity']},{'clear_fields':['due'],'clear_reason':''},{'mode':'typo'}])
def test_invalid_partial_is_atomic(override):
 c,m,_=fixture();b,r=pending(c,m);before=deepcopy(c)
 with pytest.raises(ValueError):semantic.accept_candidate(c,b,r,m,options(c,**override))
 assert c==before

def test_clear_is_distinct_from_omission_and_keeps_human_chain():
 c,m,_=fixture();b,r=pending(c,m);old=deepcopy(c['rows'][0])
 semantic.accept_candidate(c,b,r,m,options(c,clear_fields=['due'],clear_reason='synthetic authorized removal of deadline'))
 row=c['rows'][0];assert row['due']=='' and row['description']==old['description']
 p=row['field_provenance']['due'];assert p['kind']=='human' and p['original_value']==old['due']
 assert next(d for d in c['human_decisions'] if d['id']==p['decision_id'])['reason']=='synthetic authorized removal of deadline'
 b,r=pending(c,m);semantic.accept_candidate(c,b,r,m,options(c))
 assert c['rows'][0]['field_provenance']['due']['decision_id']==p['decision_id']
 assert c['rows'][0]['raw_fields']['due']==old['raw_fields']['due']

def test_wrong_target_tamper_concurrent_and_no_automatic_upload_order():
 c,m,files=fixture();b,r=pending(c,m);before=deepcopy(c)
 with pytest.raises(ValueError):semantic.accept_candidate(c,b,r,m,options(c,target_row_id=c['rows'][1]['id']))
 assert c==before
 bad=deepcopy(r);bad['field_sources']['quantity']=b['candidates'][0]['field_sources']['quantity']
 with pytest.raises(ValueError):semantic.accept_candidate(c,b,bad,m,options(c))
 altered=materials({**files,'base.txt':BASE.replace('EA','FT')+SECOND})
 with pytest.raises(ValueError):semantic.accept_candidate(c,b,r,altered,options(c))
 c['revision']+=1
 with pytest.raises(ValueError):semantic.accept_candidate(c,b,r,m,options(c))
 assert c['rows']==before['rows']
 # Late upload is just material: no acceptance and no automatic row overwrite.
 late=materials({**files,'late-old.txt':BASE});batch(c,late)
 assert c['rows']==before['rows']

def test_api_append_review_versions_export_and_evidence(tmp_path,monkeypatch):
 monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'api.sqlite')
 with TestClient(main.app) as client:
  c=client.post('/api/import',files={'file':('base.txt',(BASE+SECOND).encode())}).json()
  def post(path,values):
   nonlocal c
   res=client.post('/api/cases/'+c['id']+'/'+path,json={'revision':c['revision'],'values':values});assert res.status_code==200,res.text
   obj=res.json();c=obj.get('case',obj);return obj
  post('candidates/propose',{'mode':'offline'})
  b=c['candidate_batches'][-1]
  for r in b['candidates']:
   post(f"candidates/{b['id']}/{r['id']}/review",{'action':'accept','actor':'synthetic','reason':'original explicit selection','confirm_association':True})
  p=fixture()[0]['prices'];post('prices',{'prices':p});post('review',{'note':'synthetic complete material reviewed'});post('approve',{'actor':'synthetic'})
  old=deepcopy(c)
  response=client.post(f"/api/cases/{c['id']}/materials",data={'revision':c['revision']},files={'file':('revision.txt',PATCH.encode())});assert response.status_code==200;c=response.json()
  assert c['rows']==old['rows']
  assert client.post(f"/api/cases/{c['id']}/materials",data={'revision':c['revision']},files={'file':('revision.txt',b'overwrite')}).status_code==409
  post('candidates/propose',{'mode':'offline'});b=c['candidate_batches'][-1];r=b['candidates'][2]
  route=f"candidates/{b['id']}/{r['id']}/review";review=options(c,action='accept')
  stale=deepcopy(c)
  post(route,review)
  assert c['rows'][0]['stale'] and c['rows'][1]['approved']
  assert client.post('/api/cases/'+c['id']+'/'+route,json={'revision':stale['revision'],'values':review}).status_code==409
  assert client.get('/api/cases/'+c['id']+'/export').status_code==409
  e=client.get('/api/cases/'+c['id']+'/evidence/'+c['rows'][0]['id']).json()
  assert e['integrity_ok'] and e['fields']['unit']['inherited_from'] and e['fields']['quantity']['record']['file']=='revision.txt'
  post('approve',{'actor':'synthetic reapproval'})
  result=client.get('/api/cases/'+c['id']+'/export').json();assert [r['total'] for r in result['rows']]==['50.00','40.00']
  # A concurrent edit invalidates an open patch even when caller refreshes only envelope revision.
  post('candidates/propose',{'mode':'offline'});b=c['candidate_batches'][-1];r=b['candidates'][2];review=options(c,action='accept')
  post('review',{'note':'concurrent synthetic review'})
  assert client.post(f"/api/cases/{c['id']}/candidates/{b['id']}/{r['id']}/review",json={'revision':c['revision'],'values':review}).status_code==422

@pytest.mark.parametrize('quantity',['0','-3','NaN','Infinity','1e9999',''])
def test_partial_invalid_quantities_leave_everything_unchanged(quantity):
 c,m,_=fixture();b,r=pending(c,m);old=deepcopy(c)
 with pytest.raises(ValueError):semantic.accept_candidate(c,b,r,m,options(c,fields={'quantity':quantity}))
 assert c==old

def test_wrong_revision_equal_value_and_full_replacement():
 c,m,_=fixture();b,r=pending(c,m)
 # Two identical quantities in distinct labelled records: value alone is insufficient.
 alternate=materials({'revision.txt':PATCH+'\n'+PATCH.replace('DEV-R1','DEV-R2')})
 b2=batch(c,alternate);r2=deepcopy(b2['candidates'][0]);r2['field_sources']['quantity']=b2['candidates'][1]['field_sources']['quantity'];old=deepcopy(c)
 with pytest.raises(ValueError):semantic.accept_candidate(c,b2,r2,alternate,options(c))
 assert c==old
 # Full replacement remains explicit and does not inherit absent fields.
 b=batch(c,m);candidate=b['candidates'][0]
 semantic.accept_candidate(c,b,candidate,m,{'mode':'full','actor':'synthetic','reason':'complete replacement selected','confirm_association':True,'target_row_id':c['rows'][0]['id']})
 assert all(c['rows'][0][f]==candidate['fields'][f] for f in FIELDS)

def test_human_clear_claim_with_independent_original_binding():
 c,m,files=fixture();b,r=pending(c,m)
 semantic.accept_candidate(c,b,r,m,options(c,clear_fields=['due'],clear_reason='synthetic deadline removal authorization'))
 index=EvidenceIndex()
 for name,data in files.items():index.add(name,data.encode())
 binding={'file':'base.txt','sha256':hashlib.sha256(files['base.txt'].encode()).hexdigest(),'record_id':'text / line 2'}
 ledger={d['id']:d for d in c['human_decisions']}
 claim=index.verify_claim(c['rows'][0],'due',ledger,expected_binding=binding)
 assert claim['supported'] and claim['kind']=='human'
 assert not index.verify_claim(c['rows'][0],'due',{},expected_binding=binding)['supported']
