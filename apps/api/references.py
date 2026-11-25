"""Shared, explicitly synthetic reference data."""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from datetime import date
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import math
import os
import re
import sqlite3
import threading

from . import aux_models, matrixone

LOCK = threading.RLock()
MO_SEEDED = set()
MO_STATUS = {'connected':False,'error':None}


@lru_cache(maxsize=8)
def corpus(path, modified):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if data.get('classification')!='synthetic' or not 1<=len(data['records'])<=200:
        raise ValueError('参考数据必须为有界合成数据')
    return data, hashlib.sha256(raw).hexdigest()


class References:
    def __init__(self, root):
        self.root = Path(root)
        self.folder = self.root/'data/synthetic/references'
        path = self.folder/'records.json'
        try:self.data,self.digest = corpus(str(path),path.stat().st_mtime_ns)
        except (OSError,json.JSONDecodeError,KeyError):raise ValueError('合成参考数据未安装或无法读取') from None
        self.version = self.data['version']
        self.records = self.data['records']
        self.db = self.root/'var/references.sqlite3'

    @contextmanager
    def connection(self):
        self.db.parent.mkdir(parents=True,exist_ok=True)
        c = sqlite3.connect(self.db,timeout=10)
        try:
            c.execute('CREATE TABLE IF NOT EXISTS records (dataset TEXT,id TEXT,kind TEXT,part_no TEXT,body TEXT,content TEXT,PRIMARY KEY(dataset,id))')
            if not c.execute('SELECT 1 FROM records WHERE dataset=? LIMIT 1',(self.digest,)).fetchone():
                c.executemany('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?)',self.values())
                c.commit()
            yield c
        finally:
            c.close()

    def values(self):
        return [(self.digest,r['id'],r['kind'],r.get('part',''),json.dumps(r,ensure_ascii=False),self.content(r)) for r in self.records]

    @staticmethod
    def content(r):
        return ' '.join(str(v) for k,v in r.items() if k not in ('classification','id'))

    def vectors(self):
        p = self.folder/'embeddings.json'
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding='utf-8'))
        vectors = data.get('vectors',{})
        dim = data.get('dimension',0)
        if data.get('dataset')!=self.digest or data.get('model')!='bge-m3' or type(dim) is not int or not 1<=dim<=4096:
            return None
        if set(vectors)!={r['id'] for r in self.records} or any(not isinstance(v,list) or len(v)!=dim or any(type(x) not in (int,float) or not math.isfinite(x) for x in v) for v in vectors.values()):
            raise ValueError('合成检索索引无效')
        return data

    @contextmanager
    def mo(self):
        link = matrixone.connect()
        if not link:
            raise ValueError('MatrixOne未配置')
        c,db = link
        try:
            vectors = self.vectors()
            key = (hashlib.sha256(json.dumps(matrixone.settings(),sort_keys=True).encode()).hexdigest(),self.digest, bool(vectors))
            with LOCK:
                if key not in MO_SEEDED:
                    with c.cursor() as cur:
                        cur.execute('CREATE TABLE IF NOT EXISTS rfq_reference_records (dataset VARCHAR(64),id VARCHAR(80),kind VARCHAR(20),part_no VARCHAR(120),body JSON,content TEXT,PRIMARY KEY(dataset,id))')
                        cur.executemany('REPLACE INTO rfq_reference_records VALUES(%s,%s,%s,%s,%s,%s)',self.values())
                        if vectors:
                            dim = vectors['dimension']
                            cur.execute(f'CREATE TABLE IF NOT EXISTS rfq_reference_vectors_{dim} (dataset VARCHAR(64),id VARCHAR(80),embedding VECF32({dim}),PRIMARY KEY(dataset,id))')
                            cur.executemany(f'REPLACE INTO rfq_reference_vectors_{dim} VALUES(%s,%s,%s)',[(self.digest,k,json.dumps(v)) for k,v in vectors['vectors'].items()])
                    MO_SEEDED.add(key)
            yield c
            MO_STATUS.update(connected=True,error=None)
        finally:
            c.close()

    def select(self, kind, part=''):
        if kind not in ('stock','quote','alternative','rule'):
            raise ValueError('参考资料类型无效')
        part = str(part).strip().upper()[:120]
        warnings = []
        if matrixone.settings():
            try:
                with self.mo() as c,c.cursor() as cur:
                    cur.execute('SELECT body FROM rfq_reference_records WHERE dataset=%s AND kind=%s'+(' AND part_no=%s' if part else '')+' ORDER BY id', (self.digest,kind,*([part] if part else [])))
                    rows = [json.loads(r[0]) if isinstance(r[0],str) else r[0] for r in cur.fetchall()]
                return rows,'MatrixOne SQL',warnings
            except Exception:
                MO_STATUS.update(connected=False,error='unavailable')
                warnings.append('MatrixOne本次查询不可用，使用本地副本')
        with self.connection() as c:
            rows = c.execute('SELECT body FROM records WHERE dataset=? AND kind=?'+(' AND part_no=?' if part else '')+' ORDER BY id',(self.digest,kind,*([part] if part else []))).fetchall()
        return [json.loads(r[0]) for r in rows],'本地副本',warnings

    def result(self, rows, method, warnings=None, **extra):
        return {'classification':'synthetic','dataset':self.version,'dataset_hash':self.digest,'method':method,'records':rows,'warnings':warnings or [],**extra}

    def stock(self, part, condition='', unit='', quantity=''):
        if not str(part).strip():raise ValueError('精确库存查询需要明确件号；只有描述时请使用语义找件')
        part = str(part).strip().upper()
        condition = str(condition or '').strip().upper()
        unit = str(unit or '').strip().upper()
        quantity = str(quantity or '').strip()
        rows,method,warnings = self.select('stock',part)
        qualified = [r for r in rows if (not condition or str(r['condition']).strip().upper()==condition) and (not unit or str(r['unit']).strip().upper()==unit)]
        keep = {id(r) for r in qualified}
        unmatched = [r for r in rows if id(r) not in keep]
        if not qualified:
            warnings.append('该件号没有符合本次件状/单位的库存记录；不要按其他件状的数量替代' if rows else '该件号当前没有库存记录')
        elif unmatched:
            warnings.append(f'{len(unmatched)} 条记录的件状或单位与本次需求不符，未计入可用量')
        groups = {}
        for row in qualified:
            key = (row['condition'],row['unit'])
            groups[key] = groups.get(key,0)+row['quantity']
        requested = None
        if quantity:
            try:
                requested = Decimal(str(quantity))
                if not requested.is_finite() or not 0<=requested<=Decimal('1000000000'):raise InvalidOperation
            except InvalidOperation:raise ValueError('需求数量应为非负有限数值')
        summaries = [{'condition':cond,'unit':u,'available':n,'shortage':str(max(Decimal(0),requested-n)) if requested is not None else None} for (cond,u),n in groups.items()]
        return self.result(qualified,method,warnings,other_conditions=[{k:r[k] for k in ('id','condition','unit','quantity','warehouse')} for r in unmatched],eligible_groups=summaries,requirements={'part':part,'condition':condition,'unit':unit,'quantity':quantity},price_authority=False,note='证书与交期须核实；不构成有效价格依据')

    def history(self, part, condition='', unit='', currency='', quantity=''):
        if not str(part).strip():raise ValueError('历史报价查询需要明确件号')
        part = str(part).strip().upper()
        condition = str(condition or '').strip().upper()
        unit = str(unit or '').strip().upper()
        currency = str(currency or '').strip().upper()
        quantity = str(quantity or '').strip()
        rows,method,warnings = self.select('quote',part)
        for row in rows:
            diffs = []
            for k,label,value in [('condition','件状',condition),('unit','单位',unit),('currency','币种',currency)]:
                if value and str(row[k]).strip().upper()!=value:
                    diffs.append(f'{label}不同：历史{row[k]}，本次{value}')
            if quantity and str(row['quantity']).strip()!=quantity:
                diffs.append(f'数量不同：历史{row["quantity"]}，本次{quantity}')
            row['differences'] = diffs
            row['usable_as_current_price'] = False
            row['expired'] = row['valid_until']<date.today().isoformat()
            if row['expired']:row['differences'].append('历史报价有效期已过，不能作为当前价格')
        return self.result(sorted(rows,key=lambda r:r['date'],reverse=True),method,warnings,note='历史报价仅供参考，不跨币种折算，不自动套价')

    def alternatives(self, part):
        if not str(part).strip():raise ValueError('替代关系查询需要明确主件号')
        part = str(part).strip().upper()
        rows,method,warnings = self.select('alternative',part)
        return self.result(rows,method,warnings,note='仅列出有明确记录的替代关系；互换适用性须人工确认')

    @staticmethod
    def _tokenize(query):
        tokens = []
        seen = set()
        def add(tok):
            if tok and tok not in seen:
                seen.add(tok)
                tokens.append(tok)
        for m in re.finditer(r'[a-z0-9][a-z0-9-]*|[\u4e00-\u9fff]+', str(query).lower()):
            seg = m.group(0)
            if '\u4e00' <= seg[0] <= '\u9fff':
                if len(seg) == 1:
                    add(seg)
                else:
                    for i in range(len(seg) - 1):
                        add(seg[i:i + 2])
            else:
                add(seg)
        return tokens

    def search(self, kind, query, semantic=True, rerank=False):
        if kind not in ('stock','rule') or not isinstance(query,str) or not 1<=len(query.strip())<=300:
            raise ValueError('请填写300字以内的检索词并选择库存或规则')
        warnings = []
        index = self.vectors() if semantic else None
        rows,method,notice = self.select(kind)
        warnings.extend(notice)
        if semantic and index:
            try:
                vec = aux_models.embeddings([query])[0]
                dim = index['dimension']
                if len(vec)!=dim:raise ValueError('索引维度与查询模型不一致')
                try:
                    with self.mo() as c,c.cursor() as cur:
                        cur.execute(f'SELECT r.body,COSINE_SIMILARITY(v.embedding,CAST(%s AS VECF32({dim}))) AS score FROM rfq_reference_vectors_{dim} v JOIN rfq_reference_records r ON r.dataset=v.dataset AND r.id=v.id WHERE r.dataset=%s AND r.kind=%s ORDER BY score DESC LIMIT 5',(json.dumps(vec),self.digest,kind))
                        hits = [{**(json.loads(row[0]) if isinstance(row[0],str) else row[0]),'score':float(row[1])} for row in cur.fetchall()]
                    method = 'MatrixOne向量检索 / bge-m3'
                except Exception:
                    def cosine(other):
                        den=math.sqrt(sum(x*x for x in vec))*math.sqrt(sum(x*x for x in other))
                        return sum(x*y for x,y in zip(vec,other))/den if den else 0
                    hits = sorted([{**r,'score':cosine(index['vectors'][r['id']])} for r in rows],key=lambda r:r['score'],reverse=True)[:5]
                    method = '本地向量副本 / bge-m3'
                    warnings.append('MatrixOne向量查询本次不可用，改用本地向量副本')
                if rerank and hits:
                    try:
                        ranked = aux_models.rerank(query,[self.content(r) for r in hits])
                        hits = [{**hits[r['index']],'rerank_score':r['relevance_score']} for r in ranked]
                        method += ' + qwen3-rerank'
                    except (ValueError,TypeError,IndexError):
                        warnings.append('重排不可用，保留原始召回顺序')
                return self.result(hits,method,warnings,score_type='检索相关性，不是正确率或同件概率',requires_human_confirmation=True)
            except ValueError:
                warnings.append('向量模型本次不可用，退回关键词检索')
        elif semantic:
            warnings.append('尚无匹配版本的向量索引，使用关键词检索')
        words = self._tokenize(query)
        scored = [{**r,'score':sum(w in self.content(r).lower() for w in words)} for r in rows]
        hits = sorted([r for r in scored if r['score']>0],key=lambda r:r['score'],reverse=True)[:5]
        return self.result(hits,method+' / 关键词',warnings,score_type='关键词命中数',requires_human_confirmation=True)

    def status(self):
        return {'classification':'synthetic','dataset':self.version,'counts':{k:sum(r['kind']==k for r in self.records) for k in ('stock','quote','alternative','rule')},'vector_index_ready':bool(self.vectors()),'embedding_model':'bge-m3','matrixone':{**MO_STATUS,'configured':bool(matrixone.settings())},'rerank_enabled':os.getenv('RFQ_REFERENCE_RERANK')=='1'}
