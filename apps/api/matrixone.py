"""Work orders mirrored into MatrixOne for what SQLite cannot do: snapshots, data branches, diffs and time travel.

The app's own SQLite stays the record. MatrixOne gets every saved case (lines and decision events), every agent
turn, a database snapshot at each approval, and a data branch holding each batch of model candidates. If it is
unreachable, work continues and the report says so.
"""
from datetime import datetime, timezone
import json, os, re

import pymysql

LINE_FIELDS = ('rfq', 'part', 'description', 'quantity', 'unit', 'condition', 'due', 'requirements', 'priority')
COLUMNS = {'condition': 'cond'}  # condition is reserved in SQL
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS rfq_lines (case_id VARCHAR(32), row_id VARCHAR(80), case_revision INT, row_revision INT,
       rfq VARCHAR(200), part VARCHAR(200), description VARCHAR(500), quantity VARCHAR(100), unit VARCHAR(100), cond VARCHAR(100),
       due VARCHAR(100), requirements VARCHAR(1000), priority VARCHAR(100), excluded TINYINT, approved TINYINT,
       price_amount VARCHAR(50), price_currency VARCHAR(10), PRIMARY KEY (case_id, row_id))""",
    """CREATE TABLE IF NOT EXISTS rfq_audit (case_id VARCHAR(32), seq INT, at VARCHAR(40), action VARCHAR(64), detail JSON,
       PRIMARY KEY (case_id, seq))""",
    """CREATE TABLE IF NOT EXISTS rfq_agent_memory (case_id VARCHAR(32), seq INT, at VARCHAR(40), case_revision INT,
       message TEXT, reply TEXT, tools VARCHAR(500), PRIMARY KEY (case_id, seq))""",
    """CREATE TABLE IF NOT EXISTS rfq_snapshots (name VARCHAR(100) PRIMARY KEY, case_id VARCHAR(32), case_revision INT,
       price_version INT, actor VARCHAR(200), at VARCHAR(40))""",
    """CREATE TABLE IF NOT EXISTS rfq_candidate_branches (name VARCHAR(100) PRIMARY KEY, case_id VARCHAR(32), batch_id VARCHAR(32),
       candidates INT, at VARCHAR(40), diff JSON)""",
]
status = {'enabled': False, 'connected': False, 'error': None}


def settings():
    host = os.getenv('RFQ_MO_HOST')
    return None if not host else dict(host=host, port=int(os.getenv('RFQ_MO_PORT', '6001')), user=os.getenv('RFQ_MO_USER', 'root'),
                                      password=os.getenv('RFQ_MO_PASSWORD', ''), database=os.getenv('RFQ_MO_DB', 'rfq_desk'))


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def connect():
    s = settings()
    if not s: return None
    db = s.pop('database')
    if not re.fullmatch(r'\w+', db): raise ValueError('MatrixOne database name must be a plain identifier')
    c = pymysql.connect(**s, autocommit=True, connect_timeout=3, read_timeout=15, write_timeout=15, charset='utf8mb4')
    with c.cursor() as cur:
        cur.execute(f'CREATE DATABASE IF NOT EXISTS {db}'); cur.execute(f'USE {db}')
        for sql in SCHEMA: cur.execute(sql)
    return c, db


def guarded(action):
    """Runs one mirror operation. A failure is recorded for the page, never raised into the business flow."""
    status['enabled'] = settings() is not None
    if not status['enabled']: return None
    try:
        link = connect()
        try: result = action(*link)
        finally: link[0].close()
        status.update(connected=True, error=None)
        return result
    except Exception as e:
        status.update(connected=False, error=f'{type(e).__name__}: {str(e)[:200]}')
        return None


def line_values(case_id, case_revision, row):
    price = row.get('price') or {}
    return (case_id, row['id'], case_revision, row.get('revision', 1), *[str(row.get(f, ''))[:1000] for f in LINE_FIELDS],
            int(bool(row.get('excluded'))), int(bool(row.get('approved'))), price.get('amount'), price.get('currency'))


INSERT_LINE = f"REPLACE INTO rfq_lines (case_id,row_id,case_revision,row_revision,{','.join(COLUMNS.get(f, f) for f in LINE_FIELDS)},excluded,approved,price_amount,price_currency) VALUES ({','.join(['%s'] * 17)})"


def sync(case, rows):
    """Lines as analysed (with price and approval) and any decision events not yet mirrored."""
    def run(c, db):
        with c.cursor() as cur:
            ids = [r['id'] for r in rows]
            if ids: cur.execute(f"DELETE FROM rfq_lines WHERE case_id=%s AND row_id NOT IN ({','.join(['%s'] * len(ids))})", (case['id'], *ids))
            else: cur.execute('DELETE FROM rfq_lines WHERE case_id=%s', (case['id'],))
            if rows: cur.executemany(INSERT_LINE, [line_values(case['id'], case['revision'], r) for r in rows])
            cur.execute('SELECT COALESCE(MAX(seq),-1) FROM rfq_audit WHERE case_id=%s', (case['id'],))
            done = cur.fetchone()[0]
            fresh = [(case['id'], seq, e['time'], e['action'], json.dumps(e['detail'], ensure_ascii=False, default=str)[:60000]) for seq, e in enumerate(case['events']) if seq > done]
            if fresh: cur.executemany('INSERT INTO rfq_audit VALUES (%s,%s,%s,%s,%s)', fresh)
    return guarded(run)


def snapshot_approval(case, actor):
    """An approval is a database snapshot: the lines, decisions and agent memory exactly as they were approved."""
    name = f"rfq_{case['id']}_r{case['revision']}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    def run(c, db):
        with c.cursor() as cur:
            cur.execute(f'CREATE SNAPSHOT {name} FOR DATABASE {db}')
            cur.execute('INSERT INTO rfq_snapshots VALUES (%s,%s,%s,%s,%s,%s)', (name, case['id'], case['revision'], case['price_version'], actor, now()))
        return name
    return guarded(run)


def branch_candidates(case, batch):
    """Model candidates go on a data branch of the lines, so the diff against the formal lines shows exactly what they would add."""
    name = f"cand_{batch['id']}"
    def run(c, db):
        with c.cursor() as cur:
            cur.execute(f'DATA BRANCH CREATE TABLE {db}.{name} FROM {db}.rfq_lines')
            for x in batch['candidates']:
                cur.execute(INSERT_LINE.replace('rfq_lines', name, 1), line_values(case['id'], case['revision'], {'id': 'cand:' + x['id'], **x['fields']}))
            # Taken now, against the lines as they were when the model proposed: later acceptances must not rewrite it.
            cur.execute(f'DATA BRANCH DIFF {name} AGAINST rfq_lines')
            diff = [{'flag': r[1], 'row_id': r[3], 'rfq': r[6], 'part': r[7], 'quantity': r[9], 'unit': r[10]} for r in cur.fetchall() if r[0] == name and r[2] == case['id']]
            cur.execute('INSERT INTO rfq_candidate_branches VALUES (%s,%s,%s,%s,%s,%s)', (name, case['id'], batch['id'], len(batch['candidates']), now(), json.dumps(diff, ensure_ascii=False)))
        return name
    return guarded(run)


def remember_turn(case_id, seq, case_revision, turn):
    def run(c, db):
        with c.cursor() as cur:
            cur.execute('REPLACE INTO rfq_agent_memory VALUES (%s,%s,%s,%s,%s,%s,%s)',
                        (case_id, seq, turn['at'], case_revision, turn['message'][:20000], turn['reply'][:20000], ','.join(turn.get('tools', []))))
    return guarded(run)


def rows_at(cur, case_id, snapshot=None):
    cols = ','.join(['row_id', *[COLUMNS.get(f, f) for f in LINE_FIELDS], 'excluded', 'price_amount', 'price_currency'])
    at = f" {{SNAPSHOT='{snapshot}'}}" if snapshot else ''
    cur.execute(f'SELECT {cols} FROM rfq_lines{at} WHERE case_id=%s', (case_id,))
    names = ['row_id', *LINE_FIELDS, 'excluded', 'price_amount', 'price_currency']
    return {r[0]: dict(zip(names, r)) for r in cur.fetchall()}


def compare(before, after):
    changes = []
    for row_id in sorted(set(before) | set(after)):
        a, b = before.get(row_id), after.get(row_id)
        label = (b or a)['part'] or row_id
        if a is None: changes.append({'kind': '新增', 'part': label, 'rfq': b['rfq']})
        elif b is None: changes.append({'kind': '删除', 'part': label, 'rfq': a['rfq']})
        else:
            fields = {k: [a[k], b[k]] for k in a if k != 'row_id' and a[k] != b[k]}
            if fields: changes.append({'kind': '修改', 'part': label, 'rfq': b['rfq'], 'fields': fields})
    return changes


def report(case_id):
    """What the page and the agent can show: snapshots, changes since the last approval, branch diffs, audit and memory."""
    def run(c, db):
        with c.cursor() as cur:
            cur.execute('SELECT name,case_revision,price_version,actor,at FROM rfq_snapshots WHERE case_id=%s ORDER BY at', (case_id,))
            snaps = [dict(zip(('name', 'case_revision', 'price_version', 'actor', 'at'), r)) for r in cur.fetchall()]
            since = None
            if snaps:
                last = snaps[-1]['name']
                since = {'snapshot': last, 'changes': compare(rows_at(cur, case_id, last), rows_at(cur, case_id))}
                cur.execute(f"SELECT COUNT(*) FROM rfq_agent_memory {{SNAPSHOT='{last}'}} WHERE case_id=%s", (case_id,))
                since['memory_at_approval'] = cur.fetchone()[0]
            cur.execute('SELECT name,batch_id,candidates,at,diff FROM rfq_candidate_branches WHERE case_id=%s ORDER BY at', (case_id,))
            branches = [{'name': name, 'batch_id': batch_id, 'candidates': n, 'at': at, 'diff': (json.loads(diff) if isinstance(diff, str) else diff or [])[:30]}
                        for name, batch_id, n, at, diff in cur.fetchall()]
            cur.execute('SELECT seq,at,action FROM rfq_audit WHERE case_id=%s ORDER BY seq DESC LIMIT 12', (case_id,))
            audit = [dict(zip(('seq', 'at', 'action'), r)) for r in cur.fetchall()]
            cur.execute('SELECT COUNT(*) FROM rfq_audit WHERE case_id=%s', (case_id,)); audit_total = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM rfq_agent_memory WHERE case_id=%s', (case_id,)); memory = cur.fetchone()[0]
        return {'database': db, 'snapshots': snaps, 'since_last_approval': since, 'branches': branches, 'audit': audit, 'audit_total': audit_total, 'agent_memory': memory}
    result = guarded(run)
    return {**status, **(result or {})}
