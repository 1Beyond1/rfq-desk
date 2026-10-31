"""Local clarification ledger. Receiving evidence never selects an effective version."""
from copy import deepcopy
from datetime import date, datetime, timezone
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def same_line(a, b):
    """Same RFQ and part are one request line unless both state different conditions."""
    if (a['rfq'], a['part']) != (b['rfq'], b['part']):
        return False
    first, second = a['condition'].casefold(), b['condition'].casefold()
    return not (first and second and first != second)


def problems(case, row, today=None):
    from .domain import FIELDS, number
    if row['excluded']:
        return {}
    result = {}
    for field, label in [('rfq', '询价号'), ('part', '件号'), ('unit', '单位'), ('condition', '件状')]:
        if not row[field]: result[field] = f'缺少{label}，请明确原值'
    try: number(row['quantity'])
    except ValueError: result['quantity'] = '数量须为有限正数，请确认数量及单位'
    if row['due']:
        try:
            if date.fromisoformat(row['due'][:10]).isoformat() < (today or date.today().isoformat()):
                result['due'] = '询价期限已过，请确认延期'
        except ValueError: result['due'] = '截止日期格式待确认'
    if row['requirements'] and not row['resolution']: result['requirements'] = '特殊要求待人工核验'
    for field in row.get('pending_confirmations', []): result[field] = '原值或未知缩写待明确确认'
    peers = [p for p in case['rows'] if p['id'] != row['id'] and not p['excluded'] and same_line(p, row)]
    for peer in peers:
        differences = [f for f in FIELDS if peer[f] != row[f]]
        if not differences: result['association'] = '存在完全重复候选，请明确保留或排除'
        for f in differences: result[f] = '同询价/件号字段冲突，不可自动合计或取最新'
    return result


def target(case, item):
    row = next((r for r in case['rows'] if r['id'] == item['row_id']), None)
    if row is None or any(row[f] != item[f] for f in ('rfq', 'part') if f != item['field']):
        raise ValueError('澄清目标已缺失或重新归属，禁止按件号猜测目标')
    return row


def projection(row, field):
    return {'rfq': row['rfq'], 'part': row['part'], 'value': row.get(field), 'excluded': row['excluded']}


def state(case, item):
    if item.get('supersession'):return 'superseded'
    try: row = target(case, item)
    except ValueError: return 'stale'
    resolved = item.get('resolutions', [])
    if resolved:
        last = resolved[-1]
        if projection(row, item['field']) == last['projection'] and item['field'] not in problems(case, row):
            return 'resolved'
        return 'stale'
    return 'received' if item['replies'] else 'awaiting_reply'


def listing(case):
    output=[]
    for q in case.get('clarifications', []):
        item={**deepcopy(q),'state':state(case,q)}
        for reply in item['replies']:
            pending=[c['id'] for b in case.get('candidate_batches',[]) if b['expected_revision']==case['revision']
                     for c in b['candidates'] if c['status']=='pending' and reply_matches(c,reply)]
            reviews=reply.get('reviews',[])
            reply.update(pending_candidate_ids=pending,reviewed=bool(reviews),
                         review_status='applied' if reply['applications'] else 'pending_review' if pending else reviews[-1]['status'] if reviews else 'received')
        output.append(item)
    return output


def reply_matches(candidate,reply):
    sources=list(candidate.get('field_sources',{}).values())
    return bool(sources) and all(s.get('file')==reply['filename'] and s.get('sha256')==reply['sha256'] for s in sources)


def record_rejection(case,batch,candidate,values):
    """Review evidence, not a statement that the business question is answered."""
    explicit=values.get('clarification_id')
    questions=[find(case,explicit)] if explicit else case.get('clarifications',[])
    for q in questions:
        replies=[r for r in q['replies'] if (not explicit or r['id']==values.get('reply_id')) and reply_matches(candidate,r)]
        if explicit and not replies:raise ValueError('拒绝审阅未绑定本问题的答复原件')
        for reply in replies:
            reply.setdefault('reviews',[]).append({'time':now(),'status':'no_answer' if q['field'] not in candidate['fields'] else 'reviewed_rejected',
                'batch_id':batch['id'],'candidate_id':candidate['id'],'case_revision':case['revision']+1,
                'actor':values.get('actor') or '本地操作人','reason':values['reason']})


