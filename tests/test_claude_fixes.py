from fastapi.testclient import TestClient
from apps.api import main
from apps.api.domain import number, new_case, analyze
from apps.api.parsing import parse_file
from evals.judges.evidence import EvidenceIndex
import pytest

def test_missing_part_is_retained():
    parsed=parse_file('test.csv',b'rfq,partnumber,quantity,unit,condition\nR1,,5,EA,FN\n')
    rows=analyze(new_case('test',parsed))
    assert len(rows)==1 and '缺少件号' in rows[0]['issues']

def test_condition_separation_and_ambiguity():
    def rows(condition,quantity='5'):
        return parse_file('test.csv',f'rfq,partnumber,quantity,unit,condition\nR1,AB-1,5,EA,NE\nR1,AB-1,{quantity},EA,{condition}\n'.encode())
    assert not any(r['conflict'] for r in analyze(new_case('test',rows('OH'))))
    assert all(r['conflict'] for r in analyze(new_case('test',rows('NE','6'))))
    assert all(r['conflict'] for r in analyze(new_case('test',rows(''))))

def test_decimal_grammar():
    assert str(number('0.5'))=='0.5'
    for invalid in ('1e3','２'):
        with pytest.raises(ValueError):number(invalid)

def test_csv_gb18030_and_evidence():
    data='询价单号,零件号,需求数量,um,cond,回复期限\nR1,AB-1,0.5,EA,NE,2030-01-01\n'.encode('gb18030')
    item=parse_file('input.csv',data)['rows'][0];index=EvidenceIndex();index.add('input.csv',data)
    assert item['fields']['quantity']=='0.5'
    assert index.verify('part','AB-1',[item['source']])['supported']

def test_csv_to_approved_quote(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'db.sqlite')
    with TestClient(main.app) as h:
        data='询价单号,零件号,需求数量,um,cond\nR1,AB-1,0.5,EA,NE\n'.encode('gb18030')
        c=h.post('/api/import',files={'file':('input.csv',data)}).json();url=f"/api/cases/{c['id']}"
        price={'part':'AB-1','unit':'EA','condition':'NE','currency':'USD','amount':'10','valid_from':'2020-01-01','valid_until':'2040-01-01','lead_time':'合成','source':'合成测试','kind':'synthetic'}
        r=h.post(url+'/prices',json={'revision':c['revision'],'values':{'prices':[price]}});assert r.status_code==200,r.text;c=r.json()
        r=h.post(url+'/approve',json={'revision':c['revision'],'values':{'actor':'reviewer'}});assert r.status_code==200,r.text;c=r.json()
        r=h.get(url+'/quote-preview',params={'revision':c['revision'],'format':'json'});assert r.status_code==200 and r.json()['rows'][0]['total']=='5.00'

def test_bulk_atomic_and_single_revision(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'db.sqlite')
    with TestClient(main.app) as h:
        c=h.post('/api/import',files={'file':('input.csv',b'rfq,partnumber,quantity,unit,condition,requirements\nR1,A,1,EA,FN,special\nR1,B,2,EA,FN,\n')}).json()
        ids=[r['id'] for r in c['rows']];url=f"/api/cases/{c['id']}/rows"
        bad=h.patch(url,json={'revision':c['revision'],'values':{'row_ids':[ids[0],'missing'],'due':'2030-01-01','reason':'review'}})
        assert bad.status_code==404 and h.get(f"/api/cases/{c['id']}").json()['revision']==c['revision']
        good=h.patch(url,json={'revision':c['revision'],'values':{'row_ids':ids,'due':'2030-01-01','reason':'review'}})
        assert good.status_code==200 and good.json()['revision']==c['revision']+1
        assert all(r['due']=='2030-01-01' for r in good.json()['rows'])
        assert any(i['code']=='requirements_review' for i in good.json()['rows'][0]['issue_codes'])

def test_bulk_due_rejects_blank_and_invalid_dates(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'db.sqlite')
    with TestClient(main.app) as h:
        c=h.post('/api/import',files={'file':('input.csv',b'rfq,partnumber,quantity,unit,condition,duedate\nR1,A,1,EA,FN,2020-01-01\n')}).json()
        ids=[r['id'] for r in c['rows']];url=f"/api/cases/{c['id']}/rows"
        for bad in ('','next year','20300101',None):
            r=h.patch(url,json={'revision':c['revision'],'values':{'row_ids':ids,'due':bad,'reason':'review'}})
            assert r.status_code==422,bad
        after=h.get(f"/api/cases/{c['id']}").json()
        assert after['revision']==c['revision'] and after['rows'][0]['due']=='2020-01-01'
        assert any(i['code']=='expired_due' for i in after['rows'][0]['issue_codes'])

def test_candidate_path_keeps_distinct_conditions_as_separate_lines(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'db.sqlite')
    body=b'RFQ: R9\nPart: K1\nQuantity: 2\nUnit: EA\nCondition: NE\nRFQ: R9\nPart: K1\nQuantity: 2\nUnit: EA\nCondition: OH\nRFQ: R9\nPart: K1\nQuantity: 3\nUnit: EA\nCondition: ne\n'
    with TestClient(main.app) as h:
        c=h.post('/api/import',files={'file':('input.txt',body)}).json();url=f"/api/cases/{c['id']}"
        c=h.post(url+'/candidates/propose',json={'revision':c['revision'],'values':{'mode':'offline'}}).json()['case']
        batch=c['candidate_batches'][-1];results=[]
        for candidate in batch['candidates']:
            revision=h.get(url).json()['revision']
            results.append(h.post(f"{url}/candidates/{batch['id']}/{candidate['id']}/review",json={'revision':revision,'values':{'action':'accept','actor':'t','reason':'r','confirm_association':True}}).status_code)
        # A case variant of an existing condition is still the same line and needs an explicit target.
        assert results==[200,200,422]
        assert [r['condition'] for r in h.get(url).json()['rows']]==['NE','OH']

def test_case_variant_condition_stays_in_conflict():
    parsed=parse_file('test.csv',b'rfq,partnumber,quantity,unit,condition\nR1,AB-1,2,EA,NE\nR1,AB-1,2,EA,ne\n')
    assert all(r['conflict'] for r in analyze(new_case('test',parsed)))

def test_decimal_grammar_rejects_signed_and_partial_forms():
    for invalid in ('+5','5.','.5'):
        with pytest.raises(ValueError):number(invalid)
