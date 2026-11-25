from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import uuid
import re
from . import clarifications

FIELDS = ('rfq','part','description','quantity','unit','condition','due','requirements','priority')
MAX_PRICES = 2000
MAX_PRICE_FIELD_LEN = 500
MAX_ACTOR_LEN = 200

class ConflictError(ValueError):
    """Domain state conflict that maps to HTTP 409."""

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def _candidate_signature(candidate):
    return fingerprint({
        'fields': candidate.get('fields', {}),
        'field_sources': candidate.get('field_sources', {}),
    })

def pending_candidate_batches(case):
    reviewed = {
        _candidate_signature(c)
        for b in case.get('candidate_batches', [])
        for c in b.get('candidates', [])
        if c.get('status') in ('accepted', 'rejected')
    }
    cur_rev = case.get('revision')
    cur_snap = case.get('materials_snapshot', '')
    pending = []
    for b in case.get('candidate_batches', []):
        if b.get('status') != 'pending':
            continue
        same_rev = b.get('expected_revision', cur_rev) == cur_rev
        untouched_same_snap = (
            bool(cur_snap and b.get('materials_snapshot') and b.get('materials_snapshot') == cur_snap)
            and not any(c.get('status') in ('accepted', 'rejected') for c in b.get('candidates', []))
        )
        if not (same_rev or untouched_same_snap):
            continue
        unreviewed = [
            c for c in b.get('candidates', [])
            if c.get('status') == 'pending' and _candidate_signature(c) not in reviewed
        ]
        if unreviewed:
            pending.append((b, unreviewed))
    return pending

def case_approval_token(case, rows=None, today=None, materials_snapshot=None):
    rows = analyze(case, today) if rows is None else rows
    active = [(r['id'], r['token']) for r in rows if not r['excluded']]
    snapshot = case.get('materials_snapshot', '') if materials_snapshot is None else materials_snapshot
    return fingerprint({
        'active': active,
        'materials_snapshot': snapshot,
        'review_note': case.get('review_note', ''),
    })

def is_case_approved(case, rows=None, today=None, materials_snapshot=None):
    today = today or date.today().isoformat()
    rows = analyze(case, today) if rows is None else rows
    active = [r for r in rows if not r['excluded']]
    if not active or any(not r['approved'] for r in active):
        return False
    if case['warnings'] and not case.get('review_note'):
        return False
    if pending_candidate_batches(case):
        return False
    ca = case.get('case_approval')
    if not isinstance(ca, dict):
        return False
    return ca.get('date') == today and ca.get('token') == case_approval_token(case, rows, today, materials_snapshot)

def number(value, positive=True):
    if not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?',str(value)):raise ValueError('无效数值')
    try:
        n = Decimal(str(value))
        if not n.is_finite() or (positive and n <= 0): raise ValueError('数值必须为有限正数')
        if n.copy_abs()>Decimal('1000000000000') or n.as_tuple().exponent < -12:raise ValueError('数值超过支持范围（最多1万亿、12位小数）')
        return n
    except (InvalidOperation, TypeError): raise ValueError('无效数值')

def new_case(title, parsed):
    rows = []
    for item in parsed['rows']:
        f = {k: str(item['fields'].get(k, '')).strip() for k in FIELDS}
        rows.append({'id':uuid.uuid4().hex[:12], **f, 'raw_fields':item['raw_fields'], 'sources':[item['source']], 'excluded':False, 'resolution':'', 'revision':1, 'approval':None})
    return {'id':uuid.uuid4().hex[:12], 'title':title, 'revision':1, 'rows':rows, 'prices':[], 'price_version':0, 'warnings':parsed['warnings'], 'fragments':parsed['fragments'], 'events':[]}

def price_validate(p):
    required = ('part','unit','condition','currency','amount','valid_from','valid_until','lead_time','source','kind')
    if not isinstance(p,dict) or any(not isinstance(p.get(k),str) or not p[k].strip() for k in required): raise ValueError('价表字段须为非空字符串，且包含依据、有效期、交期和条件')
    cleaned = {**p, **{k: p[k].strip() for k in required}}
    if any(len(cleaned[k]) > MAX_PRICE_FIELD_LEN for k in required): raise ValueError('价表字段长度超出上限')
    if cleaned['kind'] not in ('synthetic','manual','authorized'): raise ValueError('价格来源类型无效')
    number(cleaned['amount'])
    if cleaned['currency'] not in ('USD','CNY','EUR','GBP','JPY'): raise ValueError('币种暂不支持')
    dates=[date.fromisoformat(cleaned[k]) for k in ('valid_from','valid_until')]
    if [d.isoformat() for d in dates]!=[cleaned['valid_from'],cleaned['valid_until']]:raise ValueError('有效期须使用 YYYY-MM-DD')
    if dates[0] > dates[1]: raise ValueError('有效期倒置')
    return cleaned

