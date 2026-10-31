from copy import deepcopy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from apps.api import main,semantic

ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture
def c(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'db.sqlite')
    import shutil
    shutil.copytree(ROOT/'data/synthetic/competitive-20261028',tmp_path/'data/synthetic/competitive-20261028')
    client=TestClient(main.app)
    data=(ROOT/'data/synthetic/competitive-20261028/tune-v3-zh.txt').read_bytes()
    case=client.post('/api/import',files={'file':('tune-v3-zh.txt',data)}).json()
    m=client.get('/api/cases/'+case['id']+'/materials').json();u=m['files'][0]['units'][0]
    fields={}
    for f,v in {'rfq':'000835','part':'TU-63','quantity':'4','unit':'EA','condition':'OH','due':'2027-03-30'}.items():
        a=u['text'].index(v);fields[f]={'value':v,'evidence':{k:u[k] for k in ('file','sha256','location')}|{'start':a,'end':a+len(v),'quote':v}}
    class Adapter:
        async def extract(self,m,b):return semantic.AdapterReply({'candidates':[{'fields':fields}]},10,0,'not_run','test_dependency')
    main.app.dependency_overrides[semantic.get_adapter]=lambda:Adapter()
    r=client.post('/api/cases/'+case['id']+'/candidates/propose',json={'revision':case['revision'],'values':{'mode':'model'}}).json();case=r['case'];b=case['candidate_batches'][-1];x=b['candidates'][0]
    case=client.post(f"/api/cases/{case['id']}/candidates/{b['id']}/{x['id']}/review",json={'revision':case['revision'],'values':{'action':'accept','actor':'DEV','reason':'review original','confirm_association':True}}).json()
    yield client,case,tmp_path
    main.app.dependency_overrides.clear()

def change(client,case,route,values):
    r=client.post(f"/api/cases/{case['id']}/"+route,json={'revision':case['revision'],'values':values});assert r.status_code==200,r.text
    return r.json()

def test_accepted_candidate_fields_reach_approval(c):
    client,case,tmp=c
    main.source_guard(case)
    e=client.get(f"/api/cases/{case['id']}/evidence/{case['rows'][0]['id']}").json()
    assert e['integrity_ok'] and all(e['fields'][f]['human_role_reviewed'] and not e['fields'][f]['supported'] for f in ('rfq','part','quantity','unit','condition','due'))
    p={'part':'TU-63','unit':'EA','condition':'OH','currency':'USD','amount':'10','valid_from':'2026-01-01','valid_until':'2030-12-31','lead_time':'SYN','source':'SYN DEV','kind':'synthetic'}
    case=change(client,case,'prices',{'prices':[p]});case=change(client,case,'review',{'note':'Original synthetic document reviewed'});case=change(client,case,'approve',{'actor':'DEV'})
    assert case['rows'][0]['approved']

def test_unaccepted_or_tampered_source_cannot_pass(c):
    client,case,tmp=c
    unaccepted=deepcopy(case);unaccepted['candidate_batches'][-1]['candidates'][0]['status']='pending'
    with pytest.raises(ValueError):main.source_guard(unaccepted)
    other=deepcopy(case);other['candidate_batches'][-1]['candidates'][0]['row_id']='another-row'
    with pytest.raises(ValueError):main.source_guard(other)
    original=tmp/'var/uploads'/case['id']/'tune-v3-zh.txt';original.write_bytes(b'changed after acceptance')
    with pytest.raises(ValueError):main.source_guard(case)

def test_model_on_user_file_requires_explicit_consent(c):
    client,_,_=c
    data='Please quote part QX-7, 3 EA, condition NE, for RFQ 77.'.encode()
    case=client.post('/api/import',files={'file':('mail.txt',data)}).json();url=f"/api/cases/{case['id']}/candidates/propose"
    r=client.post(url,json={'revision':case['revision'],'values':{'mode':'model'}}).json()
    assert r['extraction']['status']=='blocked_material' and r['extraction']['requests']==0
    r=client.post(url,json={'revision':case['revision'],'values':{'mode':'model','remote_consent':True}})
    assert r.status_code in (200,422) and r.json().get('extraction',{}).get('status')!='blocked_material'

def test_batch_accept_takes_uncontested_and_leaves_the_rest(c):
    client,_,_=c
    body=('RFQ: R1\nPart: A1\nQuantity: 2\nUnit: EA\nCondition: NE\nRFQ: R1\nPart: B1\nQuantity: 4\nUnit: EA\nCondition: FN\nRFQ: R1\nPart: B1\nQuantity: 9\nUnit: EA\nCondition: FN\nRFQ: R1\nPart: D1\nQuantity: three\nUnit: EA\nCondition: NE\n').encode()
    case=client.post('/api/import',files={'file':('m.txt',body)}).json();url=f"/api/cases/{case['id']}/candidates"
    case=client.post(url+'/propose',json={'revision':case['revision'],'values':{'mode':'offline'}}).json()['case'];b=case['candidate_batches'][-1]
    bad=client.post(f"{url}/{b['id']}/accept-batch",json={'revision':case['revision'],'values':{'actor':'t','reason':'r'}});assert bad.status_code==422
    r=client.post(f"{url}/{b['id']}/accept-batch",json={'revision':case['revision'],'values':{'actor':'t','reason':'r','confirm_association':True}});assert r.status_code==200,r.text
    after=r.json();assert after['revision']==case['revision']+1
    assert [x['part'] for x in after['rows']]==['A1']
    batch=after['candidate_batches'][-1];assert [x['status'] for x in batch['candidates']]==['accepted','pending','pending','pending'] and batch['expected_revision']==after['revision']
    x=batch['candidates'][1];rest=client.post(f"{url}/{b['id']}/{x['id']}/review",json={'revision':after['revision'],'values':{'action':'accept','actor':'t','reason':'r','confirm_association':True}});assert rest.status_code==200,rest.text
