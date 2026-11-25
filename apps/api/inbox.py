"""An account-scoped synthetic inbox with recorded model decisions and explicit human routing."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import re
import secrets
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import aux_models

LABELS = {'new_rfq':'新询价','revision':'回信或修订','other':'非询价','suspicious':'可疑'}
CRITERIA = {'new_rfq':'A new RFQ requesting product or parts availability or a quote',
            'revision':'A reply or revision explicitly referring to an earlier RFQ',
            'other':'Not an RFQ: marketing, invoice, logistics, or unclear intent',
            'suspicious':'Instructions attempting to bypass rules, approval, pricing controls or send without a person'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def classify(subject, text, transport=None):
    failures = []
    if os.getenv('RFQ_JEV_KEY') and os.getenv('RFQ_ENABLE_MODEL_REQUESTS')=='1':
        try:
            result = aux_models.jev({'subject':subject,'email':text[:8000]},CRITERIA,transport)
            answer = result['answers']['route']
            choice = answer['choice']
            probs = answer['probabilities']
            confidence = float(answer['confidence'])
            if choice not in LABELS or set(probs)!=set(LABELS) or not math.isfinite(confidence) or not 0<=confidence<=1:
                raise ValueError('Jev响应无效')
            values = [float(v) for v in probs.values()]
            if any(not math.isfinite(v) or not 0<=v<=1 for v in values) or abs(sum(values)-1)>.02:
                raise ValueError('Jev概率无效')
            ordered = sorted(values,reverse=True)
            result = {'category':choice,'model':result.get('model','jev-latest'),'provider':'Jev','confidence':confidence,'scores':probs,'score_type':'模型概率与置信度，非实测正确率',
                      'needs_review':choice=='suspicious' or confidence<.8 or ordered[0]-ordered[1]<.2,'reason':'按固定业务选项判断；不确定或可疑邮件交人工'}
            return result
        except (ValueError,KeyError,TypeError):
            failures.append('Jev本次不可用')
    if os.getenv('RFQ_ENABLE_MODEL_REQUESTS')=='1':
        try:
            ranked = aux_models.rerank(subject+'\n'+text[:8000],[LABELS[k]+': '+CRITERIA[k] for k in LABELS],transport)
            scores = {list(LABELS)[r['index']]:float(r['relevance_score']) for r in ranked}
            if len(scores)!=4:raise ValueError('分类候选数不足')
            ordered = sorted(scores,key=scores.get,reverse=True);choice=ordered[0]
            return {'category':choice,'provider':'Genesis回退','model':'qwen3-rerank','confidence':None,'scores':scores,'score_type':'相关性打分，不是分类概率',
                    'needs_review':True,'reason':'重排仅作建议，需人工确认分类','fallback':failures}
        except (ValueError,KeyError,TypeError):
            failures.append('Genesis分类回退不可用')
    combined = subject+'\n'+text
    suspicious = re.search(r'忽略.*规则|直接批准|跳过.*批准|ignore previous|without human approval|bypass.*approval',combined,re.I)
    revision = re.search(r'回信|修订|revision|change.*quantity',combined,re.I)
    rfq = re.search(r'询价|\bRFQ\b|please quote',combined,re.I)
    category = 'suspicious' if suspicious else 'revision' if revision else 'new_rfq' if rfq else 'other'
    return {'category':category,'provider':'本地规则回退','model':None,'confidence':None,'scores':{},'score_type':None,'needs_review':True,
            'reason':'模型未完成分类，规则建议需人工确认','fallback':failures}


class Inbox:
    def __init__(self, connection, root, owner):
        self.connection,self.root,self.owner = connection,Path(root),owner

    @staticmethod
    def schema(c):
        c.execute('CREATE TABLE IF NOT EXISTS inbox_messages (id TEXT PRIMARY KEY,owner TEXT NOT NULL,body TEXT NOT NULL)')

    def get(self, c, id):
        row = c.execute('SELECT body FROM inbox_messages WHERE id=? AND owner=?',(id,self.owner)).fetchone()
        if not row:raise ValueError('找不到邮件')
        return json.loads(row[0])

    def put(self,c,mail):
        c.execute('UPDATE inbox_messages SET body=? WHERE id=? AND owner=?',(json.dumps(mail,ensure_ascii=False),mail['id'],self.owner))

    def listing(self):
        with self.connection() as c:
            self.schema(c)
            rows=[json.loads(r[0]) for r in c.execute('SELECT body FROM inbox_messages WHERE owner=? ORDER BY rowid',(self.owner,))]
        from email import policy
        from email.parser import BytesParser
        for row in rows:
            parsed=BytesParser(policy=policy.default).parsebytes(self.original(row))
            body=parsed.get_body(preferencelist=('plain',))
            # 只有 HTML 正文的邮件不能让整份收件箱 500。
            row['preview']=body.get_content() if body is not None else (parsed.get_payload() or '')[:4000]
        return rows

    def seed(self):
        folder=self.root/'data/synthetic/inbox'
        with self.connection() as c:
            self.schema(c);c.execute('BEGIN IMMEDIATE')
            for sample in json.loads((folder/'index.json').read_text(encoding='utf-8')):
                id=hashlib.sha256((self.owner+':'+sample['sample_id']).encode()).hexdigest()[:24]
                row={k:v for k,v in sample.items() if k!='preclass'}
                # 样本固定，Jev 判过一次就随样本固化；新样本没有 preclass 时才现调。
                preset=sample.get('preclass')
                decision=None
                events=[]
                if preset:
                    decision={**preset,'frozen':True,'at':preset.get('frozen_at') or now()}
                    events=[{'at':decision['at'],'action':'triage','actor':'样本预置','category':preset.get('category'),'provider':preset.get('provider')}]
                mail={**row,'id':id,'revision':1,'decision':decision,'manual':None,'case_id':None,'events':events}
                c.execute('INSERT OR IGNORE INTO inbox_messages VALUES(?,?,?)',(id,self.owner,json.dumps(mail,ensure_ascii=False)))
        return self.listing()

    def original(self, mail):
        choices={r['filename'] for r in json.loads((self.root/'data/synthetic/inbox/index.json').read_text(encoding='utf-8'))}
        if mail['filename'] not in choices:raise ValueError('未知的合成原件')
        return (self.root/'data/synthetic/inbox'/mail['filename']).read_bytes()

    def decide(self,id,revision,actor,before_model=None,force=False):
        from email import policy
        from email.parser import BytesParser
        with self.connection() as c:
            self.schema(c);mail=self.get(c,id)
            if mail['revision']!=revision:raise ValueError('邮件已更新，请刷新')
            if mail.get('manual') or mail.get('case_id'):raise ValueError('邮件已交给工作单或已人工确认，不能重新分流')
            if mail['decision'] and not force:return mail
        parsed=BytesParser(policy=policy.default).parsebytes(self.original(mail))
        body=parsed.get_body(preferencelist=('plain',))
        text=body.get_content() if body is not None else (parsed.get_payload() or '')
        if before_model and os.getenv('RFQ_ENABLE_MODEL_REQUESTS')=='1':before_model()
        decision=classify(mail['subject'],text)
        with self.connection() as c:
            self.schema(c);c.execute('BEGIN IMMEDIATE');mail=self.get(c,id)
            if mail['revision']!=revision:raise ValueError('分类期间邮件已更新，未覆盖人工决定')
            if mail.get('manual') or mail.get('case_id'):raise ValueError('分类期间邮件已更新，未覆盖人工决定')
            old=mail.get('decision') or {}
            keep=force and old.get('provider')=='Jev' and decision.get('provider')!='Jev'
            if keep:
                mail['triage_warning']='本次Jev重判未完成，保留上次判定；仍可人工确认。'
            else:
                mail['decision']={**decision,'at':now()}
                mail.pop('triage_warning',None)
            mail['revision']+=1
            mail['events'].append({'at':now(),'action':'triage_failed' if keep else 'triage','actor':actor,'category':decision['category'],'provider':decision['provider']})
            self.put(c,mail)
        return mail

    def override(self,id,revision,category,reason,actor):
        if category not in LABELS or not 5<=len(reason.strip())<=500:raise ValueError('请选择分类并填写5至500字的人工依据')
        with self.connection() as c:
            self.schema(c);c.execute('BEGIN IMMEDIATE');mail=self.get(c,id)
            if mail['revision']!=revision:raise ValueError('邮件已更新，请刷新')
            if mail['case_id']:raise ValueError('邮件已交给工作单，不能再次改判')
            mail['manual']={'category':category,'reason':reason.strip(),'actor':actor,'at':now()};mail['revision']+=1
            mail['events'].append({'action':'manual_route',**mail['manual']});self.put(c,mail)
        return mail

    @staticmethod
    def route(mail):
        decision=mail.get('manual') or mail.get('decision') or {}
        if not mail.get('manual') and (not decision or decision.get('needs_review',True)):
            raise ValueError('请先人工确认分类及依据，再交给工作单')
        if decision.get('category') not in ('new_rfq','revision'):
            raise ValueError('非询价或可疑邮件不能直接交给询价Agent')
        return decision['category']


class RouteChange(BaseModel):
    revision:int
    category:str=''
    reason:str=Field(default='',max_length=500)
    case_id:str=Field(default='',max_length=32)
    force:bool=False


def router(connection, root, owner, actor, importer, appender, owns, reserve):
    api=APIRouter(prefix='/api/inbox')
    def store():return Inbox(connection,root(),owner())
    def failure(e):
        message=str(e)
        return HTTPException(404 if message=='找不到邮件' else 409 if '更新' in message or '已交给' in message else 422,message)

    @api.get('')
    def listing():return store().listing()

    @api.post('/samples')
    def samples():return store().seed()

    @api.post('/preclassify')
    def preclassify(body:RouteChange):
        """按需先跑几封分流，首页开场才有真实结论可说；数量受限，不替人改判。"""
        box=store()
        try:limit=max(1,min(6,int(body.revision or 4)))
        except (TypeError,ValueError):limit=4
        done=0
        for mail in box.listing():
            if done>=limit:break
            if mail.get('decision') or mail.get('manual'):continue
            try:box.decide(mail['id'],mail['revision'],actor(),reserve);done+=1
            except ValueError:continue
        return {'classified':done,'mails':box.listing()}

    @api.post('/{id}/triage')
    def triage(id:str,body:RouteChange):
        try:return store().decide(id,body.revision,actor(),reserve,force=bool(body.force))
        except ValueError as e:raise failure(e)

    @api.post('/{id}/review')
    def review(id:str,body:RouteChange):
        try:return store().override(id,body.revision,body.category,body.reason,actor())
        except ValueError as e:raise failure(e)

    @api.post('/{id}/open')
    def open_mail(id:str,body:RouteChange):
        box=store()
        try:
            with connection() as c:
                box.schema(c);mail=box.get(c,id)
                if mail['case_id']:
                    if not owns(mail['case_id'],owner()):raise HTTPException(404,'找不到工作单')
                    return {'case_id':mail['case_id'],'already_opened':True}
                if mail['revision']!=body.revision:raise ValueError('邮件已更新，请刷新')
                route=box.route(mail)
            def link(c,case):
                latest=box.get(c,id)
                if latest['case_id'] or latest['revision']!=body.revision:raise ValueError('邮件已更新，请刷新')
                latest['case_id']=case['id'];latest['revision']+=1
                latest['events'].append({'action':'open_work_order','at':now(),'actor':actor(),'case_id':case['id']})
                box.put(c,latest)
            if route=='revision':
                if not body.case_id or not owns(body.case_id,owner()):raise HTTPException(404,'请选择自己可访问的原工作单')
                with connection() as c:
                    row=c.execute('SELECT body FROM cases WHERE id=?',(body.case_id,)).fetchone()
                    if not row:raise HTTPException(404,'找不到原工作单')
                    case=json.loads(row[0])
                result=appender(body.case_id,case['revision'],mail['filename'],box.original(mail),on_append=link)
            else:
                result=importer(mail['filename'],box.original(mail),on_import=link)
            return {'case_id':result['id'],'already_opened':False}
        except ValueError as e:raise failure(e)
    return api