def analyze(case, today=None):
    today = today or date.today().isoformat()
    output = []
    for row in case['rows']:
        r = dict(row); issues = []; issue_codes=[]
        def issue(message,code,**detail):
            issues.append(message);issue_codes.append({'code':code,'message':message,**detail})
        peers = [p for p in case['rows'] if p['id'] != r['id'] and not p['excluded'] and clarifications.same_line(p,r)]
        duplicate = any(all(p[k] == r[k] for k in FIELDS) for p in peers)
        conflict = any(any(p[k] != r[k] for k in FIELDS) for p in peers)
        if not r['excluded']:
            if r.get('pending_confirmations'):issue('原值待确认：'+', '.join(r['pending_confirmations']),'unconfirmed_value',fields=r['pending_confirmations'])
            if duplicate: issue('重复候选：需明确保留或排除','duplicate_row')
            if conflict: issue('同询价/件号字段冲突：不可自动合计或覆盖','conflicting_row')
            for k, label in [('rfq','询价号'),('part','件号'),('unit','单位'),('condition','件状')]:
                if not r[k]: issue(f'缺少{label}','missing_field',field=k)
            try: quantity = number(r['quantity'])
            except ValueError: quantity = None; issue('数量须为正数','invalid_quantity',field='quantity')
            if r['due']:
                try:
                    if date.fromisoformat(r['due'][:10]).isoformat() < today: issue('询价期限已过：需确认延期','expired_due',field='due')
                except ValueError: issue('截止日期格式待确认','invalid_due',field='due')
            if r['requirements'] and not r['resolution']: issue('特殊要求待人工核验','requirements_review',field='requirements')
        else: quantity = None
        candidates = [p for p in case['prices'] if (p['part'],p['unit'],p['condition']) == (r['part'],r['unit'],r['condition']) and p['valid_from'] <= today <= p['valid_until']]
        selected = candidates[0] if len(candidates)==1 else None
        if not r['excluded'] and not selected: issue('缺少唯一有效价格依据' if not candidates else '多个有效报价源：需裁定价表','missing_price' if not candidates else 'ambiguous_price')
        questions=[q for q in case.get('clarifications',[]) if q['row_id']==r['id']]
        if not r['excluded']:
            for q in questions:
                if clarifications.state(case,q) not in ('resolved','superseded'):issue('澄清未解决：'+q['field']+' / '+q['id'],'open_clarification',field=q['field'],question_id=q['id'])
        approval_input={'row':{k:r[k] for k in FIELDS},'excluded':r['excluded'],'resolution':r['resolution'],'price':selected,'sources':r['sources'],'provenance':r.get('field_provenance',{}),'candidate_id':r.get('candidate_id')}
        # Keep historic cases' tokens unchanged when they have no clarification ledger.
        if questions:approval_input['clarifications']=[{'id':q['id'],'state':clarifications.state(case,q),'resolutions':q['resolutions']} for q in questions]
        token = fingerprint(approval_input)
        approved = bool(row['approval'] and row['approval']['token'] == token and row['approval']['date'] == today and not issues)
        quantum = Decimal('1') if selected and selected['currency']=='JPY' else Decimal('.01')
        r.update(issues=issues, issue_codes=issue_codes, duplicate=duplicate, conflict=conflict, price=selected, token=token, approved=approved, stale=bool(row['approval'] and not approved), total=str((quantity*number(selected['amount'])).quantize(quantum,rounding=ROUND_HALF_UP)) if quantity and selected else None)
        output.append(r)
    return output

def event(case, action, detail):
    from datetime import datetime, timezone
    case['events'].append({'time':datetime.now(timezone.utc).isoformat(),'action':action,'detail':detail})

def replace_prices(case, prices):
    if not isinstance(prices,list):raise ValueError('完整价表须为数组')
    if len(prices) > MAX_PRICES: raise ValueError(f'价表条目过多（上限{MAX_PRICES}条）')
    cleaned = [price_validate(p) for p in prices]
    if cleaned==case['prices']:return False
    before = {r['id']:r['token'] for r in analyze(case)}
    case['prices'] = cleaned; case['price_version'] += 1; case['revision'] += 1
    affected = [r['id'] for r in analyze(case) if before[r['id']] != r['token']]
    event(case,'price_update',{'version':case['price_version'],'affected':affected})
    return affected

def approve(case, actor, today=None, materials_snapshot=None):
    today=today or date.today().isoformat()
    if not isinstance(actor,str) or not actor.strip(): raise ValueError('请填写批准人')
    actor = actor.strip()
    if len(actor) > MAX_ACTOR_LEN: raise ValueError(f'批准人名称过长（上限{MAX_ACTOR_LEN}字）')
    rows = analyze(case,today)
    active = [r for r in rows if not r['excluded']]
    if not active or any(r['issues'] for r in active) or case['warnings'] and not case.get('review_note'): raise ValueError('先处理全部询价异常及解析警告，再批准')
    if pending_candidate_batches(case): raise ConflictError('存在待审候选批次，请先审阅后再批准')
    for row, result in zip(case['rows'], rows):
        if not row['excluded']: row['approval'] = {'actor':actor,'token':result['token'],'date':today}
    case['case_approval'] = {'actor':actor,'date':today,'token':case_approval_token(case,rows,today,materials_snapshot)}
    event(case,'approve',{'actor':actor,'revision':case['revision']})

def export_data(case,today=None,materials_snapshot=None):
    today=today or date.today().isoformat()
    if pending_candidate_batches(case): raise ConflictError('存在待审候选批次，请先审阅后再导出')
    analyzed = analyze(case,today)
    rows = [r for r in analyzed if not r['excluded']]
    if not rows or any(not r['approved'] for r in rows) or case['warnings'] and not case.get('review_note'): raise ValueError('当前版本未全部批准，禁止正式导出')
    ca = case.get('case_approval')
    expected_token = case_approval_token(case,analyzed,today,materials_snapshot)
    if not isinstance(ca,dict) or ca.get('date')!=today or ca.get('token')!=expected_token:
        raise ValueError('当前版本未全部批准，禁止正式导出')
    return {'case_id':case['id'],'revision':case['revision'],'price_version':case['price_version'],'label':'合成演示报价' if any(r['price']['kind']=='synthetic' for r in rows) else '报价响应', 'rows':rows}
