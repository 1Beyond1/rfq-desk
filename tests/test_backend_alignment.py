from copy import deepcopy
from email.message import EmailMessage
from pathlib import Path
import json
import shutil
import subprocess
import pytest
from fastapi.testclient import TestClient
from apps.api import main
from apps.api.materials import read_materials

ROOT=Path(__file__).resolve().parents[1]
PRICE={'part':'CLARIFY-001','unit':'EA','condition':'FN','currency':'USD','amount':'13.00','valid_from':'2026-01-01','valid_until':'2030-12-31','lead_time':'synthetic 7 days','source':'SYN-BACKEND-CARD','kind':'synthetic'}
BASE=b'Subject: Synthetic backend\nContent-Type: text/plain\n\nRFQ No.\tPart Number\tQuantity\tUnit\tCondition\n009401\tCLARIFY-001\t2\tEA\tFN\n009402\tCLARIFY-001\t3\tEA\tFN\n'

@pytest.fixture
def h(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'test.sqlite')
    with TestClient(main.app) as client:yield client

def create(h,data=BASE):
    r=h.post('/api/import',files={'file':('backend.eml',data)});assert r.status_code==200,r.text
    return r.json()

def post(h,c,path,values,status=200):
    r=h.post(f"/api/cases/{c['id']}/"+path,json={'revision':c['revision'],'values':values})
    assert r.status_code==status,r.text
    return r.json() if status==200 else r


def test_exact_material_aliases_plain_html_and_alternative_no_value_guess(h):
    c=create(h)
    old_sources=deepcopy(c['rows'][0]['sources'])
    m=h.get(f"/api/cases/{c['id']}/materials").json()
    canonical=read_materials(main.ROOT/'var/uploads'/c['id'])
    assert m['snapshot']==canonical['snapshot']
    assert all(u.get('kind')!='source_row' for f in canonical['files'] for u in f['units'])
    assert next(u for u in m['files'][0]['units'] if u['location']=='MIME text / row 2')['text'].startswith('009401\t')
    assert h.get(f"/api/cases/{c['id']}").json()['rows'][0]['sources']==old_sources
    msg=EmailMessage();msg['Subject']='synthetic alternative';msg.set_content(BASE.decode().split('\n\n')[1])
    table='<table><tr><th>RFQ No.</th><th>Part Number</th><th>Quantity</th><th>Unit</th><th>Condition</th></tr><tr><td>000007</td><td>SAME-001</td><td>2</td><td>EA</td><td>FN</td></tr><tr><td>000007</td><td>SAME-001</td><td>2</td><td>EA</td><td>FN</td></tr></table>'
    msg.add_alternative('<html>'+table+table+'</html>',subtype='html')
    c=create(h,msg.as_bytes());assert len(c['rows'])==4
    m=h.get(f"/api/cases/{c['id']}/materials").json()
    ids=[]
    for row in c['rows']:
        src=row['sources'][0]
        hits=[u for f in m['files'] if f['file']==src['file'] and f['sha256']==src['sha256'] for u in f['units'] if u['location']==src['location']]
        assert len(hits)==1 and hits[0]['kind']=='source_row'
        assert hits[0]['text']=='000007\tSAME-001\t2\tEA\tFN'
        ids.append(hits[0]['unit_id'])
    assert len(set(ids))==4 # Identical values, distinct table/row structural positions.
    assert m['source_mapping_errors']==[]


def test_attachment_existing_xlsx_locations_exposed_without_changing_citations(h):
    from io import BytesIO
    from openpyxl import Workbook
    b=Workbook();b.active.append(['RFQ No.','Part Number','Quantity','Unit','Condition']);b.active.append(['0007','SYN-001',2,'EA','FN'])
    out=BytesIO();b.save(out)
    msg=EmailMessage();msg.set_content('synthetic attachment');msg.add_attachment(out.getvalue(),maintype='application',subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename='rows.xlsx')
    c=create(h,msg.as_bytes());src=c['rows'][0]['sources'][0]
    assert src['file']=='backend.eml > rows.xlsx'
    m=h.get(f"/api/cases/{c['id']}/materials").json()
    file=next(f for f in m['files'] if f['file']==src['file'])
    # The header row is a unit too now; the cited row must be among them under the same name.
    assert file['sha256']==src['sha256'] and any(u['location']==src['location'] for u in file['units'])


def test_targeted_registration_legacy_summary_codes_and_noop(h):
    data=(ROOT/'data/synthetic/clarification/roundtrip.eml').read_bytes();c=create(h,data)
    before=c['revision'];row=c['rows'][0]
    c=post(h,c,'clarifications/register',{'row_id':row['id']})
    assert c['revision']==before+1 and len(c['clarifications'])==1 and c['clarifications'][0]['row_id']==row['id']
    unchanged=post(h,c,'clarifications/register',{'row_id':row['id']});assert unchanged==c
    post(h,c,'clarifications/register',{'row_id':'missing'},422)
    assert h.get(f"/api/cases/{c['id']}").json()==c
    c=post(h,c,'clarifications/register',{});assert len(c['clarifications'])==2
    assert c['progress']['active']==2 and c['progress']['approved']==0 and c['progress']['open_clarifications']==2
    assert c['progress']['open_issues']==sum(len(r['issues']) for r in c['rows'])
    summary=next(x for x in h.get('/api/cases').json() if x['id']==c['id'])
    assert all(summary[k]==v for k,v in c['progress'].items())
    assert c['rows'][0]['issues']==['缺少单位','缺少唯一有效价格依据',f"澄清未解决：unit / {c['clarifications'][0]['id']}"]
    assert [i['message'] for i in c['rows'][0]['issue_codes']]==c['rows'][0]['issues']
    assert c['rows'][0]['issue_codes'][0]['code']=='missing_field' and c['rows'][0]['issue_codes'][0]['field']=='unit'
    r=h.patch(f"/api/cases/{c['id']}/rows/{row['id']}",json={'revision':c['revision'],'values':{'excluded':True,'reason':'synthetic excluded target'}}).json()
    assert r['progress']['active']==1 and r['progress']['open_clarifications']==1 and r['progress']['all_open_clarifications']==2


