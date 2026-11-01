from pathlib import Path
from contextlib import contextmanager
from datetime import date
import json
import os
import sqlite3
import csv
import io
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from .parsing import parse_file
from . import price_intake, clarifications
from .quote_html import render_quote
from .materials import read_materials
from .semantic import get_adapter, propose, accept_candidate, synthetic_remote_allowed
from .domain import new_case, analyze, replace_prices, approve, export_data, event, FIELDS

ROOT = Path(__file__).resolve().parents[2]
DB = Path(os.getenv('RFQ_DB') or str(ROOT/'var/rfq.sqlite3'))
app = FastAPI(title='航材询报价工作台', version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5311','http://localhost:5311'], allow_methods=['GET','POST','PATCH'], allow_headers=['Content-Type'])

@contextmanager
def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as c:
        c.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        yield c

def save(c, case):
    c.execute('INSERT OR REPLACE INTO cases VALUES (?, ?)', (case['id'],json.dumps(case,ensure_ascii=False)))

def load(c, id):
    row = c.execute('SELECT body FROM cases WHERE id=?',(id,)).fetchone()
    if not row: raise HTTPException(404,'找不到工作单')
    return json.loads(row[0])

def view(case):
    from .model_config import ModelSettings
    settings=ModelSettings.from_env()
    rows=analyze(case)
    return {**case, 'rows':rows, 'clarifications':clarifications.listing(case), 'progress':progress(case,rows), 'mode':'model-live-local' if settings.configured and settings.enabled else 'offline-local'}

def progress(case,rows=None):
    rows=analyze(case) if rows is None else rows
    active=[r for r in rows if not r['excluded']];ids={r['id'] for r in active}
    questions=[q for q in clarifications.listing(case) if q['state'] not in ('resolved','superseded')]
    return {'active':len(active),'approved':sum(r['approved'] for r in active),
            'open_issues':sum(len(r['issues']) for r in active),'issue_rows':sum(bool(r['issues']) for r in active),
            'open_clarifications':sum(q['row_id'] in ids for q in questions),'all_open_clarifications':len(questions),
            'pending_parse_review':bool(case['warnings'] and not case.get('review_note')),
            'pending_candidates':sum(c['status']=='pending' for b in case.get('candidate_batches',[]) if b['expected_revision']==case['revision'] for c in b['candidates'])}

class Change(BaseModel):
    revision: int
    values: dict

def mutate(id, change, action):
    try:
        with connection() as c:
            c.execute('BEGIN IMMEDIATE')
            case = load(c,id)
            if change.revision != case['revision']: raise HTTPException(409,'工作单已更新，请刷新后重试')
            changed=action(case,change.values)
            if changed is False:return view(case)
            # Some domain operations also support standalone callers and already advance once.
            case['revision'] = max(case['revision'],change.revision+1)
            save(c,case)
            return view(case)
    except ValueError as e: raise HTTPException(422,str(e))

@app.get('/api/health')
def health():
    from .model_config import ModelSettings
    from .model_usage import UsageLedger
    s=ModelSettings.from_env();enabled=s.configured and s.enabled
    calls=UsageLedger().summary()['calls'] if enabled else []
    return {'mode':'model-live-local' if enabled else 'offline-local','model_configured':s.configured,'requests_enabled':enabled,'model_name':s.model if enabled else None,'model_connected':any(c.get('http_status')==200 for c in calls),'connection_scope':'historical HTTP success in this run; not a current probe','platform_connected':False,'request_count':len(calls)}

@app.get('/api/cases')
def cases():
    with connection() as c:
        return [{'id':x['id'],'title':x['title'],'revision':x['revision'],**progress(x)} for (b,) in c.execute('SELECT body FROM cases ORDER BY rowid DESC') for x in [json.loads(b)]]

def import_bytes(name, data):
    if Path(name).suffix.lower() not in ('.txt','.eml','.csv','.xlsx','.pdf'):raise HTTPException(422,'支持 EML、CSV、XLSX、TXT 和文本型 PDF')
    try:
        parsed = {'rows':[],'warnings':['文本材料未执行规则表格提取；请审阅候选并核查完整性'],'fragments':[]} if Path(name).suffix.lower()=='.txt' else parse_file(name,data)
    except Exception: raise HTTPException(422,'文件无法解析，请检查文件格式和编码')
    case = new_case(name,parsed)
    folder = ROOT/'var/uploads'/case['id']; folder.mkdir(parents=True,exist_ok=True)
    (folder/Path(name).name).write_bytes(data)
    event(case,'import',{'filename':name,'rows':len(case['rows'])})
    with connection() as c: save(c,case)
    return view(case)

@app.post('/api/import')
async def upload(file:UploadFile=File(...)):
    data = await file.read(20*1024*1024+1)
    if len(data)>20*1024*1024: raise HTTPException(413,'文件上限 20 MB')
    return import_bytes(Path(file.filename or 'unknown').name,data)

@app.post('/api/cases/{id}/materials')
async def append_material(id:str,revision:int=Form(...),file:UploadFile=File(...)):
    """Append an original without choosing an effective version or overwriting a file."""
    data=await file.read(20*1024*1024+1)
    name=Path(file.filename or '').name
    if not name or Path(name).suffix.lower() not in ('.txt','.eml','.pdf'):raise HTTPException(422,'追加原件支持 TXT / EML / 文本PDF')
    if len(data)>20*1024*1024:raise HTTPException(413,'文件上限20MB')
    with connection() as c:
        c.execute('BEGIN IMMEDIATE');case=load(c,id)
        if revision!=case['revision']:raise HTTPException(409,'工作单已更新，请重新选择原件')
        folder=ROOT/'var/uploads'/id;folder.mkdir(parents=True,exist_ok=True);path=folder/name
        if path.exists():raise HTTPException(409,'同名原件已存在，禁止覆盖')
        with path.open('xb') as f:f.write(data)
        case['revision']+=1
        event(case,'material_append',{'filename':name,'effective_version_selected':False})
        save(c,case)
    return view(case)

@app.post('/api/demo')
def demo():
    p = ROOT/'data/synthetic/demo.eml'
    return import_bytes(p.name,p.read_bytes())

@app.get('/api/official')
def official():
    return [str(p.relative_to(ROOT/'data/raw/official-rfq')) for p in (ROOT/'data/raw/official-rfq').rglob('*') if p.is_file()]

@app.post('/api/official/{index}')
def import_official(index:int):
    files = official()
    if not 0<=index<len(files): raise HTTPException(404)
    p=ROOT/'data/raw/official-rfq'/files[index]
    return import_bytes(p.name,p.read_bytes())

def evidence_index(case):
    # Deliberately independent of the application's extractor: re-read stored original bytes.
    from evals.judges.evidence import EvidenceIndex
    index=EvidenceIndex()
    folder=ROOT/'var/uploads'/case['id']
    for file in folder.glob('*'):
        if file.is_file(): index.add(file.name,file.read_bytes())
    return index

def source_guard(case):
    price_intake.guard(ROOT,case)
    index=evidence_index(case)
    for row in case['rows']:
        if row['excluded']:continue
        for field,value in row['raw_fields'].items():
            citations=row.get('field_provenance',{}).get(field,{}).get('sources',row['sources'])
            check=index.verify(field,value,citations)
            # Explicit partial revisions/clarification replies may legitimately inherit
            # different source records. Every record must still prove this request key.
            key={f:index._original_key(row,f) for f in ('rfq','part')}
            matches=[]
            for binding in check.get('bindings',[]):
                entry=index.bindings.get((binding['sha256'],binding['record_id'])) or index.records.get((binding['sha256'],binding['record_id']))
                if entry and all(entry['fields'].get(f)==v for f,v in key.items()):matches.append(binding)
            if value and (not check['supported'] or not matches):
                from .role_review import accepted_candidate_span
                if accepted_candidate_span(case,row,field,case_materials(case)):continue
                raise ValueError(f"原始证据无法支持 {row['rfq']} / {field}，请核查文件与定位")

@app.get('/api/cases/{id}/evidence/{row_id}')
def evidence(id:str,row_id:str):
    with connection() as c:case=load(c,id)
    row=next((r for r in case['rows'] if r['id']==row_id),None)
    if row is None:raise HTTPException(404)
    index=evidence_index(case)
    fields={};content=case_materials(case)
    for field in FIELDS:
        original=row['raw_fields'].get(field,'')
        if not original and not row.get(field):continue
        provenance=row.get('field_provenance',{}).get(field,{})
        citations=provenance.get('sources',row['sources'])
        check=index.verify(field,row.get(field,''),citations)
        origin=index.verify(field,original,citations)
        from .role_review import accepted_candidate_span
        reviewed=accepted_candidate_span(case,row,field,content)
        fields[field]={'value':row.get(field,''),'original':original,'supported':check['supported'],'human_role_reviewed':bool(reviewed),'citation':citations[0] if len(citations)==1 else None,'reasons':check.get('reasons',[]),'record':check.get('record') or origin.get('record'),'manual':row.get(field,'')!=original,'manual_reason':row.get('resolution',''),'inherited_from':provenance.get('inherited_from'),'claim':index.verify_claim(row,field,{d['id']:d for d in case.get('human_decisions',[])})}
    return {'row_id':row_id,'row_revision':row['revision'],'snapshot':content['snapshot'],'fields':fields,'integrity_ok':all(v['supported'] or v['human_role_reviewed'] for v in fields.values() if v['original'])}

@app.post('/api/lifecycle-demo')
def lifecycle_demo():
    p=ROOT/'data/synthetic/tasks/lifecycle.eml'
    return import_bytes(p.name,p.read_bytes())

def case_materials(case):return read_materials(ROOT/'var/uploads'/case['id'])

@app.get('/api/cases/{id}/materials')
def materials(id:str):
    with connection() as c:case=load(c,id)
    content=read_materials(ROOT/'var/uploads'/case['id'],include_source_rows=True)
    adapter=get_adapter()
    return {**content,'model_status':getattr(adapter,'status','configured'),'model_requests_enabled':False if getattr(adapter,'status','') in ('not_configured','disabled') else True}

@app.post('/api/semantic-demo/{name}')
def semantic_demo(name:str):
    choices={'prose':'prose-cn.eml','revision':'forward-revision.eml','mail-en':'../realistic-mail/en-prose.eml','mail-revision':'../realistic-mail/zh-forward-revision.eml','mail-mixed':'../realistic-mail/zh-mixed-line.eml'}
    if name not in choices:raise HTTPException(404)
    p=ROOT/'data/synthetic/semantic'/choices[name]
    return import_bytes(p.name,p.read_bytes())

@app.post('/api/cases/{id}/candidates/propose')
async def propose_candidates(id:str,change:Change,adapter=Depends(get_adapter)):
    with connection() as c:case=load(c,id)
    if change.revision!=case['revision']:raise HTTPException(409,'工作单已更新')
    content=case_materials(case)
    consent=change.values.get('remote_consent') is True
    try:result=await propose(case,content,change.values.get('mode','model'),adapter,consent or synthetic_remote_allowed(content,ROOT))
    except ValueError as e:raise HTTPException(422,str(e))
    if 'id' not in result:return {'case':view(case),'extraction':result}
    def store(current,values):
        if case_materials(current)['snapshot']!=content['snapshot']:raise ValueError('提取期间原件变化，未保存候选')
        current.setdefault('candidate_batches',[]).append(result)
        event(current,'candidate_propose',{'batch':result['id'],'engine':result['engine'],'model_status':result['model_status'],'count':len(result['candidates']),'metrics':result['metrics'],'remote_consent':consent})
    updated=mutate(id,change,store)
    return {'case':updated,'extraction':{'status':'pending_review','count':len(result['candidates']),'model_status':result['model_status'],'requests':result['metrics']['requests'],'engine':result['engine'],'rejected_candidates':result['metrics']['rejected_candidates'],'dropped_fields':result['metrics']['dropped_fields']}}

@app.post('/api/cases/{id}/candidates/{batch_id}/{candidate_id}/review')
def review_candidate(id:str,batch_id:str,candidate_id:str,change:Change):
    def action(case,values):
        batch=next((b for b in case.get('candidate_batches',[]) if b['id']==batch_id),None)
        candidate=next((r for r in batch['candidates'] if r['id']==candidate_id),None) if batch else None
        if not candidate:raise HTTPException(404,'候选不存在')
        if values.get('action')=='reject':
            if candidate['status']!='pending':raise ValueError('候选已处理')
            if not isinstance(values.get('reason'),str) or not values['reason'].strip():raise ValueError('请记录拒绝理由')
            clarifications.record_rejection(case,batch,candidate,values)
            candidate.update(status='rejected',review={'reason':values['reason']})
            # Rejecting a stale batch does not refresh its other pending candidates.
            if batch['expected_revision']==case['revision']:batch['expected_revision']=case['revision']+1
            if all(c['status']!='pending' for c in batch['candidates']):batch['status']='reviewed'
            event(case,'candidate_reject',{'candidate':candidate_id,'reason':values['reason']})
        elif values.get('action')=='accept':
            content=case_materials(case)
            linked=None
            if values.get('clarification_id'):
                linked=clarifications.check_candidate(case,values['clarification_id'],values.get('reply_id'),candidate,content,values)
            elif any(s['sha256']==reply['sha256'] for q in case.get('clarifications',[]) for reply in q['replies'] for s in candidate['field_sources'].values()):
                raise ValueError('此原件已关联澄清项，请从对应答复入口审阅，保留目标及版本守卫')
            accept_candidate(case,batch,candidate,content,values)
            if linked:clarifications.record_application(case,*linked,candidate,values)
        else:raise ValueError('需要显式选择接纳或拒绝')
    return mutate(id,change,action)

@app.post('/api/cases/{id}/candidates/{batch_id}/accept-batch')
def accept_candidate_batch(id:str,batch_id:str,change:Change):
    """Accept the uncontested candidates; same-line siblings and reply-linked ones stay for individual review."""
    def action(case,values):
        batch=next((b for b in case.get('candidate_batches',[]) if b['id']==batch_id),None)
        if not batch:raise HTTPException(404,'候选批次不存在')
        start=case['revision']
        if batch['expected_revision']!=start:raise ValueError('候选已过期，请依据当前工作版本重新生成')
        content=case_materials(case)
        replies={reply['sha256'] for q in case.get('clarifications',[]) for reply in q['replies']}
        pending=[c for c in batch['candidates'] if c['status']=='pending']
        lines=[{f:c['fields'].get(f,'') for f in FIELDS} for c in pending]
        review={k:values.get(k) for k in ('actor','reason','confirm_association')}
        accepted=0;failure=None
        for i,candidate in enumerate(pending):
            if any(clarifications.same_line(lines[i],other) for j,other in enumerate(lines) if j!=i):continue
            if any(s['sha256'] in replies for s in candidate['field_sources'].values()):continue
            batch['expected_revision']=start
            try:
                accept_candidate(case,batch,candidate,content,review);accepted+=1
            except ValueError as e:
                failure=failure or e
        if not accepted:raise failure or ValueError('本批候选都有争议，请逐条处理')
        batch['expected_revision']=start+1
    return mutate(id,change,action)

@app.get('/api/cases/{id}')
def get_case(id:str):
    with connection() as c: return view(load(c,id))

def apply_row_edit(case,row_id,values,mark_resolution=True):
    row = next((r for r in case['rows'] if r['id']==row_id),None)
    if not row: raise HTTPException(404)
    if not values.get('reason','').strip(): raise ValueError('填写裁定依据')
    before = dict(row)
    for k in FIELDS:
        if k in values: row[k] = str(values[k]).strip()
    if 'excluded' in values:
        if not isinstance(values['excluded'],bool): raise ValueError('排除状态必须为布尔值')
        row['excluded']=values['excluded']
    changed=[f for f in FIELDS if row[f]!=before[f]]
    actor=values.get('actor') or row.get('review_actor') or '本地操作人'
    for field in changed:
        original=row['raw_fields'].get(field,'')
        citations=row.get('field_provenance',{}).get(field,{}).get('sources',row['sources'])
        if row[field]==original:row.setdefault('field_provenance',{})[field]={'kind':'source','sources':citations}
        else:
            d={'id':uuid.uuid4().hex,'row_id':row['id'],'field':field,'from':original,'to':row[field],'actor':actor,'reason':values['reason'],'kind':'authorized_human'}
            case.setdefault('human_decisions',[]).append(d)
            row.setdefault('field_provenance',{})[field]={'kind':'human','original_value':original,'sources':citations,'decision_id':d['id']}
    row['pending_confirmations']=[f for f in row.get('pending_confirmations',[]) if f not in changed]
    if mark_resolution:row['resolution']=values['reason']
    row['revision']+=1
    # Retain approval for stale display, but row token always incorporates the edit/reason.
    event(case,'resolve',{'row':row_id,'before':before,'after':dict(row),'reason':values['reason']})


@app.patch('/api/cases/{id}/rows/{row_id}')
def edit_row(id:str,row_id:str,change:Change):
    return mutate(id,change,lambda case,values:apply_row_edit(case,row_id,values))

@app.patch('/api/cases/{id}/rows')
def edit_rows(id:str,change:Change):
    def edit(case,values):
        ids=values.get('row_ids')
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or not all(isinstance(x,str) for x in ids):raise ValueError('请选择不同的询价行')
        changes={k:v for k,v in values.items() if k in ('due','excluded','reason')}
        if not ('due' in changes or 'excluded' in changes):raise ValueError('请选择要批量修改的字段')
        if 'due' in changes:
            try: valid=date.fromisoformat(changes['due']).isoformat()==changes['due']
            except (TypeError,ValueError): valid=False
            if not valid:raise ValueError('统一截止日期须为有效的 YYYY-MM-DD')
        for row_id in ids:apply_row_edit(case,row_id,changes,mark_resolution=False)
    return mutate(id,change,edit)

@app.post('/api/cases/{id}/prices')
def prices(id:str,change:Change): return mutate(id,change,lambda c,v:replace_prices(c,v.get('prices',[])))

@app.post('/api/cases/{id}/prices/import/preview')
async def price_preview(id:str,revision:int=Form(...),file:UploadFile=File(...)):
    with connection() as c:case=load(c,id)
    if revision!=case['revision']:raise HTTPException(409,'工作单版本变化，请刷新')
    try:return price_intake.preview(ROOT,case,Path(file.filename or '').name,await file.read(5*1024*1024+1))
    except (ValueError,UnicodeError,KeyError) as e:raise HTTPException(422,str(e))

@app.post('/api/cases/{id}/prices/import/accept')
def price_accept(id:str,change:Change):
    def action(case,values):
        prices=price_intake.accept(ROOT,case,values)
        affected=replace_prices(case,prices)
        if affected is False:affected=[]
        event(case,'price_import_review',{'preview_id':values['preview_id'],'actor':values['actor'],'reason':values['reason'],'affected':affected})
    return mutate(id,change,action)

@app.post('/api/cases/{id}/demo-prices')
def demo_prices(id:str,change:Change):
    return mutate(id,change,lambda c,v:replace_prices(c,json.loads((ROOT/'data/synthetic/prices.json').read_text(encoding='utf-8'))))

@app.post('/api/cases/{id}/review')
def review(id:str,change:Change):
    def action(c,v):
        if not v.get('note','').strip(): raise ValueError('填写解析警告的人工核查说明')
        c['review_note']=v['note']; event(c,'parse_review',v)
    return mutate(id,change,action)

@app.post('/api/cases/{id}/approve')
def approval(id:str,change:Change):
    def action(c,v):
        source_guard(c)
        approve(c,v.get('actor',''))
    return mutate(id,change,action)

@app.get('/api/cases/{id}/draft')
def draft(id:str):
    with connection() as c: case=load(c,id)
    return {'text':clarifications.draft(case), 'revision':case['revision']}

@app.post('/api/cases/{id}/clarifications/register')
def register_clarifications(id:str,change:Change):
    return mutate(id,change,clarifications.register)

@app.post('/api/cases/{id}/clarifications/{item_id}/replies')
def receive_reply(id:str,item_id:str,change:Change):
    return mutate(id,change,lambda c,v:clarifications.receive(c,item_id,case_materials(c),v))

@app.post('/api/cases/{id}/clarifications/{item_id}/resolve')
def resolve_clarification(id:str,item_id:str,change:Change):
    def action(c,v):
        source_guard(c)
        clarifications.resolve(c,item_id,v)
    return mutate(id,change,action)

def checked_export(case,format,revision,explicit=False):
    if revision is not None and revision!=case['revision']:raise ValueError('所选批准版本已变化，请刷新后重新预览')
    if (explicit or format=='html') and revision is None:raise ValueError('HTML响应必须绑定明确工作版本' if format=='html' else '响应必须绑定明确工作版本')
    source_guard(case)
    return export_data(case)


def export_response(id,result,format,operation):
    headers={'X-RFQ-Business-Revision':str(result['revision']),'X-RFQ-Operation':operation}
    if format=='html':
        headers['Content-Disposition']=f'inline; filename=quote-{id}-r{result["revision"]}.html'
        return Response(render_quote(result),media_type='text/html',headers=headers)
    if format=='csv':
        out=io.StringIO();writer=csv.writer(out)
        writer.writerow(['类型','询价号','件号','数量','单位','件状','币种','单价','总价','交期','价格依据','来源定位','批准人'])
        for r in result['rows']:
            values=[result['label'],r['rfq'],r['part'],r['quantity'],r['unit'],r['condition'],r['price']['currency'],r['price']['amount'],r['total'],r['price']['lead_time'],r['price']['source'],' | '.join(s['file']+' '+s['location'] for s in r['sources']),r['approval']['actor']]
            writer.writerow(["'"+str(v) if str(v).startswith(('=','+','-','@','\t','\r')) else v for v in values])
        headers['Content-Disposition']=f'attachment; filename="quote-{id}.csv"'
        return Response('\ufeff'+out.getvalue(),media_type='text/csv',headers=headers)
    return result


@app.get('/api/cases/{id}/quote-preview')
def quote_preview(id:str,revision:int,format:str='html'):
    if format not in ('html','csv','json'):raise HTTPException(422,'预览格式须为html/csv/json')
    try:
        with connection() as c:
            case=load(c,id);result=checked_export(case,format,revision,explicit=True)
        return export_response(id,result,format,'preview')
    except ValueError as e:raise HTTPException(409,str(e))


@app.post('/api/cases/{id}/exports')
def formal_export(id:str,change:Change):
    format=change.values.get('format','json')
    if format not in ('html','csv','json'):raise HTTPException(422,'导出格式须为html/csv/json')
    return audited_export(id,format,change.revision,'explicit_post')


def audited_export(id,format,revision,route):
    try:
        with connection() as c:
            c.execute('BEGIN IMMEDIATE');case=load(c,id)
            result=checked_export(case,format,revision,explicit=route=='explicit_post')
            # Audit-only: do not advance the business version or invalidate its own approval.
            event(case,'export',{'revision':case['revision'],'format':format,'route':route});save(c,case)
        return export_response(id,result,format,'formal_export')
    except ValueError as e:raise HTTPException(409,str(e))


@app.get('/api/cases/{id}/export')
def export(id:str,format:str='json',revision:int|None=None):
    # Compatibility: the current frontend still uses this auditable legacy GET for preview.
    return audited_export(id,format,revision,'legacy_get')
