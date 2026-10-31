from copy import deepcopy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from apps.api import main
from apps.api.domain import FIELDS, analyze

DATA=Path(__file__).resolve().parents[1]/'data/synthetic/clarification'

class Session:
    def __init__(self, h):
        self.h=h
        self.c=h.post('/api/import',files={'file':('roundtrip.eml',(DATA/'roundtrip.eml').read_bytes())}).json()
        assert len(self.c['rows'])==2
        self.url='/api/cases/'+self.c['id']
    def post(self, route, values, status=200):
        old=deepcopy(self.h.get(self.url).json())
        r=self.h.post(self.url+'/'+route,json={'revision':self.c['revision'],'values':values})
        assert r.status_code==status,r.text
        if status==200:self.c=r.json()
        else:assert self.h.get(self.url).json()==old
        return r
    def append(self,name):
        r=self.h.post(self.url+'/materials',data={'revision':self.c['revision']},files={'file':(name,(DATA/name).read_bytes())})
        assert r.status_code==200,r.text
        self.c=r.json()
    def question(self,field):return next(q for q in self.c['clarifications'] if q['field']==field)
    def receive(self,field,name,version=1,status=200):
        q=self.question(field)
        self.post(f"clarifications/{q['id']}/replies",{'filename':name,'reply_row_revision':version,'actor':'synthetic reviewer','reason':'synthetic explicit target/version review'},status)
    def propose(self):
        r=self.h.post(self.url+'/candidates/propose',json={'revision':self.c['revision'],'values':{'mode':'offline'}})
        assert r.status_code==200,r.text
        self.c=r.json()['case']
    def apply(self,field,name,resolve=True,status=200,**overrides):
        q=self.question(field);reply=next(r for r in q['replies'] if r['filename']==name)
        b=self.c['candidate_batches'][-1];candidate=next(c for c in b['candidates'] if any(s['file']==name for s in c['field_sources'].values()))
        row=next(r for r in self.c['rows'] if r['id']==q['row_id'])
        v={'action':'accept','mode':'partial','fields':{},'actor':'synthetic reviewer','reason':'synthetic literal field and target verified','target_row_id':row['id'],'base_revision':self.c['revision'],'base_row_revision':row['revision'],'update_fields':[field],'clear_fields':[],'confirm_association':True,'confirmed_fields':[], 'clarification_id':q['id'],'reply_id':reply['id'],'resolve_clarification':resolve}
        v.update(overrides)
        return self.post(f"candidates/{b['id']}/{candidate['id']}/review",v,status)

@pytest.fixture
def s(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'test.sqlite')
    with TestClient(main.app) as h:yield Session(h)

def test_roundtrip_separate_rfqs_insufficient_atomic_and_approval(s):
    s.post('clarifications/register',{})
    assert len(s.c['clarifications'])==2
    ids=[q['id'] for q in s.c['clarifications']]
    s.post('clarifications/register',{});assert [q['id'] for q in s.c['clarifications']]==ids
    draft=s.h.get(s.url+'/draft').json()['text'];assert all(i in draft for i in ids) and '009401' in draft and '009402' in draft
    s.append('insufficient.txt');s.receive('unit','insufficient.txt');s.propose()
    s.apply('unit','insufficient.txt',status=422)
    assert s.question('unit')['state']=='received' and not s.c['rows'][0]['unit']
    second=deepcopy(s.c['rows'][1])
    s.append('reply-unit.txt');s.receive('unit','reply-unit.txt');s.propose();s.apply('unit','reply-unit.txt')
    assert s.question('unit')['state']=='resolved' and s.question('condition')['state']=='awaiting_reply'
    assert all(s.c['rows'][1][f]==second[f] for f in FIELDS) and s.c['rows'][1]['revision']==second['revision']
    s.post('approve',{'actor':'synthetic'},422)
    s.append('reply-condition.txt');s.receive('condition','reply-condition.txt');s.propose();s.apply('condition','reply-condition.txt')
    assert all(q['state']=='resolved' for q in s.c['clarifications'])
    price={'part':'CLARIFY-001','unit':'EA','condition':'FN','currency':'USD','amount':'12.35','valid_from':'2026-01-01','valid_until':'2030-12-31','lead_time':'synthetic 7 days','source':'SYN-CLARIFY-CARD','kind':'synthetic'}
    s.post('prices',{'prices':[price]});s.post('approve',{'actor':'synthetic'})
    r=s.h.get(s.url+f'/export?format=json&revision={s.c["revision"]}');assert r.status_code==200
    assert [r['total'] for r in r.json()['rows']]==['24.70','37.05']
    s.post('prices',{'prices':[{**price,'amount':'13.00'}]})
    assert all(not r['approved'] and r['stale'] for r in s.c['rows'])
    assert s.h.get(s.url+'/export?format=html&revision='+str(s.c['revision'])).status_code==409

def test_old_duplicate_wrong_target_and_missing_context(s):
    s.post('clarifications/register',{})
    row=s.c['rows'][0]
    r=s.h.patch(s.url+'/rows/'+row['id'],json={'revision':s.c['revision'],'values':{'description':'synthetic new revision','reason':'synthetic authorized current version'}});s.c=r.json()
    s.append('old-unit.txt');s.receive('unit','old-unit.txt',1);s.receive('unit','old-unit.txt',1,422)
    s.propose();s.apply('unit','old-unit.txt',status=422)
    s.append('reply-condition.txt');s.receive('unit','reply-condition.txt',2);s.propose()
    s.apply('unit','reply-condition.txt',status=422)
    # Even an explicit generic candidate operation cannot silently discard its linked reply/version.
    s.apply('unit','reply-condition.txt',status=422,clarification_id=None)
    s.append('reply-unit.txt');s.receive('unit','reply-unit.txt',2);s.propose()
    s.apply('unit','reply-unit.txt',status=422,target_row_id=s.c['rows'][1]['id'])
    stale=s.c['revision']-1
    r=s.h.post(s.url+'/clarifications/register',json={'revision':stale,'values':{}});assert r.status_code==409

