"""Independent in-memory development probes. No product parser or reserved/gold inputs."""
from copy import deepcopy
from email.message import EmailMessage
from evals.judges.evidence import EvidenceIndex
from evals.judges.objective import judge

def probe(body,name='coordinator-probe.eml'):
 m=EmailMessage();m.set_content(body);index=EvidenceIndex();index.add(name,m.as_bytes());return index

def citation(index,line,field,value):
 unit=next(u for u in index.units.values() if u['location']==f'MIME body / line {line}')
 start=unit['text'].rindex(value)
 return {k:unit[k] for k in ('file','sha256','location')}|{'kind':'literal_span','field':field,'start':start,'end':start+len(value),'quote':value}

def row(index,start=1,rfq='R1',part='P1'):
 f={'rfq':rfq,'part':part,'quantity':'3','unit':'EA','condition':'FN'}
 return {'id':'test-row',**f,'status':'unpriced','sources':[citation(index,start+n,k,v) for n,(k,v) in enumerate(f.items())]}

def gold(r,binding=None,mode=None):
 result={'rows':[{k:r[k] for k in ('rfq','part','quantity','unit','condition','status')}|{'source_required':True}],'export_allowed':False}
 if binding:result['rows'][0]['source_binding']=binding
 if mode:result['rows'][0]['evidence_modes']=mode
 return result

def score(index,r,expected=None,auth=None):return judge(expected or gold(r),{'rows':[r],'export_allowed':False},index,authorizations=auth)

BODY='RFQ: R1\nPart: P1\nQuantity: 3\nUnit: EA\nCondition: FN\nPriority: 3\nRFQ: R2\nPart: P2\nQuantity: 3\nUnit: EA\nCondition: FN\n'

def test_coordinator_exact_priority_and_other_request_false_normal_true():
 index=probe(BODY);r=row(index)
 assert score(index,r)['passed']
 for line in (6,9):
  bad=deepcopy(r);bad['sources'][2]=citation(index,line,'quantity','3')
  result=score(index,bad)
  assert not result['passed'] and result['field_source_support']<1

def test_duplicate_same_key_and_equal_revision_values_need_trusted_occurrence():
 for body in ('RFQ: R1\nPart: P1\nQuantity: 3\nUnit: EA\nCondition: FN\nRFQ: R1\nPart: P1\nQuantity: 3\nUnit: EA\nCondition: FN\n',
              'RFQ: R1\nPart: P1\nQuantity: 3\nUnit: EA\nCondition: FN\nPart: P1\nQuantity: 3\nUnit: EA\nCondition: FN\n'):
  index=probe(body);r=row(index)
  binding=next(v['binding'] for v in index.bindings.values())
  expected=gold(r,binding)
  assert score(index,r,expected)['passed']
  assert not score(index,r)['passed'] # occurrence selection is not inferable from equal business keys
  second_quantity=next(u for u in reversed(list(index.units.values())) if u.get('label_field')=='quantity')
  bad=deepcopy(r);n=int(second_quantity['location'].split()[-1]);bad['sources'][2]=citation(index,n,'quantity','3')
  assert not score(index,bad,expected)['passed']
  # Swapping the entire occurrence is also wrong, even if all values are identical.
  second_binding=list(index.bindings.values())[-1]['binding']
  other=[]
  for f,v in ((f,r[f]) for f in ('rfq','part','quantity','unit','condition')):
   u=next(u for u in index.units.values() if second_binding in u['bindings'] and u.get('label_field')==f)
   other.append(citation(index,int(u['location'].split()[-1]),f,v))
  bad['sources']=other;assert not score(index,bad,expected)['passed']
  assert score(index,bad,gold(bad,second_binding))['passed']

def test_unlabelled_natural_language_unverified_not_supported():
 index=probe('For R1 please send P1, three pieces; number 3 below is only a note.\n')
 unit=next(iter(index.units.values()));start=unit['text'].index('3')
 cite={k:unit[k] for k in ('file','sha256','location')}|{'kind':'literal_span','field':'quantity','quote':'3','start':start,'end':start+1}
 assert not index.verify('quantity','3',[cite])['supported']
 r={'id':'test-row','rfq':'R1','part':'P1','quantity':'3','unit':'EA','condition':'FN','status':'unpriced','sources':[cite]}
 result=score(index,r);assert not result['passed'] and result['unverified_semantic_fields']==5

def test_external_cross_document_human_adjudication_is_not_source():
 index=probe(BODY);other=EmailMessage();other.set_content('RFQ: R9\nPart: P9\nQuantity: 3\nUnit: EA\nCondition: FN\n');index.add('human-confirmation.eml',other.as_bytes())
 r=row(index);unit=next(u for u in index.units.values() if u['file']=='human-confirmation.eml' and u.get('label_field')=='quantity')
 cite={k:unit[k] for k in ('file','sha256','location')}|{'kind':'literal_span','field':'quantity','start':unit['value_span'][0],'end':unit['value_span'][1],'quote':'3'}
 r['quantity']='4';r['field_provenance']={'quantity':{'kind':'human','original_value':'3','sources':[cite],'decision_id':'decision-1'}}
 binding=unit['bindings'][0]
 auth={'decision-1':{'kind':'authorized_human','row_id':r['id'],'field':'quantity','from':'3','to':'4','actor':'authorized reviewer','reason':'Explicitly applies cross-document confirmation to R1/P1','source_binding':binding}}
 expected=gold(r,mode={'quantity':'human'})
 assert not score(index,r,expected)['passed']
 result=score(index,r,expected,auth)
 assert result['passed'] and result['authorized_human_fields']==1 and result['verified_source_fields']==4
 assert result['field_source_support']==.8
 wrong=deepcopy(auth);wrong['decision-1']['source_binding']={'file':'wrong','sha256':'wrong','record_id':'wrong'}
 assert not score(index,r,expected,wrong)['passed']
 no_id=deepcopy(r);no_id.pop('id');wrong=deepcopy(auth);wrong['decision-1']['row_id']=None
 assert not score(index,no_id,expected,wrong)['passed']

def test_malformed_citations_and_provenance_never_crash():
 index=probe(BODY);r=row(index)
 for sources in (None,{},['nonexistent'],[{'kind':'literal_span','file':[],'sha256':{},'location':None}], [{**r['sources'][2],'start':True}], [{**r['sources'][2],'quote':[]} ]):
  bad=deepcopy(r);bad['sources']=sources;assert not score(index,bad)['passed']
 for value in (None,[],{'quantity':None},{'quantity':{'kind':'human','decision_id':[]}}):
  bad=deepcopy(r);bad['field_provenance']=value;assert not score(index,bad)['passed']


def test_explicit_external_human_resolution_without_invented_source():
 index=probe(BODY);r=row(index);r['quantity']='4'
 r['field_provenance']={'quantity':{'kind':'human','original_value':'','sources':[],'decision_id':'manual-new'}}
 auth={'manual-new':{'kind':'authorized_human','row_id':r['id'],'field':'quantity','from':'','to':'4','actor':'reviewer','reason':'External authorized quantity confirmation, no original text claim'}}
 expected=gold(r,mode={'quantity':'human'})
 result=score(index,r,expected,auth)
 assert result['passed'] and result['authorized_human_fields']==1 and result['verified_source_fields']==4
 assert not score(index,r,expected)['passed']
