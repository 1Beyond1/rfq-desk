"""Build authored synthetic task families; reserved packs are not evaluated here."""
from pathlib import Path
from email.message import EmailMessage
import hashlib,json
import openpyxl
ROOT=Path(__file__).resolve().parents[1]
public=ROOT/'data/synthetic/tasks';public.mkdir(parents=True,exist_ok=True)
tasks=ROOT/'evals/cases/tasks';tasks.mkdir(parents=True,exist_ok=True)
reserved=ROOT/'evals/cases/reserved';reserved.mkdir(parents=True,exist_ok=True)
gold=ROOT/'evals/gold';gold.mkdir(parents=True,exist_ok=True)
def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def price(amount):return {'part':'EVT-001','unit':'EA','condition':'FN','currency':'USD','amount':amount,'valid_from':'2026-01-01','valid_until':'2027-12-31','lead_time':'synthetic 7 days','source':'SYN-EVENT-CATALOG','kind':'synthetic'}
m=EmailMessage();m['Subject']='Synthetic event replay';m.set_content('RFQ No.\tPart Number\tQuantity\tUnit\tCondition\n000201\tEVT-001\t3\tEA\tFN\n000202\tEVT-001\t2\tEA\tFN\n')
(public/'lifecycle.eml').write_bytes(m.as_bytes())
events=[{'id':'initial','instruction':'核验并询问当前快照批准','price_version':1,'prices':[price('10.00')],'answers':{'approve':{'id':'SYN-AUTH-1','actor':'synthetic reviewer','approved_price_version':1}}},
{'id':'price_change_missing','instruction':'供应商撤回价格；旧批准不可导出，澄清缺价','price_version':2,'prices':[],'answers':{'price':{'id':'SYN-CLAR-2','status':'unavailable','text':'尚无新报价，不得猜测'}}},
{'id':'new_price','instruction':'提供新价格，需重新批准','price_version':3,'prices':[price('12.50')],'answers':{'approve':{'id':'SYN-AUTH-3','actor':'synthetic reviewer','approved_price_version':3}}}]
task={'id':'DEV-EVENT-01','family':'authored-tsv-lifecycle','lineage':'synthetic-original-lifecycle-v1','split':'dev','title':'合成报价撤回及重新批准事件','as_of':'2026-10-22','files':['data/synthetic/tasks/lifecycle.eml'],'events':events}
write(tasks/'lifecycle.json',task)
expected=[]
for event in events:
 ready=bool(event['prices']);expected.append({'stage':len(expected),'rows':[{'rfq':rfq,'part':'EVT-001','quantity':qty,'unit':'EA','condition':'FN','status':'ready' if ready else 'unpriced','total':str(__import__('decimal').Decimal(qty)*__import__('decimal').Decimal(event['prices'][0]['amount'])) if ready else None,'forbid_total':not ready,'source_required':True,'approval':{'price_version':event['price_version'],'answer_id':event['answers']['approve']['id']} if ready else {}} for rfq,qty in [('000201','3'),('000202','2')]],'export_allowed':ready,'approval_snapshot':hashlib.sha256(json.dumps(event['prices'],ensure_ascii=False,sort_keys=True).encode()).hexdigest() if ready else None})
write(gold/'lifecycle.json',{'task_id':task['id'],'checkpoints':expected})
# Existing mixed HTML case stays in one dev family; no numeric variants count as new tasks.
write(tasks/'mixed.json',{'id':'DEV-MIXED-01','family':'authored-html-duplicate-conflict','lineage':'synthetic-demo-v1','split':'dev','title':'合成重复与数量冲突','as_of':'2026-10-22','files':['data/synthetic/demo.eml'],'events':[{'id':'initial','instruction':'保留独立询价，重复/冲突必须澄清','price_version':1,'prices':[],'answers':{}}]})
# Reserve different constructed structures without invoking parser, product, judge or transport.
w=openpyxl.Workbook();w.active.title='Request';w.active.append(['RFQ No.','Part Number','Quantity','Unit','Condition']);w.active.append(['000701','HOLD-CLIP','2','FT','OH']);s=w.create_sheet('Amendment');s.append(['RFQ No.','Part Number','Quantity','Unit','Condition']);s.append(['000701','HOLD-CLIP','2','IN','OH']);w.save(public/'reserved-multisheet.xlsx')
fwd=EmailMessage();fwd['Subject']='Synthetic forwarded packet';fwd.set_content('See nested RFQ. Unclear revision precedence requires clarification.');inner=EmailMessage();inner['Subject']='RFQ-777';inner.set_content('RFQ No.\tPart Number\tQuantity\tUnit\tCondition\n000801\tHOLD-PIN\t4\tEA\tSV\n');fwd.add_attachment(inner);(public/'reserved-forward.eml').write_bytes(fwd.as_bytes())
reserved_entries=[]
for name,family in [('reserved-multisheet.xlsx','cross-sheet-unit-amendment'),('reserved-forward.eml','nested-rfc822-precedence')]:
 obj={'id':'RESERVE-'+str(len(reserved_entries)+1),'family':family,'lineage':'authored-reserve-'+family,'split':'reserved','state':'unexecuted-not-blind-to-author','title':'Reserved synthetic structure','as_of':'2026-10-22','files':['data/synthetic/tasks/'+name],'events':[{'id':'initial','price_version':0,'prices':[],'answers':{}}]};write(reserved/(family+'.json'),obj);reserved_entries.append({'id':obj['id'],'family':family,'file_sha256':hashlib.sha256((public/name).read_bytes()).hexdigest(),'task':str((reserved/(family+'.json')).relative_to(ROOT))})
write(gold/'reserve-cross-sheet.json',{'task_id':'RESERVE-1','review_state':'author-defined-needs-independent-review','checkpoints':[{'stage':0,'rows':[{'rfq':'000701','part':'HOLD-CLIP','quantity':'2','unit':u,'condition':'OH','status':'clarify','forbid_total':True,'source_required':True} for u in ('FT','IN')],'export_allowed':False}]})
write(gold/'reserve-forward.json',{'task_id':'RESERVE-2','review_state':'author-defined-needs-independent-review','checkpoints':[{'stage':0,'rows':[{'rfq':'000801','part':'HOLD-PIN','quantity':'4','unit':'EA','condition':'SV','status':'unpriced','forbid_total':True,'source_required':True}],'export_allowed':False}]})
write(ROOT/'evals/cases/challenge_manifest.json',{'origin':'authored synthetic tasks, not independently sampled customers','dev':[{'task':'evals/cases/tasks/lifecycle.json','family':task['family'],'risk':['missing price','approval invalidation','reclarify','reapprove']},{'task':'evals/cases/tasks/mixed.json','family':'authored-html-duplicate-conflict','risk':['duplicate block','same part different RFQ','conflicting quantity']}],'reserved':reserved_entries,'reserve_policy':'No parser/product/agent/judge runs on reserved packs before configuration freeze. Author knows generation templates; do not claim blind holdout. Gold for reserved tasks is author-defined in judge-only files and requires independent review before release. Official two groups/derivatives are local development evidence, never heldout because previously inspected.'})
print('Wrote 2 dev tasks + 2 unexecuted synthetic reserves; no benchmark run')
