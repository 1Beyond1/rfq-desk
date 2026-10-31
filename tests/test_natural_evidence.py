from pathlib import Path
from copy import deepcopy
import pytest
from apps.api.materials import read_materials
from apps.api import semantic
from apps.api.domain import new_case
from evals.judges.evidence import EvidenceIndex
ROOT=Path(__file__).resolve().parents[1]
def fixture(tmp_path):
    body=(ROOT/'data/synthetic/model-live-20261027/normal.txt').read_bytes()
    (tmp_path/'normal.txt').write_bytes(body)
    m=read_materials(tmp_path);f=m['files'][0];fields={}
    for k,v in {'rfq':'009731','part':'DEV-A731','quantity':'4','unit':'EA','condition':'FN','due':'2027-02-08'}.items():
        u=next(u for u in f['units'] if v in u['text']);a=u['text'].index(v)
        fields[k]={'value':v,'evidence':{key:u[key] for key in ('file','sha256','location')}|{'start':a,'end':a+len(v),'quote':v}}
    c=new_case('test',{'rows':[],'warnings':[],'fragments':[]});candidate=semantic.validate_payload({'candidates':[{'fields':fields}]},m)[0]
    b={'expected_revision':1,'snapshot':m['snapshot'],'status':'pending','id':'test','candidates':[candidate]}
    return c,b,candidate,m,body
def test_prose_roles_and_authorized_correction(tmp_path):
    c,b,x,m,body=fixture(tmp_path);semantic.accept_candidate(c,b,x,m,{'actor':'DEV','reason':'independent synthetic review','confirm_association':True,'fields':{'quantity':'6'}})
    row=c['rows'][0];index=EvidenceIndex();index.add('normal.txt',body)
    for f in row['raw_fields']:assert index.verify_claim(row,f,{d['id']:d for d in c['human_decisions']})['supported'],f
    assert index.verify_claim(row,'quantity',{})['supported'] is False
    assert not index.verify('priority','4',row['sources'])['supported']
    row['field_provenance']['quantity']['decision_id']='forged'
    assert not index.verify_claim(row,'quantity',{d['id']:d for d in c['human_decisions']})['supported']
def test_wrong_request_and_ambiguous_clauses(tmp_path):
    c,b,x,m,body=fixture(tmp_path);semantic.accept_candidate(c,b,x,m,{'actor':'DEV','reason':'review','confirm_association':True})
    row=c['rows'][0];other=body.replace(b'009731',b'009732')
    index=EvidenceIndex();index.add('normal.txt',body);index.add('other.txt',other)
    import hashlib
    cite=deepcopy(row['field_provenance']['quantity']['sources'][0]);cite.update(file='other.txt',sha256=hashlib.sha256(other).hexdigest());row['field_provenance']['quantity']['sources']=[cite]
    assert not index.verify_claim(row,'quantity')['supported']
    ambiguous=body+b'We require 8 EA in FN condition by 2027-02-08.\n';idx=EvidenceIndex();idx.add('normal.txt',ambiguous)
    assert not idx.bindings
def test_revisions_need_explicit_target(tmp_path):
    c,b,x,m,body=fixture(tmp_path);v={'actor':'DEV','reason':'review','confirm_association':True};semantic.accept_candidate(c,b,x,m,v)
    x=deepcopy(x);x['status']='pending';b.update(expected_revision=1,status='pending',candidates=[x])
    with pytest.raises(ValueError,match='目标'):semantic.accept_candidate(c,b,x,m,v)

def test_priority_and_cross_revision_cannot_be_quantity(tmp_path):
    c,b,x,m,body=fixture(tmp_path)
    text=body.decode()+'Priority: 3\n'+body.decode().replace('009731','009732').replace('require 4','require 8')
    (tmp_path/'normal.txt').write_text(text,encoding='utf-8');m=read_materials(tmp_path)
    base={f:{'value':v,'evidence':{k:x['field_sources'][f][k] for k in ('file','sha256','location','start','end','quote')}} for f,v in x['fields'].items()}
    # Update hash for original prefix without changing offsets; then attempt two attacks.
    sha=m['files'][0]['sha256']
    for f in base.values():f['evidence']['sha256']=sha
    for unit,value in [(next(u for u in m['files'][0]['units'] if u['text']=='Priority: 3'),'3'),(next(u for u in m['files'][0]['units'] if 'require 8' in u['text']),'8')]:
        bad=deepcopy(base);a=unit['text'].index(value);bad['quantity']={'value':value,'evidence':{k:unit[k] for k in ('file','sha256','location')}|{'start':a,'end':a+len(value),'quote':value}}
        with pytest.raises(ValueError):semantic.validate_payload({'candidates':[{'fields':bad}]},m)
