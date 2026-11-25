from pathlib import Path
from contextlib import contextmanager
from datetime import date, datetime
from urllib.parse import urlsplit
import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
import zlib
from contextvars import ContextVar

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field
from .parsing import parse_file
from . import price_intake, clarifications, agent, matrixone, material_policy, accounts, references, inbox
from .model_router import ROUTER
from .quote_html import render_quote
from .materials import read_materials, material_files
from .semantic import get_adapter, propose, accept_candidate, synthetic_remote_allowed
from .domain import new_case, analyze, replace_prices, approve, export_data, event, FIELDS, ConflictError, is_case_approved, pending_candidate_batches

ROOT = Path(__file__).resolve().parents[2]
DB = Path(os.getenv('RFQ_DB') or str(ROOT/'var/rfq.sqlite3'))
MAX_CASE_MATERIALS = 25
MAX_BULK_ROWS = 500
LOCAL_ALLOWED_ORIGINS = {'http://127.0.0.1:5311', 'http://localhost:5311'}
_DOCS_PATHS = {'/docs', '/docs/oauth2-redirect', '/redoc', '/openapi.json'}
_VISITOR_SECRET = secrets.token_bytes(32)
_docs_enabled = not (os.getenv('RFQ_AUTH_REQUIRED') == '1' and os.getenv('RFQ_ENABLE_DOCS') != '1')
app = FastAPI(
    title='航材询报价工作台',
    version='0.1.0',
    docs_url='/docs' if _docs_enabled else None,
    redoc_url='/redoc' if _docs_enabled else None,
    openapi_url='/openapi.json' if _docs_enabled else None,
)