def register(case, values):
    from .domain import event
    target_id=values.get('row_id')
    if target_id is not None and (not isinstance(target_id,str) or not any(r['id']==target_id for r in case['rows'])):
        raise ValueError('指定登记的稳定行不存在')
    added = []
    for row in case['rows']:
        if target_id is not None and row['id']!=target_id:continue
        for field, question in problems(case, row).items():
            if any(q['row_id'] == row['id'] and q['field'] == field and state(case, q) not in ('resolved','superseded') for q in case.get('clarifications', [])):
                continue
            q = {'id': uuid.uuid4().hex[:12], 'row_id': row['id'], 'rfq': row['rfq'], 'part': row['part'], 'field': field,
                 'question': question, 'start_revision': case['revision'], 'start_row_revision': row['revision'],
                 'basis': projection(row, field), 'sources': deepcopy(row['sources']), 'created_at': now(), 'replies': [], 'resolutions': []}
            case.setdefault('clarifications', []).append(q); added.append(q['id'])
    if not added:return False
    event(case, 'clarification_register', {'added': added, 'sent': False, 'row_id':target_id})


def find(case, item_id):
    item = next((q for q in case.get('clarifications', []) if q['id'] == item_id), None)
    if item is None: raise ValueError('澄清项不存在')
    return item


def reviewer(values):
    for f in ('actor', 'reason'):
        if not isinstance(values.get(f), str) or not values[f].strip() or len(values[f]) > 4000:
            raise ValueError('请填写核对人及明确处理依据（最多4000字）')


def receive(case, item_id, materials, values):
    from .domain import event
    q = find(case, item_id); row = target(case, q); reviewer(values)
    if state(case,q) in ('resolved','superseded'):raise ValueError('此项已结束，新资料请独立审阅')
    file = next((f for f in materials['files'] if f['file'] == values.get('filename')), None)
    if not file: raise ValueError('须选择本工作单已追加的答复原件')
    if not any(e['action']=='material_append' and e['detail']['filename']==file['file'] for e in case['events']):
        raise ValueError('请先追加答复原件；初始询价不是收到的答复')
    if any(r['sha256'] == file['sha256'] for r in q['replies']): raise ValueError('此答复已登记，禁止重复处理')
    if type(values.get('reply_row_revision')) is not int or values['reply_row_revision']<1: raise ValueError('须明确答复针对的正整数行版本')
    reply = {'id': uuid.uuid4().hex[:12], 'filename': file['file'], 'sha256': file['sha256'], 'received_at': now(),
             'case_revision': case['revision'], 'row_revision': values['reply_row_revision'], 'received_row_revision': row['revision'],
             'projection': projection(row, q['field']), 'actor': values['actor'], 'reason': values['reason'], 'applications': []}
    reply['outdated'] = reply['row_revision'] != row['revision']
    q['replies'].append(reply)
    event(case, 'clarification_receive', {'item': q['id'], 'reply': deepcopy(reply), 'resolved': False})


def check_candidate(case, qid, rid, candidate, materials, values):
    q = find(case, qid); row = target(case, q)
    reply = next((r for r in q['replies'] if r['id'] == rid), None)
    if reply is None: raise ValueError('须选择此澄清项已登记的答复')
    if state(case, q) in ('resolved','superseded'): raise ValueError('澄清已结束；新变更请独立审阅')
    if reply['outdated'] or reply['row_revision'] != row['revision'] or reply['projection'] != projection(row, q['field']):
        raise ValueError('答复针对旧行版本，禁止自动重基或覆盖；需新答复或明确人工裁定')
    if reply['applications']: raise ValueError('答复已应用，禁止重复回填')
    file = next((f for f in materials['files'] if f['file'] == reply['filename']), None)
    if not file or file['sha256'] != reply['sha256']: raise ValueError('答复原件已变化')
    if values.get('mode') != 'partial' or values.get('target_row_id') != row['id']:
        raise ValueError('澄清回填须使用所绑定稳定行的局部修订')
    if values.get('update_fields') != [q['field']] or values.get('clear_fields'):
        raise ValueError('澄清回填只允许明确更新此项字段；未回答字段保持原样')
    if any(s['file'] != file['file'] or s['sha256'] != file['sha256'] for s in candidate['field_sources'].values()):
        raise ValueError('候选不是选定答复原件的内容')
    return q, reply, deepcopy(row)


