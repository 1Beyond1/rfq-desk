from pathlib import Path
from copy import deepcopy
import io,csv,hashlib
import pytest
from openpyxl import Workbook
from fastapi.testclient import TestClient
from apps.api import main,price_intake
from apps.api.domain import price_validate

P={'part':'000001','unit':'EA','condition':'FN','currency':'USD','amount':'12.35','valid_from':'2026-01-01','valid_until':'2027-12-31','lead_time':'synthetic 7 days','source':'synthetic card','kind':'synthetic'}
B=b'RFQ No.\tPart Number\tQuantity\tUnit\tCondition\n000001\t000001\t2\tEA\tFN\n'
def csvdata(rows):
 out=io.StringIO();w=csv.writer(out);w.writerow(price_intake.COLUMNS);w.writerows([[p[k] for k in price_intake.COLUMNS] for p in rows]);return out.getvalue().encode()
def workbook(numeric=False):
 b=Workbook();w=b.active;w.append(list(price_intake.COLUMNS));w.append([P[k] for k in price_intake.COLUMNS]);
 if numeric:w.cell(2,1,1)
 out=io.BytesIO();b.save(out);return out.getvalue()

def test_strict_csv_xlsx_and_row_errors():
 for name,data in [('p.csv',csvdata([P])),('p.xlsx',workbook())]:
  r=price_intake.parse_prices(name,data);assert not r['errors'] and r['rows'][0]['price']['part']=='000001'
 assert price_intake.parse_prices('p.xlsx',workbook(True))['errors']
 assert price_intake.parse_prices('p.csv',csvdata([P,P]))['errors'][0]['line']==3
 for key,value in [('amount',''),('currency','XYZ'),('valid_until','2025-01-01'),('amount','NaN')]:assert price_intake.parse_prices('p.csv',csvdata([{**P,key:value}]))['errors']
 with pytest.raises(ValueError):price_intake.parse_prices('p.xlsx',b'broken')

@pytest.fixture
def env(tmp_path,monkeypatch):
 monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'test.sqlite')
 with TestClient(main.app) as h:yield h,tmp_path

def test_review_atomic_versions_original_and_html_guards(env):
 h,root=env;c=h.post('/api/import',files={'file':('base.eml',b'Subject: synthetic\nContent-Type: text/plain\n\n'+B)}).json();id=c['id']
 def post(route,values):
  nonlocal c
  r=h.post(f'/api/cases/{id}/'+route,json={'revision':c['revision'],'values':values});assert r.status_code==200,r.text;c=r.json()
 def preview(data):return h.post(f'/api/cases/{id}/prices/import/preview',data={'revision':c['revision']},files={'file':('prices.csv',data)}).json()
 invalid=preview(csvdata([P,P]));old=deepcopy(c)
 r=h.post(f'/api/cases/{id}/prices/import/accept',json={'revision':c['revision'],'values':{'preview_id':invalid['id'],'mode':'replace','actor':'synthetic','reason':'synthetic'}});assert r.status_code==422 and h.get(f'/api/cases/{id}').json()==old
 good=preview(csvdata([P]));post('prices/import/accept',{'preview_id':good['id'],'mode':'replace','actor':'synthetic','reason':'explicit synthetic file review'})
 evidence=c['prices'][0]['evidence'];assert evidence['location']=='CSV / row 2'
 post('approve',{'actor':'synthetic'})
 r=h.get(f'/api/cases/{id}/export?format=html&revision={c["revision"]}');assert r.status_code==200 and '000001' in r.text and '24.70' in r.text and 'prices.csv' in r.text
 assert h.get(f'/api/cases/{id}/export?format=html').status_code==409
 assert h.get(f'/api/cases/{id}/export?format=html&revision=0').status_code==409
 path=root/'var/price-imports'/id/good['id']/'prices.csv';original=path.read_bytes();path.write_bytes(original+b'changed')
 assert h.get(f'/api/cases/{id}/export?format=html&revision={c["revision"]}').status_code==409
 path.write_bytes(original)
 post('prices',{'prices':[]});assert h.get(f'/api/cases/{id}/export?format=html&revision={c["revision"]}').status_code==409

def test_stale_preview_and_escaped_multicurrency():
 from apps.api.quote_html import render_quote
 row={'rfq':'0001','part':'<script>alert(1)</script>','quantity':'2','unit':'EA','condition':'FN','total':'10.00','approval':{'actor':'test','date':'2026-10-24'},'price':{**P,'amount':'5'}}
 html=render_quote({'case_id':'x','revision':2,'price_version':1,'label':'synthetic','rows':[row,{**row,'price':{**row['price'],'currency':'EUR'}}]})
 assert '<script>' not in html and '&lt;script&gt;' in html and 'USD 10.00' in html and 'EUR 10.00' in html

def test_stale_preview_append_conflict_and_input_integrity(env):
 h,root=env;c=h.post('/api/import',files={'file':('base.eml',b'Subject: synthetic\nContent-Type: text/plain\n\n'+B)}).json();id=c['id']
 def preview():return h.post(f'/api/cases/{id}/prices/import/preview',data={'revision':c['revision']},files={'file':('prices.csv',csvdata([P]))}).json()
 def accept(preview,mode='append'):
  return h.post(f'/api/cases/{id}/prices/import/accept',json={'revision':c['revision'],'values':{'preview_id':preview['id'],'mode':mode,'actor':'synthetic','reason':'explicit synthetic review'}})
 stale=preview();c=h.post(f'/api/cases/{id}/review',json={'revision':c['revision'],'values':{'note':'concurrent synthetic material review'}}).json()
 assert accept(stale).status_code==422 and not c['prices']
 good=preview();r=accept(good);assert r.status_code==200;c=r.json();before=deepcopy(c)
 conflict=preview();assert accept(conflict).status_code==422
 assert h.get(f'/api/cases/{id}').json()==before
 c=h.post(f'/api/cases/{id}/approve',json={'revision':c['revision'],'values':{'actor':'synthetic'}}).json()
 path=root/'var/uploads'/id/'base.eml';original=path.read_bytes();path.write_bytes(original+b' tampered')
 assert h.get(f'/api/cases/{id}/export?format=html&revision={c["revision"]}').status_code==409
 path.write_bytes(original)
 assert h.get(f'/api/cases/{id}/export?format=html&revision={c["revision"]}').status_code==200

def test_unresolved_rfq_conflict_cannot_render_html(env):
 h,_=env
 body=B+b'000001\t000001\t3\tEA\tFN\n'
 c=h.post('/api/import',files={'file':('conflict.eml',b'Subject: synthetic\nContent-Type: text/plain\n\n'+body)}).json();id=c['id']
 c=h.post(f'/api/cases/{id}/prices',json={'revision':c['revision'],'values':{'prices':[P]}}).json()
 assert any(row['conflict'] for row in c['rows'])
 assert h.post(f'/api/cases/{id}/approve',json={'revision':c['revision'],'values':{'actor':'synthetic'}}).status_code==422
 assert h.get(f'/api/cases/{id}/export?format=html&revision={c["revision"]}').status_code==409