@contextmanager
def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    try:
        c.execute('PRAGMA busy_timeout=10000')
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS agent_turns (seq INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, body TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS case_owners (case_id TEXT PRIMARY KEY, visitor TEXT NOT NULL)')
        with c:
            yield c
    finally:
        c.close()

# On the public demo each browser sees only the work orders it created, so nothing one visitor pastes reaches
# another. Off by default: local review and tests keep one shared desk.
SCOPED = os.getenv('RFQ_VISITOR_SCOPE') == '1'
VISITOR: ContextVar[str] = ContextVar('visitor', default='')
CASE_PATH = re.compile(r'^/api/cases/([^/]+)')
ACCOUNTS = accounts.Accounts(connection, upload_root=lambda: ROOT/'var/uploads')
app.include_router(accounts.router(ACCOUNTS))

def _sign_visitor(token: str) -> str:
    secret = (os.getenv('RFQ_VISITOR_SECRET') or '').encode('utf-8') or _VISITOR_SECRET
    return hmac.new(secret, token.encode('ascii'), hashlib.sha256).hexdigest()

def _make_visitor_cookie() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, f'{token}.{_sign_visitor(token)}'

def _parse_visitor_cookie(raw: str) -> str | None:
    if not isinstance(raw, str) or '.' not in raw:
        return None
    token, sig = raw.rsplit('.', 1)
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', token) or not re.fullmatch(r'[0-9a-f]{64}', sig):
        return None
    if not secrets.compare_digest(sig, _sign_visitor(token)):
        return None
    return token

def _referer_origin(request: Request) -> str:
    ref = (request.headers.get('referer') or '').strip()
    if not ref:
        return ''
    parsed = urlsplit(ref)
    if not parsed.scheme or not parsed.netloc:
        return 'invalid'
    return f'{parsed.scheme}://{parsed.netloc}'.rstrip('/')

def check_origin_unauth(request: Request, check_referer: bool = False):
    origin = (request.headers.get('origin') or '').strip()
    fetch_site = (request.headers.get('sec-fetch-site') or '').strip().lower()
    ref_origin = _referer_origin(request) if check_referer else ''
    if not origin and not fetch_site and not ref_origin:
        return
    expected = os.getenv('RFQ_PUBLIC_ORIGIN', '').rstrip('/') or str(request.base_url).rstrip('/')
    allowed = {expected} | LOCAL_ALLOWED_ORIGINS
    if fetch_site == 'cross-site' or (fetch_site and fetch_site not in ('same-origin', 'same-site', 'none')):
        raise HTTPException(403, '请求来源不受信任，请从本站打开')
    if origin and origin.rstrip('/') not in allowed:
        raise HTTPException(403, '请求来源不受信任，请从本站打开')
    if check_referer and ref_origin and ref_origin not in allowed:
        raise HTTPException(403, '请求来源不受信任，请从本站打开')

def owns(case_id, visitor):
    if not SCOPED and not accounts.enabled():
        with connection() as c:
            return bool(c.execute('SELECT 1 FROM cases WHERE id=?', (case_id,)).fetchone())
    with connection() as c:
        row = c.execute('SELECT visitor FROM case_owners WHERE case_id=?', (case_id,)).fetchone()
    return bool(row) and secrets.compare_digest(row[0], visitor)

@app.middleware('http')
async def visitor_scope(request: Request, call_next):
    if request.method == 'OPTIONS': return await call_next(request)
    if accounts.enabled() and os.getenv('RFQ_ENABLE_DOCS') != '1' and request.url.path in _DOCS_PATHS:
        return JSONResponse({'detail': 'Not Found'}, status_code=404)
    if accounts.enabled() and request.url.path.startswith('/api/'):
        user = ACCOUNTS.session(request.cookies.get(accounts.COOKIE, ''), touch=request.url.path!='/api/auth/session')
        user_token = accounts.USER.set(user)
        visitor_token = VISITOR.set('user:'+user['id'] if user else '')
        try:
            path = request.url.path
            public = path in ('/api/auth/session', '/api/auth/login', '/api/auth/demo')
            if not public:
                if not user: raise HTTPException(401, '登录已过期，请重新登录')
                if request.headers.get('x-rfq-account') != user['id']:
                    raise HTTPException(409, '登录账号已变化，请刷新页面')
                if user['must_change'] and path not in ('/api/auth/password','/api/auth/logout'):
                    raise HTTPException(403, '首次登录请先修改密码')
                if request.method not in ('GET','HEAD','OPTIONS'):
                    accounts.check_origin(request)
                    if not secrets.compare_digest(accounts.digest(request.headers.get('x-csrf-token','')), accounts.digest(user['csrf'])):
                        raise HTTPException(403, '页面校验已失效，请刷新后重试')
                found = CASE_PATH.match(path)
                if found and not owns(found.group(1), VISITOR.get()): raise HTTPException(404, '找不到工作单')
                if user['role']=='demo' and request.method not in ('GET','HEAD','OPTIONS'):
                    if path in ('/api/import','/api/agent/start') or path.endswith('/materials') or '/prices/import/' in path or '/clarifications/' in path and path.endswith('/replies'):
                        raise HTTPException(403,'评委体验只使用独立合成材料；导入自己的文件请登录正式账号')
            response = await call_next(request)
        except HTTPException as e:
            response = JSONResponse({'detail':e.detail}, status_code=e.status_code)
            if e.status_code == 409: response.headers['X-RFQ-Session-Changed'] = '1'
        finally:
            VISITOR.reset(visitor_token)
            accounts.USER.reset(user_token)
        response.headers['Cache-Control'] = 'no-store'
        return response
    if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        try:
            check_origin_unauth(request)
        except HTTPException as e:
            return JSONResponse({'detail': e.detail}, status_code=e.status_code)
    if not SCOPED: return await call_next(request)
    visitor = _parse_visitor_cookie(request.cookies.get('rfq_visitor', ''))
    fresh = visitor is None
    signed_cookie = ''
    if fresh:
        visitor, signed_cookie = _make_visitor_cookie()
    token = VISITOR.set(visitor)
    try:
        found = CASE_PATH.match(request.url.path)
        response = JSONResponse({'detail':'找不到工作单'}, status_code=404) if found and not owns(found.group(1), visitor) else await call_next(request)
    finally: VISITOR.reset(token)
    if fresh: response.set_cookie('rfq_visitor', signed_cookie, max_age=30*86400, httponly=True, samesite='lax', secure=request.url.scheme=='https')
    return response

app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5311','http://localhost:5311'], allow_credentials=True, allow_methods=['GET','POST','PATCH'], allow_headers=['Content-Type','X-CSRF-Token','X-RFQ-Account'], expose_headers=['X-RFQ-Session-Changed'])

def save(c, case):
    user = accounts.USER.get()
    if accounts.enabled() and user:
        old = c.execute('SELECT body FROM cases WHERE id=?', (case['id'],)).fetchone()
        offset = len(json.loads(old[0]).get('events',[])) if old else 0
        for entry in case.get('events',[])[offset:]:
            entry.setdefault('detail',{})['account'] = {'id':user['id'],'username':user['username']}
    c.execute('INSERT OR REPLACE INTO cases VALUES (?, ?)', (case['id'],json.dumps(case,ensure_ascii=False)))
    if (SCOPED or accounts.enabled()) and VISITOR.get(): c.execute('INSERT OR IGNORE INTO case_owners VALUES (?, ?)', (case['id'], VISITOR.get()))

def load(c, id):
    row = c.execute('SELECT body FROM cases WHERE id=?',(id,)).fetchone()
    if not row: raise HTTPException(404,'找不到工作单')
    return json.loads(row[0])

def view(case):
    from .model_config import ModelSettings
    settings=ModelSettings.from_env()
    rows=analyze(case)
    p=progress(case,rows)
    return {**case, 'rows':rows, 'clarifications':clarifications.listing(case), 'progress':p, 'case_approved':p['case_approved'], 'mode':'model-live-local' if settings.configured and settings.enabled else 'offline-local'}

def progress(case,rows=None):
    rows=analyze(case) if rows is None else rows
    active=[r for r in rows if not r['excluded']];ids={r['id'] for r in active}
    questions=[q for q in clarifications.listing(case) if q['state'] not in ('resolved','superseded')]
    pending_cands=sum(len(u) for _,u in pending_candidate_batches(case))
    case_ok=is_case_approved(case,rows)
    return {'active':len(active),'approved':sum(r['approved'] for r in active),
            'case_approved':case_ok,
            'open_issues':sum(len(r['issues']) for r in active),'issue_rows':sum(bool(r['issues']) for r in active),
            'open_clarifications':sum(q['row_id'] in ids for q in questions),'all_open_clarifications':len(questions),
            'pending_parse_review':bool(case['warnings'] and not case.get('review_note')),
            'pending_candidates':pending_cands}

class Change(BaseModel):
    revision: int
    values: dict

def mutate(id, change, action):
    try:
        user = accounts.USER.get()
        if accounts.enabled() and user:
            change.values = {**change.values, 'actor':accounts.actor_label(user)}
        with connection() as c:
            c.execute('BEGIN IMMEDIATE')
            case = load(c,id)
            if change.revision != case['revision']: raise HTTPException(409,'工作单已更新，请刷新后重试')
            changed=action(case,change.values)
            if changed is False:return view(case)
            case['revision'] = max(case['revision'],change.revision+1)
            save(c,case)
        matrixone.sync(case,analyze(case))
        return view(case)
    except ConflictError as e: raise HTTPException(409,str(e))
    except ValueError as e: raise HTTPException(422,str(e))

@app.get('/api/health')
def health():
    from .model_config import ModelSettings
    from .model_usage import UsageLedger
    s=ModelSettings.from_env();enabled=s.configured and s.enabled
    calls=UsageLedger().summary()['calls'] if enabled else []
    return {'mode':'model-live-local' if enabled else 'offline-local','model_configured':s.configured,'requests_enabled':enabled,'model_name':s.model if enabled else None,'model_connected':any(c.get('http_status')==200 for c in calls),'connection_scope':'historical HTTP success in this run; not a current probe','platform_connected':bool(matrixone.status['connected']),'model_routes':ROUTER.snapshot(ModelSettings.routes()) if enabled else [],'matrixone':{k:matrixone.status[k] for k in ('enabled','connected')},'request_count':len(calls)}

@app.get('/api/cases')
def cases():
    with connection() as c:
        rows = c.execute('SELECT body FROM cases WHERE id IN (SELECT case_id FROM case_owners WHERE visitor=?) ORDER BY rowid DESC', (VISITOR.get(),)) if SCOPED or accounts.enabled() else c.execute('SELECT body FROM cases ORDER BY rowid DESC')
        return [{'id':x['id'],'title':x['title'],'revision':x['revision'],**progress(x)} for (b,) in rows for x in [json.loads(b)]]

def import_bytes(name, data, on_import=None):
    suffix = Path(name).suffix.lower()
    if suffix not in ('.txt','.eml','.csv','.xlsx','.pdf'):raise HTTPException(422,'支持 EML、CSV、XLSX、TXT 和文本型 PDF')
    if not data.strip():raise HTTPException(422,'文件是空的，没有导入')
    try:
        material_files(name, data)
        parsed = {'rows':[],'warnings':['文本材料未执行规则表格提取；请审阅候选并核查完整性'],'fragments':[]} if suffix=='.txt' else parse_file(name,data)
    except Exception: raise HTTPException(422,'文件无法解析，请检查文件格式和编码')
    case = new_case(name,parsed)
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        if accounts.USER.get() and accounts.USER.get()['role']=='demo':
            count=c.execute('SELECT COUNT(*) FROM case_owners WHERE visitor=?',(VISITOR.get(),)).fetchone()[0]
            if count>=6:raise HTTPException(429,'本体验空间最多保留6张合成工作单，请继续处理已有工作单')
        if on_import:on_import(c,case)
        folder = ROOT/'var/uploads'/case['id']; folder.mkdir(parents=True,exist_ok=True)
        (folder/Path(name).name).write_bytes(data)
        case['materials_snapshot'] = case_materials(case)['snapshot']
        event(case,'import',{'filename':name,'rows':len(case['rows'])})
        save(c,case)
    matrixone.sync(case,analyze(case))
    return view(case)

@app.post('/api/import')
async def upload(file:UploadFile=File(...)):
    data = await file.read(20*1024*1024+1)
    if len(data)>20*1024*1024: raise HTTPException(413,'文件上限 20 MB')
    return await asyncio.to_thread(import_bytes, Path(file.filename or 'unknown').name, data)

@app.post('/api/cases/{id}/materials')
async def append_material(id:str,revision:int=Form(...),file:UploadFile=File(...)):
    """Append an original without choosing an effective version or overwriting a file."""
    data=await file.read(20*1024*1024+1)
    name=Path(file.filename or '').name
    if not name or Path(name).suffix.lower() not in ('.txt','.eml','.pdf'):raise HTTPException(422,'追加原件支持 TXT / EML / 文本PDF')
    if len(data)>20*1024*1024:raise HTTPException(413,'文件上限20MB')
    return await asyncio.to_thread(append_file, id, revision, name, data)

def append_file(id,revision,name,data,on_append=None):
    suffix = Path(name).suffix.lower()
    if suffix not in ('.txt','.eml','.pdf','.csv','.xlsx'):raise HTTPException(422,'追加原件格式不受支持')
    if not data or not data.strip():raise HTTPException(422,'文件是空的，没有导入')
    try:
        material_files(name, data)
        if suffix != '.txt': parse_file(name, data)
    except Exception: raise HTTPException(422,'文件无法解析，请检查文件格式和编码')
    with connection() as c:
        c.execute('BEGIN IMMEDIATE');case=load(c,id)
        if revision!=case['revision']:raise HTTPException(409,'工作单已更新，请重新选择原件')
        folder=ROOT/'var/uploads'/id;folder.mkdir(parents=True,exist_ok=True)
        existing=[p for p in folder.glob('*') if p.is_file()]
        if len(existing)>=MAX_CASE_MATERIALS:raise HTTPException(422,f'单张工作单原件数量上限为{MAX_CASE_MATERIALS}份')
        path=folder/Path(name).name
        if path.exists():raise HTTPException(409,'同名原件已存在，禁止覆盖')
        if on_append:on_append(c,case)
        with path.open('xb') as f:f.write(data)
        case['case_approval']=None
        case['materials_snapshot']=case_materials(case)['snapshot']
        case['revision']+=1
        event(case,'material_append',{'filename':Path(name).name,'effective_version_selected':False})
        save(c,case)
    matrixone.sync(case,analyze(case))
    return view(case)

@app.post('/api/demo')
def demo():
    p = ROOT/'data/synthetic/demo.eml'
    return import_bytes(p.name,p.read_bytes())

@app.get('/api/official')
def official():
    if accounts.enabled(): return []
    return [str(p.relative_to(ROOT/'data/raw/official-rfq')) for p in (ROOT/'data/raw/official-rfq').rglob('*') if p.is_file()]

@app.post('/api/official/{index}')
def import_official(index:int):
    if accounts.enabled(): raise HTTPException(403, '账号环境不开放本机研究素材')
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

@app.post('/api/guided-demo')
def guided_demo():
    return import_bytes('合成体验-两张询价.eml', (ROOT/'data/synthetic/guided.eml').read_bytes())

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

def store_batch(id,change,content,result,consent):
    def store(current,values):
        if case_materials(current)['snapshot']!=content['snapshot']:raise ValueError('提取期间原件变化，未保存候选')
        current['materials_snapshot']=content['snapshot']
        result['materials_snapshot']=content['snapshot']
        if result.get('candidates'):
            current['case_approval']=None
        current.setdefault('candidate_batches',[]).append(result)
        event(current,'candidate_propose',{'batch':result['id'],'engine':result['engine'],'model_status':result['model_status'],'count':len(result['candidates']),'metrics':result['metrics'],'remote_consent':consent})
    updated=mutate(id,change,store)
    matrixone.branch_candidates(updated,result)
    return updated

@app.post('/api/cases/{id}/candidates/propose')
async def propose_candidates(id:str,change:Change,adapter=Depends(get_adapter)):
    with connection() as c:case=load(c,id)
    if change.revision!=case['revision']:raise HTTPException(409,'工作单已更新')
    content=case_materials(case)
    consent=change.values.get('remote_consent') is True
    try:
        mode=change.values.get('mode','model')
        if mode=='model':
            material_policy.check_remote_materials(content,ROOT)
            ACCOUNTS.check_demo_call()
        result=await propose(case,content,mode,adapter,consent or synthetic_remote_allowed(content,ROOT))
    except ValueError as e:raise HTTPException(422,str(e))
    if 'id' not in result:return {'case':view(case),'extraction':result}
    updated=store_batch(id,change,content,result,consent)
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
    reason = values.get('reason')
    if not isinstance(reason, str) or not reason.strip(): raise ValueError('填写裁定依据')
    if len(reason) > 4000: raise ValueError('裁定依据过长（上限4000字）')
    reason = reason.strip()
    if 'actor' in values and values['actor'] is not None:
        if not isinstance(values['actor'], str) or len(values['actor']) > 200:
            raise ValueError('操作人格式无效或过长')
    before = dict(row)
    for k in FIELDS:
        if k in values:
            if not isinstance(values[k], str): raise ValueError(f'字段 {k} 须为字符串')
            if len(values[k]) > 2000: raise ValueError(f'字段 {k} 长度超出上限（2000字）')
            row[k] = values[k].strip()
    if 'excluded' in values:
        if not isinstance(values['excluded'],bool): raise ValueError('排除状态必须为布尔值')
        row['excluded']=values['excluded']
    if row['excluded'] != before['excluded']:
        # Excluding or restoring a row invalidates both row-level and case-level approvals so a
        # shrunken quote cannot be exported and exclude->restore cannot resurrect old approval.
        row['approval'] = None
        case['case_approval'] = None
    changed=[f for f in FIELDS if row[f]!=before[f]]
    actor=(values.get('actor') or '').strip() or row.get('review_actor') or '本地操作人'
    for field in changed:
        original=row['raw_fields'].get(field,'')
        citations=row.get('field_provenance',{}).get(field,{}).get('sources',row['sources'])
        if row[field]==original:row.setdefault('field_provenance',{})[field]={'kind':'source','sources':citations}
        else:
            d={'id':uuid.uuid4().hex,'row_id':row['id'],'field':field,'from':original,'to':row[field],'actor':actor,'reason':reason,'kind':'authorized_human'}
            case.setdefault('human_decisions',[]).append(d)
            row.setdefault('field_provenance',{})[field]={'kind':'human','original_value':original,'sources':citations,'decision_id':d['id']}
    row['pending_confirmations']=[f for f in row.get('pending_confirmations',[]) if f not in changed]
    if mark_resolution:row['resolution']=reason
    row['revision']+=1
    # Retain approval for stale display on field edits; excluded toggles already cleared it above.
    event(case,'resolve',{'row':row_id,'before':before,'after':dict(row),'reason':reason})


@app.patch('/api/cases/{id}/rows/{row_id}')
def edit_row(id:str,row_id:str,change:Change):
    return mutate(id,change,lambda case,values:apply_row_edit(case,row_id,values))

@app.patch('/api/cases/{id}/rows')
def edit_rows(id:str,change:Change):
    def edit(case,values):
        ids=values.get('row_ids')
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or not all(isinstance(x,str) for x in ids):raise ValueError('请选择不同的询价行')
        if len(ids)>MAX_BULK_ROWS:raise ValueError(f'单次批量修改上限为{MAX_BULK_ROWS}行')
        changes={k:v for k,v in values.items() if k in ('due','excluded','reason','actor')}
        if not ('due' in changes or 'excluded' in changes):raise ValueError('请选择要批量修改的字段')
        if 'due' in changes:
            try: valid=isinstance(changes['due'],str) and date.fromisoformat(changes['due']).isoformat()==changes['due']
            except (TypeError,ValueError): valid=False
            if not valid:raise ValueError('统一截止日期须为有效的 YYYY-MM-DD')
        for row_id in ids:apply_row_edit(case,row_id,changes,mark_resolution=False)
    return mutate(id,change,edit)

@app.post('/api/cases/{id}/prices')
def prices(id:str,change:Change): return mutate(id,change,lambda c,v:replace_prices(c,v.get('prices',[])))

def _run_price_preview(id, revision, filename, data):
    with connection() as c:case=load(c,id)
    if revision!=case['revision']:raise HTTPException(409,'工作单版本变化，请刷新')
    try:return price_intake.preview(ROOT,case,filename,data)
    except (ValueError,UnicodeError,KeyError,zlib.error) as e:raise HTTPException(422,str(e))

@app.post('/api/cases/{id}/prices/import/preview')
async def price_preview(id:str,revision:int=Form(...),file:UploadFile=File(...)):
    data = await file.read(5*1024*1024+1)
    return await asyncio.to_thread(_run_price_preview, id, revision, Path(file.filename or '').name, data)

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
        note = v.get('note')
        if not isinstance(note, str) or not note.strip(): raise ValueError('填写解析警告的人工核查说明')
        if len(note) > 4000: raise ValueError('核查说明过长（上限4000字）')
        c['review_note']=note.strip(); event(c,'parse_review',{**v,'note':c['review_note']})
    return mutate(id,change,action)

@app.post('/api/cases/{id}/approve')
def approval(id:str,change:Change):
    def action(c,v):
        source_guard(c)
        approve(c,v.get('actor',''),materials_snapshot=case_materials(c)['snapshot'])
    approved=mutate(id,change,action)
    matrixone.snapshot_approval(approved,change.values.get('actor',''))
    return approved

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

def _csv_cell(v):
    s = '' if v is None else str(v)
    if s.startswith(('\t', '\r', '\n')) or s.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')):
        return "'" + s
    return s

def checked_export(case,format,revision,explicit=False):
    if revision is not None and revision!=case['revision']:raise ValueError('所选批准版本已变化，请刷新后重新预览')
    if (explicit or format=='html') and revision is None:raise ValueError('HTML响应必须绑定明确工作版本' if format=='html' else '响应必须绑定明确工作版本')
    source_guard(case)
    return export_data(case,materials_snapshot=case_materials(case)['snapshot'])


def export_response(id,result,format,operation):
    headers={'X-RFQ-Business-Revision':str(result['revision']),'X-RFQ-Operation':operation}
    if format=='html':
        headers['Content-Disposition']=f'inline; filename=quote-{id}-r{result["revision"]}.html'
        headers['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'"
        headers['X-Content-Type-Options']='nosniff'
        return Response(render_quote(result),media_type='text/html',headers=headers)
    if format=='csv':
        out=io.StringIO();writer=csv.writer(out)
        writer.writerow(['类型','询价号','件号','数量','单位','件状','币种','单价','总价','交期','价格依据','来源定位','批准人'])
        for r in result['rows']:
            values=[result['label'],r['rfq'],r['part'],r['quantity'],r['unit'],r['condition'],r['price']['currency'],r['price']['amount'],r['total'],r['price']['lead_time'],r['price']['source'],' | '.join(s['file']+' '+s['location'] for s in r['sources']),r['approval']['actor']]
            writer.writerow([_csv_cell(v) for v in values])
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
        matrixone.sync(case,analyze(case))
        return export_response(id,result,format,'formal_export')
    except ValueError as e:raise HTTPException(409,str(e))


@app.get('/api/cases/{id}/export')
def export(id:str,request:Request,format:str='json',revision:int|None=None):
    # Legacy auditable GET kept for compatibility with existing audit tests (test_backend_alignment.py);
    # guarded against cross-site state writes via Origin / Sec-Fetch-Site / Referer checks.
    # New callers should use read-only GET /quote-preview or explicit POST /exports.
    if accounts.enabled():
        accounts.check_origin(request)
        ref_origin = _referer_origin(request)
        expected = os.getenv('RFQ_PUBLIC_ORIGIN', '').rstrip('/') or str(request.base_url).rstrip('/')
        if ref_origin and ref_origin != expected:
            raise HTTPException(403, '请求来源不受信任，请从本站打开')
    else:
        check_origin_unauth(request, check_referer=True)
    return audited_export(id,format,revision,'legacy_get')


# ---------- 询价 Agent ----------
AGENT_SHORT_QUESTION=120

class AgentStart(BaseModel):
    text:str
    consent:bool=False

class AgentMessage(BaseModel):
    message:str
    consent:bool=False

def get_agent_session():
    from .model_config import ModelSettings
    s=ModelSettings.from_env()
    return agent.ModelSession(ModelSettings.routes()) if s.configured and s.enabled else None

class CaseWorkspace:
    tools = agent.CASE_TOOLS
    def __init__(self,id,adapter):self.id=id;self.adapter=adapter
    def case(self):
        with connection() as c:return load(c,self.id)
    def content(self,case):return case_materials(case)
    def history(self):return matrixone.report(self.id)
    def reference(self, name, args):
        try:store=references.References(ROOT)
        except ValueError:
            if name!='search_rules':raise
            rules=agent.search_rules(args.get('query',''))['rules']
            return {'method':'内置规则 / 合成检索索引未安装','records':[{'id':f'RULE-{i+1}','description':r['title'],'text':r['text'],'source':r['source']} for i,r in enumerate(rules)],'warnings':['使用现有规则查询回退']}
        if name=='lookup_stock':return store.stock(str(args.get('part','')),str(args.get('condition','')),str(args.get('unit','')),str(args.get('quantity','')))
        if name=='historical_quotes':return store.history(str(args.get('part','')),str(args.get('condition','')),str(args.get('unit','')),str(args.get('currency','')),str(args.get('quantity','')))
        if name=='find_alternatives':return store.alternatives(str(args.get('part','')))
        return store.search('rule' if name=='search_rules' else 'stock',str(args.get('query','')),rerank=os.getenv('RFQ_REFERENCE_RERANK')=='1')
    def add_mail(self,text):
        case=self.case();data=text.encode()
        if any(f['sha256']==hashlib.sha256(data).hexdigest() for f in case_materials(case)['files']):raise ValueError('这封邮件已经在工作单里')
        name=f"邮件-{datetime.now().strftime('%m%d-%H%M%S')}.txt"
        try:append_file(self.id,case['revision'],name,data)
        except HTTPException as e:raise ValueError(e.detail)
        return name
    async def extract(self):
        case=self.case();content=case_materials(case)
        result=await propose(case,content,'model',self.adapter,True)
        if 'id' not in result:return {'status':'没有提取到候选','detail':result['status']}
        # A line the table parser already made formal would only ask the person to accept it twice,
        # but revisions changing due/requirements/priority/description must not be discarded.
        formal={tuple(r.get(k,'') for k in FIELDS) for r in case['rows'] if not r['excluded']}
        result['candidates']=[c for c in result['candidates'] if tuple(c['fields'].get(k,'') for k in FIELDS) not in formal]
        if not result['candidates']:return {'status':'原件里的询价行已经是正式询价行，没有新的候选'}
        try:store_batch(self.id,Change(revision=case['revision'],values={}),content,result,True)
        except HTTPException as e:raise ValueError(e.detail)
        return {'status':'已生成待审候选','rejected':result['metrics']['rejected_candidates'],'dropped_fields':result['metrics']['dropped_fields']}

# What a running turn is doing, so the page can say it while the person waits. Lost on restart, which only ends the display.
AGENT_PROGRESS={}

class GlobalWorkspace:
    """工作区首页的会话：不绑定某一张工作单，只汇总待办与只读参考。"""
    system = agent.HOME_SYSTEM
    tools = agent.HOME_TOOLS

    def __init__(self,owner,adapter=None):
        self.owner=owner;self.adapter=adapter

    def case_rows(self):
        with connection() as c:
            rows=(c.execute('SELECT body FROM cases WHERE id IN (SELECT case_id FROM case_owners WHERE visitor=?) ORDER BY rowid DESC',(self.owner,))
                  if SCOPED or accounts.enabled() else c.execute('SELECT body FROM cases ORDER BY rowid DESC'))
            return [json.loads(b) for (b,) in rows]

    def overview(self):
        mails=inbox.Inbox(connection,ROOT,self.owner).listing()
        routed=[m for m in mails if m.get('case_id')]
        judged=[m for m in mails if m.get('manual') or m.get('decision')]
        unrouted=[m for m in mails if not (m.get('manual') or m.get('decision'))]
        need_review=[m for m in judged if not m.get('manual') and (m.get('decision') or {}).get('needs_review')]
        by_category={}
        for m in judged:
            key=(m.get('manual') or m.get('decision') or {}).get('category')
            if key:by_category[key]=by_category.get(key,0)+1
        cases=[]
        for case in self.case_rows():
            counts=progress(case)
            cases.append({'id':case['id'],'title':case['title'],'revision':case['revision'],**counts,'next':agent.next_step(case)})
        todo=[]
        if unrouted:todo.append({'kind':'mail_unrouted','count':len(unrouted),'text':f'{len(unrouted)} 封邮件还没分流'})
        if need_review:todo.append({'kind':'mail_review','count':len(need_review),'text':f'{len(need_review)} 封分流结果需人工确认'})
        candidates=sum(c['pending_candidates'] for c in cases)
        if candidates:todo.append({'kind':'candidates','count':candidates,'text':f'{candidates} 条候选待审'})
        unpriced=sum(c['issue_rows'] for c in cases)
        if unpriced:todo.append({'kind':'issue_rows','count':unpriced,'text':f'{unpriced} 行待核对或核价'})
        waiting=sum(1 for c in cases if c['active'] and not c.get('case_approved'))
        if waiting:todo.append({'kind':'approve','count':waiting,'text':f'{waiting} 张工作单待批准'})
        clarifications_open=sum(c['all_open_clarifications'] for c in cases)
        if clarifications_open:todo.append({'kind':'clarify','count':clarifications_open,'text':f'{clarifications_open} 项澄清未解决'})
        return {'today':datetime.now().date().isoformat(),'mails':{'total':len(mails),'routed':len(routed),'unrouted':len(unrouted),
                'need_review':len(need_review),'by_category':by_category},'cases':cases[:12],'todo':todo,
                'note':'数字来自当前账号的收件箱与工作单；邮件正文不在这里返回'}

    def mails(self,category='',limit='8'):
        try:limit=max(1,min(20,int(limit)))
        except (TypeError,ValueError):limit=8
        rows=inbox.Inbox(connection,ROOT,self.owner).listing()
        picked=[]
        for m in rows:
            decision=(m.get('manual') or m.get('decision') or {})
            label=decision.get('category') or 'unrouted'
            if category and label!=category:continue
            picked.append({'id':m['id'],'subject':m['subject'],'sender':m['sender'],'revision':m['revision'],
                           'category':label,'needs_review':bool(not m.get('manual') and (m.get('decision') or {}).get('needs_review')),
                           'provider':decision.get('provider'),'case_id':m.get('case_id')})
            if len(picked)>=limit:break
        return {'category':category or 'all','mails':picked,'total':len(rows),'note':'只给摘要；正文与改判请到收件箱操作'}

    def reference(self,name,args):
        store=references.References(ROOT)
        if name=='lookup_stock':return store.stock(str(args.get('part','')),str(args.get('condition','')),str(args.get('unit','')),str(args.get('quantity','')))
        if name=='historical_quotes':return store.history(str(args.get('part','')),str(args.get('condition','')),str(args.get('unit','')),str(args.get('currency','')),str(args.get('quantity','')))
        if name=='find_alternatives':return store.alternatives(str(args.get('part','')))
        kind='stock' if name=='search_parts' else 'rule'
        return store.search(kind,str(args.get('query','')),rerank=os.getenv('RFQ_REFERENCE_RERANK')=='1')

    def case(self):raise ValueError('当前对话不在某张工作单里')
    def content(self,case):raise ValueError('当前对话不在某张工作单里')
    def history(self):raise ValueError('当前对话不在某张工作单里')
    def extract(self):raise ValueError('请先打开一张工作单')
    def add_mail(self,text):raise ValueError('请先在收件箱或工作单里导入原件')

def agent_turns(id):
    with connection() as c:return [json.loads(b) for (b,) in c.execute('SELECT body FROM agent_turns WHERE case_id=? ORDER BY seq',(id,))]

@app.post('/api/agent/start')
def agent_start(body:AgentStart,session=Depends(get_agent_session)):
    """Files a pasted mail as an original. The agent turn that follows is a separate request, so a model failure loses nothing."""
    if session is None:raise HTTPException(409,'模型未启用，请用导入原件的方式处理')
    if not body.consent:raise HTTPException(422,'请先同意把这封邮件发送给模型服务')
    text=body.text.strip()
    if len(text)<10:raise HTTPException(422,'内容太短，请贴完整的询价邮件')
    if len(text)>agent.MAX_MESSAGE:raise HTTPException(422,'内容过长，请分段发送')
    return import_bytes(f"邮件-{datetime.now().strftime('%m%d-%H%M%S')}.txt",text.encode())

@app.get('/api/cases/{id}/matrixone')
def matrixone_report(id:str):
    with connection() as c:load(c,id)
    return matrixone.report(id)

@app.get('/api/cases/{id}/agent/progress')
def agent_progress(id:str):
    return {'steps':AGENT_PROGRESS.get(id)}

@app.get('/api/cases/{id}/agent')
def agent_log(id:str):
    with connection() as c:load(c,id)
    return {'turns':agent_turns(id)}

@app.post('/api/cases/{id}/agent')
async def agent_turn(id:str,body:AgentMessage,session=Depends(get_agent_session),adapter=Depends(get_adapter)):
    if session is None:raise HTTPException(409,'模型未启用，询价 Agent 不可用；工作单其余功能不受影响')
    with connection() as c:case=load(c,id)
    content=case_materials(case)
    try:material_policy.check_remote_materials(content,ROOT)
    except ValueError as e:raise HTTPException(422,str(e))
    # 合成样例已核过可外发，不必再勾；真实材料仍要用户显式同意。
    if not (body.consent or synthetic_remote_allowed(content,ROOT)):raise HTTPException(422,'请先同意把本工作单内容发送给模型服务')
    original=any(body.message.strip()==f.read_text(encoding='utf-8',errors='replace').strip() for f in (ROOT/'var/uploads'/id).glob('*.txt'))
    demo=bool(accounts.USER.get() and accounts.USER.get()['role']=='demo')
    if demo and len(body.message)>600:raise HTTPException(422,'体验提问限600字；请围绕合成询价提问')
    ACCOUNTS.check_demo_call()
    AGENT_PROGRESS[id]=[]
    try:result=await agent.run_turn(CaseWorkspace(id,adapter),body.message,agent_turns(id),session,can_add_mail=not original and not demo,on_step=AGENT_PROGRESS[id].append)
    except ValueError as e:raise HTTPException(422,str(e))
    except agent.ModelUnavailable as e:raise HTTPException(503,f'{e}，请稍后重试；工作单没有变化')
    finally:AGENT_PROGRESS.pop(id,None)
    turn={'message':body.message,'at':datetime.now().isoformat(timespec='seconds'),**result}
    with connection() as c:
        c.execute('INSERT INTO agent_turns (case_id,body) VALUES (?,?)',(id,json.dumps(turn,ensure_ascii=False)))
        case=load(c,id)
        seq=c.execute('SELECT COUNT(*) FROM agent_turns WHERE case_id=?',(id,)).fetchone()[0]
    matrixone.remember_turn(id,seq,case['revision'],turn)
    return {'turn':turn,'case':view(case)}

class HomeMessage(BaseModel):
    message:str
    consent:bool=False


def home_turns():
    owner=VISITOR.get()
    with connection() as c:
        c.execute('CREATE TABLE IF NOT EXISTS agent_home_turns (owner TEXT,seq INTEGER PRIMARY KEY AUTOINCREMENT,body TEXT)')
        rows=c.execute('SELECT body FROM agent_home_turns WHERE owner=? ORDER BY seq',(owner,)).fetchall()
    return [json.loads(b) for (b,) in rows]


@app.get('/api/agent/overview')
def agent_overview():
    return GlobalWorkspace(VISITOR.get()).overview()


@app.get('/api/agent/home')
def agent_home_turns():
    return {'turns':home_turns()}


@app.post('/api/agent/home')
async def agent_home_turn(body:HomeMessage,session=Depends(get_agent_session)):
    if session is None:raise HTTPException(409,'模型未启用，可以先看收件箱与工作单列表')
    if not body.message.strip():raise HTTPException(422,'请输入内容')
    if len(body.message)>600:raise HTTPException(422,'首页提问限600字')
    if not body.consent and len(body.message)>AGENT_SHORT_QUESTION:raise HTTPException(422,'请先同意把问题发送给模型服务')
    ACCOUNTS.check_demo_call()
    try:result=await agent.run_turn(GlobalWorkspace(VISITOR.get()),body.message,home_turns(),session,can_add_mail=False)
    except ValueError as e:raise HTTPException(422,str(e))
    except agent.ModelUnavailable as e:raise HTTPException(503,f'{e}，请稍后重试')
    turn={'message':body.message,'at':datetime.now().isoformat(timespec='seconds'),**result}
    with connection() as c:
        c.execute('CREATE TABLE IF NOT EXISTS agent_home_turns (owner TEXT,seq INTEGER PRIMARY KEY AUTOINCREMENT,body TEXT)')
        c.execute('INSERT INTO agent_home_turns (owner,body) VALUES (?,?)',(VISITOR.get(),json.dumps(turn,ensure_ascii=False)))
    return {'turn':turn}



class ReferenceQuery(BaseModel):
    kind:str=Field(max_length=20)
    query:str=Field(max_length=300)
    condition:str=Field(default='',max_length=30)
    unit:str=Field(default='',max_length=30)
    currency:str=Field(default='',max_length=10)
    quantity:str=Field(default='',max_length=30)
    semantic:bool=False
    rerank:bool=False
    consent:bool=False


@app.get('/api/references/status')
def reference_status():
    return references.References(ROOT).status()


@app.post('/api/references/query')
def reference_query(body:ReferenceQuery):
    store=references.References(ROOT)
    try:
        if not body.query.strip():raise ValueError('请填写件号或检索词')
        if body.kind=='stock':return store.stock(body.query,body.condition,body.unit,body.quantity)
        if body.kind=='quote':return store.history(body.query,body.condition,body.unit,body.currency,body.quantity)
        if body.kind=='alternative':return store.alternatives(body.query)
        if body.kind not in ('parts','rule'):raise ValueError('参考查询类型无效')
        remote=body.semantic and os.getenv('RFQ_ENABLE_MODEL_REQUESTS')=='1' and bool(store.vectors())
        if remote:
            if not body.consent:raise ValueError('语义检索会发送本次检索词给模型，请先确认同意')
            ACCOUNTS.check_demo_call()
        return store.search('stock' if body.kind=='parts' else 'rule',body.query,body.semantic,body.rerank)
    except ValueError as e:raise HTTPException(422,str(e))


app.include_router(inbox.router(connection,lambda:ROOT,lambda:VISITOR.get(),
    lambda:accounts.actor_label(accounts.USER.get()) if accounts.USER.get() else '本地访客',
    import_bytes,append_file,owns,ACCOUNTS.check_demo_call))
