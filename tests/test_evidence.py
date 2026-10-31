from copy import deepcopy
from pathlib import Path
from io import BytesIO
import openpyxl
from apps.api.parsing import parse_file
from evals.judges.evidence import EvidenceIndex
from evals.judges.objective import judge

ROOT=Path(__file__).resolve().parents[1]

def sample():
    data=(ROOT/'data/synthetic/demo.eml').read_bytes()
    index=EvidenceIndex();index.add('demo.eml',data)
    rows=parse_file('demo.eml',data)['rows']
    actual=[{**r['fields'],'sources':[r['source']],'status':'ready','total':'98.80'} for r in rows[:1]]
    expected={'rows':[{'rfq':'000101','part':'SYN-001','quantity':'8','unit':'EA','condition':'FN','status':'ready','total':'98.80','source_required':True}],'export_allowed':False}
    return index,rows,actual,expected

def test_supported_value_and_blanket_refusal():
    index,_,rows,gold=sample()
    result=judge(gold,{'rows':rows,'export_allowed':False},index)
    assert result['passed'] and result['completion_coverage']==1 and result['field_source_support']==1
    refusal=judge(gold,{'rows':[],'export_allowed':False},index)
    assert not refusal['passed'] and refusal['completion_coverage']==0

def test_forged_hash_wrong_row_and_forged_snippet():
    index,parsed,rows,gold=sample()
    for alteration in ('hash','wrong-row','snippet','value'):
        bad=deepcopy(rows)
        if alteration=='hash':bad[0]['sources'][0]['sha256']='0'*64
        if alteration=='wrong-row':bad[0]['sources']=[parsed[3]['source']]
        if alteration=='snippet':bad[0]['sources'][0]['raw'][3]='999'
        if alteration=='value':bad[0]['quantity']='999'
        assert not judge(gold,{'rows':bad,'export_allowed':False},index)['passed'],alteration

def test_cannot_assemble_correct_row_from_multiple_bad_candidates():
    index,_,rows,gold=sample();other=deepcopy(rows[0]);other['total']='98.81';rows[0]['quantity']='999';rows.append(other)
    result=judge(gold,{'rows':rows,'export_allowed':False},index)
    assert not result['passed'] and 'unexpected_or_duplicate_rows' in result['errors']

def test_control_center_exact_false_positive_regression():
    gold={'rows':[{'rfq':'R1','part':'P1','status':'ready','quantity':'1','unit':'EA','condition':'FN','total':'10','source_required':True}],'export_allowed':True}
    rows=[{'rfq':'R1','part':'P1','status':'ready','quantity':'2','unit':'EA','condition':'FN','total':'20','sources':['nonexistent']},
          {'rfq':'R1','part':'P1','status':'clarify','quantity':'1','unit':'IN','condition':'SV','total':'10','sources':[]}]
    result=judge(gold,{'rows':rows,'export_allowed':True},EvidenceIndex())
    assert not result['passed'] and result['field_source_support']==0

def test_precise_identifiers_and_missing_price_clarification():
    w=openpyxl.Workbook();s=w.active;s.append(['RFQ No.','Part Number','Quantity','Unit','Condition']);s.append(['00001',12,3,'EA','FN']);s['B2'].number_format='00000';b=BytesIO();w.save(b)
    index=EvidenceIndex();index.add('zeros.xlsx',b.getvalue());item=parse_file('zeros.xlsx',b.getvalue())['rows'][0]
    assert index.verify('part','00012',[item['source']])['supported']
    assert not index.verify('part','12',[item['source']])['supported']
    row={**item['fields'],'sources':[item['source']],'status':'unpriced','total':None}
    gold={'rows':[{**item['fields'],'status':'unpriced','forbid_total':True,'source_required':True}],'export_allowed':False}
    result=judge(gold,{'rows':[row],'export_allowed':False},index)
    assert result['passed'] and result['correct_clarification_rate']==1
    row['total']='0';assert not judge(gold,{'rows':[row],'export_allowed':False},index)['passed']

def test_pdf_page_citation_cannot_point_to_other_item():
    files=list((ROOT/'data/raw').rglob('*.pdf'))
    if not files:return
    p=files[0];index=EvidenceIndex();index.add(p.name,p.read_bytes());rows=parse_file(p.name,p.read_bytes())['rows']
    assert index.verify('part',rows[-1]['fields']['part'],[rows[-1]['source']])['supported']
    assert not index.verify('part',rows[-1]['fields']['part'],[rows[0]['source']])['supported']

def test_price_evidence_and_stale_approval_rejected():
    import json
    from evals.baselines.protocol import run
    from evals.baselines.fixture_transport import ScriptedTransport
    task=json.loads((ROOT/'evals/cases/tasks/lifecycle.json').read_text(encoding='utf-8-sig'))
    cfg=json.loads((ROOT/'evals/configs/strong-agent.json').read_text(encoding='utf-8-sig'))
    report=run(task,ScriptedTransport(),cfg)
    gold=json.loads((ROOT/'evals/gold/lifecycle.json').read_text(encoding='utf-8-sig'))['checkpoints'][-1]
    p=ROOT/task['files'][0];index=EvidenceIndex();index.add(p.name,p.read_bytes())
    actual=report['checkpoints'][-1]['output'];prices={'records':task['events'][-1]['prices'],'as_of':task['as_of']}
    assert judge(gold,actual,index,prices)['passed']
    for mode in ('wrong_amount','wrong_price_hash','stale_snapshot','stale_approval'):
        bad=deepcopy(actual)
        if mode=='wrong_amount':bad['rows'][0]['price']['amount']='0.01'
        if mode=='wrong_price_hash':bad['rows'][0]['price_source']['sha256']='0'*64
        if mode=='stale_snapshot':bad['approval_snapshot']=report['checkpoints'][0]['output']['approval_snapshot']
        if mode=='stale_approval':bad['rows'][0]['approval']['answer_id']='SYN-AUTH-1'
        assert not judge(gold,bad,index,prices)['passed'],mode