def test_rejected_reply_records_conclusion_but_cannot_resolve_and_regeneration_is_pending(h):
    c=create(h,(ROOT/'data/synthetic/clarification/roundtrip.eml').read_bytes())
    c=post(h,c,'clarifications/register',{});q=c['clarifications'][0]
    r=h.post(f"/api/cases/{c['id']}/materials",data={'revision':c['revision']},files={'file':('insufficient.txt',(ROOT/'data/synthetic/clarification/insufficient.txt').read_bytes())});c=r.json()
    c=post(h,c,f"clarifications/{q['id']}/replies",{'filename':'insufficient.txt','reply_row_revision':1,'actor':'synthetic','reason':'receipt only'})
    q=c['clarifications'][0];reply=q['replies'][0]
    def propose(c):
        return post(h,c,'candidates/propose',{'mode':'offline'})['case']
    c=propose(c);b=c['candidate_batches'][-1];candidate=b['candidates'][0]
    route=f"candidates/{b['id']}/{candidate['id']}/review"
    values={'action':'reject','actor':'synthetic','reason':'no unit answer','clarification_id':q['id'],'reply_id':reply['id']}
    post(h,c,route,{**values,'reply_id':'other-reply'},422)
    c=post(h,c,route,values);q=c['clarifications'][0];reply=q['replies'][0]
    assert q['state']=='received' and reply['reviewed'] and reply['review_status']=='no_answer'
    assert reply['reviews'][0]['candidate_id']==candidate['id'] and reply['reviews'][0]['reason']=='no unit answer'
    assert not q['resolutions'] and not c['rows'][0]['unit']
    c=post(h,c,'prices',{'prices':[PRICE]});post(h,c,'approve',{'actor':'synthetic'},422)
    c=propose(c);reply=c['clarifications'][0]['replies'][0]
    assert reply['review_status']=='pending_review' and len(reply['reviews'])==1


def test_price_version_once_idempotent_full_case_and_409(h):
    c=create(h);rev=c['revision'];c=post(h,c,'prices',{'prices':[PRICE]})
    assert c['revision']==rev+1 and c['price_version']==1 and 'rows' in c and 'clarifications' in c
    assert post(h,c,'prices',{'prices':[PRICE]})==c
    old={**c,'revision':rev};post(h,old,'prices',{'prices':[]},409)
    c=post(h,c,'prices',{'prices':[{**PRICE,'amount':'14.00'}]});assert c['revision']==rev+2 and c['price_version']==2


def test_pure_preview_explicit_export_and_legacy_audit_preserve_approval_version(h):
    c=post(h,create(h),'prices',{'prices':[PRICE]});c=post(h,c,'approve',{'actor':'synthetic'})
    url=f"/api/cases/{c['id']}";before=h.get(url).json();revision=c['revision']
    for format in ('html','csv','json'):
        r=h.get(url+'/quote-preview',params={'format':format,'revision':revision});assert r.status_code==200
        assert h.get(url).json()==before
    assert h.get(url+'/quote-preview',params={'revision':revision-1}).status_code==409
    assert h.get(url+'/quote-preview').status_code==422
    assert h.get(url+'/quote-preview',params={'format':'pdf','revision':revision}).status_code==422
    for route in ('exports','export'):
        r=h.post(url+'/exports',json={'revision':revision,'values':{'format':'html'}}) if route=='exports' else h.get(url+'/export',params={'format':'html','revision':revision})
        assert r.status_code==200 and '65.00' in r.text and r.headers['x-rfq-business-revision']==str(revision)
        current=h.get(url).json();assert current['revision']==revision and all(r['approved'] for r in current['rows'])
        assert len(current['events'])==len(before['events'])+1;before=current
    c=post(h,current,'prices',{'prices':[{**PRICE,'amount':'14.00'}]})
    for path in ('quote-preview','export'):
        assert h.get(url+'/'+path,params={'format':'html','revision':c['revision']}).status_code==409
    assert h.post(url+'/exports',json={'revision':revision,'values':{'format':'csv'}}).status_code==409
    c=post(h,c,'approve',{'actor':'synthetic'})
    original=main.ROOT/'var/uploads'/c['id']/'backend.eml';original.write_bytes(original.read_bytes()+b'tampered')
    for path in ('quote-preview','export'):
        assert h.get(url+'/'+path,params={'format':'html','revision':c['revision']}).status_code==409
    assert h.post(url+'/exports',json={'revision':c['revision'],'values':{'format':'csv'}}).status_code==409


def test_start_script_does_not_require_git_or_ownership():
    shell=shutil.which('pwsh') or shutil.which('powershell')
    if not shell:pytest.skip('PowerShell not available on this host')
    script=str(ROOT/'scripts/start.ps1').replace("'","''")
    result=subprocess.run([shell,'-NoProfile','-Command',f"function git {{ throw 'Git must not be invoked' }}; & '{script}' api -CheckOnly"],capture_output=True,text=True,timeout=20)
    assert result.returncode==0 and 'Git not required' in result.stdout,result.stderr