def test_apply_without_closing_manual_and_stale_conclusion(s):
    s.post('clarifications/register',{});s.append('reply-unit.txt');s.receive('unit','reply-unit.txt');s.propose()
    s.apply('unit','reply-unit.txt',resolve=False)
    assert s.c['rows'][0]['unit']=='EA' and s.question('unit')['state']=='received'
    q=s.question('unit');reply=q['replies'][0];row=s.c['rows'][0]
    s.post(f"clarifications/{q['id']}/resolve",{'method':'reply','reply_id':reply['id'],'base_row_revision':row['revision'],'actor':'synthetic','reason':'independent explicit closure'})
    assert s.question('unit')['state']=='resolved'
    r=s.h.patch(s.url+'/rows/'+row['id'],json={'revision':s.c['revision'],'values':{'unit':'FT','reason':'synthetic independent authorized change'}})
    assert r.status_code==200;s.c=r.json()
    assert s.question('unit')['state']=='stale' and len(s.question('unit')['resolutions'])==1
    s.post(f"clarifications/{q['id']}/resolve",{'method':'manual','base_row_revision':s.c['rows'][0]['revision'],'actor':'synthetic','reason':'explicit current FT decision verified'})
    assert s.question('unit')['state']=='resolved' and len(s.question('unit')['resolutions'])==2

def test_manual_cannot_close_invalid_field_or_no_record(s):
    s.post('clarifications/register',{});q=s.question('unit')
    v={'method':'manual','base_row_revision':1,'actor':'synthetic','reason':'not an answer'}
    s.post(f"clarifications/{q['id']}/resolve",v,422)
    s.receive('unit','roundtrip.eml',status=422)
    row=s.c['rows'][0]
    r=s.h.patch(s.url+'/rows/'+row['id'],json={'revision':s.c['revision'],'values':{'unit':'EA','reason':'synthetic authorized manual unit'}});assert r.status_code==200;s.c=r.json()
    s.post(f"clarifications/{q['id']}/resolve",{**v,'base_row_revision':2})
    assert s.question('unit')['state']=='resolved'

def test_reply_changed_original_and_insufficient_value_atomic(s):
    s.post('clarifications/register',{});s.append('reply-unit.txt');s.receive('unit','reply-unit.txt');s.propose()
    # A literal exists but an unknown unit cannot close the question until explicitly confirmed.
    s.apply('unit','reply-unit.txt',status=422,fields={'unit':'UNKNOWN'})
    path=main.ROOT/'var/uploads'/s.c['id']/'reply-unit.txt';path.write_bytes(path.read_bytes()+b'changed')
    s.apply('unit','reply-unit.txt',status=422)

def test_missing_identity_manual_fix_can_close_stable_row(s):
    row=s.c['rows'][0]
    r=s.h.patch(s.url+'/rows/'+row['id'],json={'revision':s.c['revision'],'values':{'rfq':'','reason':'synthetic missing identity setup'}});s.c=r.json()
    s.post('clarifications/register',{});q=s.question('rfq')
    r=s.h.patch(s.url+'/rows/'+row['id'],json={'revision':s.c['revision'],'values':{'rfq':'009401','reason':'synthetic original identity checked'}});s.c=r.json()
    s.post(f"clarifications/{q['id']}/resolve",{'method':'manual','base_row_revision':s.c['rows'][0]['revision'],'actor':'synthetic','reason':'stable row and original RFQ confirmed'})
    assert s.question('rfq')['state']=='resolved'


def test_reassigned_target_requires_explicit_retirement_and_new_question(s):
    s.post('clarifications/register',{});q=s.question('unit');row=s.c['rows'][0]
    r=s.h.patch(s.url+'/rows/'+row['id'],json={'revision':s.c['revision'],'values':{'rfq':'009499','reason':'synthetic authorized reassignment'}});s.c=r.json()
    assert s.question('unit')['state']=='stale'
    v={'method':'manual','base_row_revision':2,'actor':'synthetic','reason':'old target no longer active'}
    s.post(f"clarifications/{q['id']}/resolve",v,422)
    s.post(f"clarifications/{q['id']}/resolve",{**v,'method':'superseded'})
    assert s.question('unit')['state']=='superseded' and not s.c['rows'][0]['unit']
    s.post('clarifications/register',{})
    assert len([q for q in s.c['clarifications'] if q['field']=='unit'])==2
    assert any(q['rfq']=='009499' and q['state']=='awaiting_reply' for q in s.c['clarifications'])
    assert any('缺少单位' in i for i in s.c['rows'][0]['issues'])

    old_id=q['id']
    r=s.h.patch(s.url+'/rows/'+row['id'],json={'revision':s.c['revision'],'values':{'unit':'EA','reason':'synthetic new target confirmation'}});s.c=r.json()
    assert next(q for q in s.c['clarifications'] if q['id']==old_id)['state']=='superseded'
