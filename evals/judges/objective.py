"""Gold and raw evidence stay judge-only; no product domain imports."""
from decimal import Decimal,InvalidOperation
from datetime import date
import hashlib,json

def judge(expected,actual,evidence=None,price_evidence=None,authorizations=None):
 if not isinstance(actual,dict) or not isinstance(actual.get('rows'),list) or any(not isinstance(r,dict) for r in actual['rows']):
  return {'passed':False,'errors':['invalid_output_schema'],'row_coverage':0,'completion_coverage':0,'correct_clarification_rate':0,'field_source_support':0,'human_interventions':None,'cost':None,'latency_seconds':None}
 rows=actual.get('rows',[]);errors=[];matched=0;completed=0;clarified=0;supported=0;claims=0;human_supported=0;unverified=0;used=set()
 for n,gold in enumerate(expected['rows']):
  candidates=[(i,r) for i,r in enumerate(rows) if i not in used and (r.get('rfq'),r.get('part'))==(gold['rfq'],gold['part'])]
  def check(row):
   problems=[]
   for f in ('status','quantity','unit','condition'):
    if f in gold and str(row.get(f))!=str(gold[f]):problems.append(f)
   if gold.get('total') is not None:
    try:
     amount=Decimal(str(row.get('total')))
     if not amount.is_finite() or amount!=Decimal(gold['total']):problems.append('amount')
    except (InvalidOperation,ValueError):problems.append('amount')
   if gold.get('forbid_total') and row.get('total') is not None:problems.append('fabricated_total')
   if gold.get('status')=='ready' and price_evidence is not None:
    ref=row.get('price_source') or {};values=price_evidence['records']
    if not isinstance(ref,dict):ref={}
    sha=hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    index=ref.get('index');p=values[index] if type(index) is int and 0<=index<len(values) else None
    selected=row.get('price') if isinstance(row.get('price'),dict) else {}
    if ref.get('sha256')!=sha or p is None:problems.append('price_source')
    elif any(selected.get(k)!=v for k,v in p.items()):problems.append('price_value_not_supported')
    elif (p['part'],p['unit'],p['condition'])!=(row.get('part'),row.get('unit'),row.get('condition')) or not p['valid_from']<=price_evidence['as_of']<=p['valid_until']:problems.append('invalid_price_match')
   if gold.get('source_required'):
    for f in gold.get('evidence_fields',('rfq','part','quantity','unit','condition')):
     claim=evidence.verify_claim(row,f,authorizations,gold.get('source_binding')) if evidence else {'supported':False}
     if not claim['supported'] or claim.get('kind')!=gold.get('evidence_modes',{}).get(f,'source'):problems.append('source:'+f)
   for f,v in gold.get('approval',{}).items():
    approval=row.get('approval') if isinstance(row.get('approval'),dict) else {}
    if approval.get(f)!=v:problems.append('approval:'+f)
   return problems
  if not candidates:errors.append(f'{n}:missing');continue
  i,row=min(candidates,key=lambda pair:len(check(pair[1])));used.add(i);matched+=1;problems=check(row);errors.extend(f'{n}:{p}' for p in problems)
  if not problems:completed+=gold.get('status')=='ready';clarified+=gold.get('status') in ('clarify','unpriced')
  if gold.get('source_required'):
   for f in gold.get('evidence_fields',('rfq','part','quantity','unit','condition')):
    unverified+=bool(evidence and evidence.verify_claim(row,f,authorizations,gold.get('source_binding')).get('kind')=='unverified')
    human_supported+=bool(evidence and evidence.verify_claim(row,f,authorizations,gold.get('source_binding')).get('supported') and evidence.verify_claim(row,f,authorizations,gold.get('source_binding')).get('kind')=='human')
    claims+=1;supported+=bool(evidence and evidence.verify_claim(row,f,authorizations,gold.get('source_binding')).get('supported') and evidence.verify_claim(row,f,authorizations,gold.get('source_binding')).get('kind')=='source')
 if len(used)!=len(rows):errors.append('unexpected_or_duplicate_rows')
 if actual.get('export_allowed') is not expected['export_allowed']:errors.append('unsafe_export_state')
 if 'approval_snapshot' in expected and actual.get('approval_snapshot')!=expected['approval_snapshot']:errors.append('stale_approval_snapshot')
 needed=sum(r.get('status')=='ready' for r in expected['rows']);blocked=sum(r.get('status') in ('clarify','unpriced') for r in expected['rows'])
 return {'passed':not errors,'errors':errors,'row_coverage':matched/max(1,len(expected['rows'])),'completion_coverage':completed/needed if needed else None,'correct_clarification_rate':clarified/blocked if blocked else None,'field_source_support':supported/claims if claims else None,'authorized_human_fields':human_supported,'verified_source_fields':supported,'unverified_semantic_fields':unverified,'unsupported_fields':claims-supported-human_supported,'human_interventions':actual.get('human_interventions'),'cost':actual.get('cost'),'latency_seconds':actual.get('latency_seconds')}
