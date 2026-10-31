from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
import json
import pytest
import openpyxl
from fastapi.testclient import TestClient
from apps.api.parsing import parse_file
from apps.api.domain import new_case,analyze,replace_prices,approve,export_data
from apps.api import main

ROOT=Path(__file__).resolve().parents[1]

def simple():
    c=new_case('synthetic',{'rows':[{'fields':{'rfq':'0001','part':'SYN-001','quantity':'3','unit':'EA','condition':'FN'},'raw_fields':{},'source':{'file':'synthetic','location':'row 1','raw':[]}}],'warnings':[],'fragments':[]})
    replace_prices(c,json.loads((ROOT/'data/synthetic/prices.json').read_text(encoding='utf-8')))
    return c

def test_decimal_and_version_invalidation():
    c=simple();approve(c,'test');assert export_data(c)['rows'][0]['total']=='37.05'
    p=deepcopy(c['prices']);p[0]['amount']='12.36';affected=replace_prices(c,p)
    assert affected==[c['rows'][0]['id']]
    assert analyze(c)[0]['stale']
    with pytest.raises(ValueError):export_data(c)
    approve(c,'test');assert export_data(c)['rows'][0]['total']=='37.08'

def test_unrelated_price_preserves_approval():
    c=simple();approve(c,'test');p=deepcopy(c['prices']);p[1]['amount']='50';assert replace_prices(c,p)==[]
    assert export_data(c)['rows'][0]['approved']

def test_jpy_currency_precision():
    c=simple();c['prices'][0]['currency']='JPY';c['prices'][0]['amount']='12.50'
    approve(c,'test');assert export_data(c)['rows'][0]['total']=='38'

def test_invalid_price_update_preserves_approved_snapshot():
    c=simple();approve(c,'test');before=deepcopy(c)
    for p in ('not-an-array',[None],[{**c['prices'][0],'amount':'1e99999'}],[{**c['prices'][0],'amount':'1e9999999'}],[{**c['prices'][0],'valid_from':'20260101'}],[{**c['prices'][0],'amount':{'untrusted':'value'}}]):
        with pytest.raises(ValueError):replace_prices(c,p)
        assert c==before
        assert export_data(c)['rows'][0]['total']=='37.05'

@pytest.mark.parametrize('field,value',[('unit','FT'),('condition','OH'),('quantity','NaN'),('quantity','0'),('quantity','-1'),('due','2020-01-01'),('rfq','')])
def test_bad_request_blocks_output(field,value):
    c=simple();c['rows'][0][field]=value
    with pytest.raises(ValueError):approve(c,'test')

def test_expired_ambiguous_and_missing_price():
    for mode in ('expired','ambiguous','missing'):
        c=simple();p=deepcopy(c['prices'])
        if mode=='expired':p[0]['valid_until']='2020-01-01';p[0]['valid_from']='2019-01-01'
        if mode=='ambiguous':p.append(deepcopy(p[0]))
        if mode=='missing':p=[]
        replace_prices(c,p)
        with pytest.raises(ValueError):approve(c,'test')

def test_demo_identity_duplicate_conflict():
    parsed=parse_file('demo.eml',(ROOT/'data/synthetic/demo.eml').read_bytes());c=new_case('demo',parsed)
    assert len(c['rows'])==6
    rows=analyze(c)
    assert not rows[0]['duplicate'] and rows[1]['duplicate'] and rows[2]['duplicate']
    assert rows[3]['conflict'] and rows[4]['conflict']
    c['rows'][2]['excluded']=True;c['rows'][4]['excluded']=True
    assert not analyze(c)[1]['duplicate'] and not analyze(c)[3]['conflict']

def test_xlsx_identifiers_and_raw_location():
    w=openpyxl.Workbook();s=w.active;s.append(['RFQ No.','Part Number','Quantity','Unit','Condition']);s.append(['00001',12,3,'EA','FN']);s['B2'].number_format='00000';b=BytesIO();w.save(b)
    r=parse_file('test.xlsx',b.getvalue())['rows'][0]
    assert r['fields']['rfq']=='00001' and r['fields']['part']=='00012'
    assert 'row 2' in r['source']['location']

def test_official_local_pdf_continuation():
    files=list((ROOT/'data/raw').rglob('*.pdf'))
    if not files: pytest.skip('Official local-only materials unavailable')
    for p in files:
        parsed=parse_file(p.name,p.read_bytes())
        assert len(parsed['rows'])==7
        assert 'page 2' in parsed['rows'][-1]['source']['location']
        assert parsed['rows'][-1]['fields']['unit']=='Each'
        assert not parsed['rows'][-1]['fields'].get('condition')

def test_api_end_to_end_and_concurrency(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',tmp_path/'test.sqlite');client=TestClient(main.app)
    c=client.post('/api/demo').json();id=c['id']
    assert client.get(f'/api/cases/{id}/export').status_code==409
    def post(path,values):
        nonlocal c
        r=client.post(f'/api/cases/{id}/{path}',json={'revision':c['revision'],'values':values});assert r.status_code==200,r.text;c=r.json()
    post('demo-prices',{})
    for index in (2,4):
        r=client.patch(f"/api/cases/{id}/rows/{c['rows'][index]['id']}",json={'revision':c['revision'],'values':{'excluded':True,'reason':'合成样例：确认重复/冲突，保留另行'}});assert r.status_code==200;c=r.json()
    p=deepcopy(c['prices']);p.append({**p[0],'part':'SYN-003','amount':'10.10'})
    post('prices',{'prices':p});post('approve',{'actor':'本地测试'})
    assert client.get(f'/api/cases/{id}/export?format=csv').status_code==200
    old=c['revision'];p[0]['amount']='13.00';post('prices',{'prices':p})
    assert client.get(f'/api/cases/{id}/export').status_code==409
    assert client.post(f'/api/cases/{id}/approve',json={'revision':old,'values':{'actor':'stale'}}).status_code==409
    assert client.get(f'/api/cases/{id}').json()['revision']==c['revision']
