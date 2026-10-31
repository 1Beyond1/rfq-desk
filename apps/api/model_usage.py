"""Credential-free, persistent call accounting. Unknown usage is never zero."""
from datetime import date
from pathlib import Path
import os,json,time,sqlite3,uuid,hashlib

def usage_account(raw):
    if not isinstance(raw,dict):return None
    valid=lambda v:type(v) is int and v>=0
    total=raw.get('total_tokens');prompt=raw.get('prompt_tokens');completion=raw.get('completion_tokens')
    details=raw.get('completion_tokens_details') or {};reasoning=details.get('reasoning_tokens') if isinstance(details,dict) else None
    options=[total] if valid(total) else []
    if valid(prompt) and valid(completion):
        options.append(prompt+completion)
        if valid(reasoning):options.append(prompt+completion+reasoning)
    return max(options) if options else None

class UsageLedger:
    def __init__(self):
        root=Path(__file__).resolve().parents[2]
        self.path=Path(os.getenv('RFQ_MODEL_LEDGER') or root/'var/model-usage.sqlite3')
        # Without an explicit experiment run, limits apply per calendar day to the running product.
        experiment=os.getenv('RFQ_MODEL_RUN_ID')
        self.daily=not experiment
        self.run=experiment or 'daily-'+date.today().isoformat()
        self.max_calls=int(os.getenv('RFQ_MODEL_MAX_CALLS','100' if self.daily else '8'))
        self.max_tokens=int(os.getenv('RFQ_MODEL_TASK_MAX_TOKENS','1000000' if self.daily else '96000'))
        self.max_seconds=float(os.getenv('RFQ_MODEL_TASK_MAX_SECONDS','86400' if self.daily else '1800'))
        self.stop=Path(os.getenv('RFQ_MODEL_STOP_FILE') or self.path.parent/'STOP_MODEL_REQUESTS')
        self.batch=os.getenv('RFQ_MODEL_BATCH','01')
        self.window=os.getenv('RFQ_MODEL_WINDOW','01')
        competitive=self.run in ('competitive-validation-20261028-1','goal-readiness-20261029-1')
        limit=5000 if self.daily else 60 if self.run=='goal-readiness-20261029-1' and self.batch=='02' else 40 if competitive else 8
        if not 1<=self.max_calls<=limit or not 1000<=self.max_tokens<=(20000000 if self.daily else 500000 if competitive else 160000) or not 60<=self.max_seconds<=(86400 if self.daily else 7200):raise ValueError('模型本地任务配额配置无效')
    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(self.path,timeout=10)
        c.execute('CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, run TEXT, started REAL, finished REAL, reserved INTEGER, charge INTEGER, observed INTEGER, status TEXT, model TEXT, input_hash TEXT, raw_usage TEXT, metadata TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS batch_audits (run TEXT, batch TEXT, calls_before INTEGER, authorized_at REAL, first_started REAL, note TEXT, PRIMARY KEY(run,batch))')
        c.execute('CREATE TABLE IF NOT EXISTS window_audits (run TEXT, window TEXT, calls_before INTEGER, authorized_at REAL, first_started REAL, note TEXT, PRIMARY KEY(run,window))')
        return c
    def reserve(self,materials,model,cap):
        if self.stop.exists():raise ValueError('模型任务已终止；未发出请求')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            n,charged,start=c.execute('SELECT count(*),coalesce(sum(charge),0),min(started) FROM calls WHERE run=?',(self.run,)).fetchone()
            if self.run=='goal-readiness-20261029-1' and self.batch=='02':
                audit=c.execute('SELECT calls_before,first_started FROM batch_audits WHERE run=? AND batch=?',(self.run,'02')).fetchone()
                if not audit or audit[0]!=40 or n<40:raise ValueError('第二批未有有效审计授权')
                if audit[1] is None:
                    start=time.time();c.execute('UPDATE batch_audits SET first_started=? WHERE run=? AND batch=?',(start,self.run,'02'))
                else:start=audit[1]
                if self.window=='02':
                    window=c.execute('SELECT calls_before,first_started FROM window_audits WHERE run=? AND window=?',(self.run,'02')).fetchone()
                    if not window or window[0]!=43 or n<43:raise ValueError('第二执行窗口未有有效审计授权')
                    if window[1] is None:
                        start=time.time();c.execute('UPDATE window_audits SET first_started=? WHERE run=? AND window=?',(start,self.run,'02'))
                    else:start=window[1]
            if self.run in ('competitive-validation-20261028-1','goal-readiness-20261029-1') and c.execute('SELECT count(*) FROM calls WHERE run=? AND (observed IS NULL OR finished IS NULL)',(self.run,)).fetchone()[0]:raise ValueError('已有请求用量未知或仍在途，停止继续调用')
            if n>=self.max_calls:raise ValueError('本轮真实调用工作配额已用完，未追加请求')
            if charged+cap>self.max_tokens:raise ValueError('累计token保守预算不足，未追加请求')
            if start is not None and time.time()-start>=self.max_seconds:raise ValueError('本轮模型任务墙钟预算已到，未追加请求')
            rid=uuid.uuid4().hex;h=hashlib.sha256(json.dumps(materials,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            c.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(rid,self.run,time.time(),None,cap,cap,None,'started',model,h,None,'{}'))
            return rid
    def finish(self,rid,status,raw=None,**metadata):
        observed=usage_account(raw)
        with self.connect() as c:
            reserved=c.execute('SELECT reserved FROM calls WHERE id=?',(rid,)).fetchone()[0]
            c.execute('UPDATE calls SET finished=?,charge=?,observed=?,status=?,raw_usage=?,metadata=? WHERE id=?',(time.time(),observed if observed is not None else reserved,observed,status,json.dumps(raw,ensure_ascii=False),json.dumps(metadata,ensure_ascii=False),rid))
    def outcome(self,rid,status):
        with self.connect() as c:c.execute('UPDATE calls SET status=? WHERE id=?',(status,rid))
    def summary(self):
        with self.connect() as c:
            rows=c.execute('SELECT id,started,finished,reserved,charge,observed,status,model,input_hash,raw_usage,metadata FROM calls WHERE run=? ORDER BY started',(self.run,)).fetchall()
        calls=[]
        for r in rows:
            calls.append({'id':r[0],'started_unix':r[1],'elapsed_seconds':None if r[2] is None else round(r[2]-r[1],3),'reserved_tokens':r[3],'budget_charge_tokens':r[4],'accounted_tokens':r[5],'status':r[6],'model':r[7],'synthetic_input_sha256':r[8],'raw_usage':json.loads(r[9]) if r[9] else None,**json.loads(r[10])})
        return {'run_id':self.run,'request_count':len(calls),'work_quota_calls':self.max_calls,'accounted_tokens_known_sum':sum(c['accounted_tokens'] for c in calls if c['accounted_tokens'] is not None),'unknown_usage_calls':sum(c['accounted_tokens'] is None for c in calls),'budget_charge_tokens':sum(c['budget_charge_tokens'] for c in calls),'cost':None,'cost_status':'unknown gateway rates','calls':calls}