def record_application(case, q, reply, before, candidate, values):
    from .domain import event
    row = target(case, q)
    reply['applications'].append({'candidate_id': candidate['id'], 'row_revision': row['revision'], 'field': q['field'],
                                  'changed': before.get(q['field']) != row.get(q['field']), 'actor': values['actor'], 'reason': values['reason']})
    event(case, 'clarification_apply', {'item': q['id'], 'reply': reply['id'], 'row_revision': row['revision']})
    if values.get('resolve_clarification') is True:
        resolve(case, q['id'], {**values, 'method': 'reply', 'reply_id': reply['id'], 'base_row_revision': row['revision']})


def resolve(case, item_id, values):
    from .domain import event
    q = find(case, item_id); reviewer(values)
    if state(case,q) in ('resolved','superseded'):raise ValueError('此项已结束，无需重复处理')
    if values.get('method')=='superseded':
        row=next((r for r in case['rows'] if r['id']==q['row_id']),None)
        if row is None or values.get('base_row_revision')!=row['revision']:raise ValueError('目标行不存在或版本已变化')
        if (row['rfq'],row['part'])==(q['rfq'],q['part']):raise ValueError('目标归属未变化，不能结束未解决问题')
        if row['revision']<=q['start_row_revision']:raise ValueError('缺少重新归属的正式裁定')
        q['supersession']={'time':now(),'row_revision':row['revision'],'actor':values['actor'],'reason':values['reason'],'projection':projection(row,q['field'])}
        # The old target is retired explicitly; any current field problem remains independently blocking.
        event(case,'clarification_superseded',{'item':q['id'],**deepcopy(q['supersession'])})
        return
    row = target(case, q)
    if state(case, q) == 'resolved': raise ValueError('此项已解决，无需重复关闭')
    if values.get('base_row_revision') != row['revision']: raise ValueError('行版本变化，请重新核对')
    if q['field'] in problems(case, row): raise ValueError('此字段仍有业务阻断，答复不充分，不能标记解决')
    method = values.get('method')
    if method == 'reply':
        reply = next((r for r in q['replies'] if r['id'] == values.get('reply_id')), None)
        applied = reply['applications'][-1] if reply and reply['applications'] else None
        if not applied or not applied['changed'] or applied['row_revision'] != row['revision']:
            raise ValueError('未核对实际字段变化，不能把收到答复当作解决')
    elif method == 'manual':
        baseline = q['resolutions'][-1]['row_revision'] if q['resolutions'] else q['start_row_revision']
        if row['revision'] <= baseline: raise ValueError('请先在对应行记录人工字段裁定或确认说明，再核实关闭')
    else: raise ValueError('须明确使用答复回填或人工裁定依据')
    record = {'time': now(), 'case_revision': case['revision'] + 1, 'row_revision': row['revision'], 'projection': projection(row, q['field']),
              'actor': values['actor'], 'reason': values['reason'], 'method': method, 'reply_id': values.get('reply_id')}
    q['resolutions'].append(record)
    event(case, 'clarification_resolve', {'item': q['id'], **deepcopy(record)})


def draft(case):
    lines = [f"本地澄清草稿 · {case['title']} · 工作版本 {case['revision']}", '仅供人工导出/发送；系统未发送邮件。请逐项回复询价号、件号、目标字段及所针对的行版本。']
    for q in listing(case):
        if q['state'] in ('resolved','superseded'): continue
        row = next((r for r in case['rows'] if r['id'] == q['row_id']), None)
        lines.append(f"[{q['id']}] RFQ {q['rfq']} / 件号 {q['part']} / 字段 {q['field']} / 行版本 {row['revision'] if row else '目标缺失'} / 状态 {q['state']}\n问题：{q['question']}\n开始工作版本 {q['start_revision']}；原值 {q['basis']['value']}；依据 " + '；'.join(s['file'] + ' / ' + s['location'] for s in q['sources']))
    if len(lines) == 2: lines.append('尚无登记的未决项，请先登记当前澄清项。价格由内部有效价源核对。')
    return '\n\n'.join(lines)
