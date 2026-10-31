"""Opt-in MOI Catalog file contract; no hooks into imports, edits, approval or startup.

JSON content is our own snapshot schema, never a MOI branch/revision API.
Contract checked 2026-10-25: see docs/PLATFORM_READINESS.md. No live call verified.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import os
import re
import httpx
from .domain import FIELDS

BASE_URL = 'https://api.moi.matrixorigin.cn/v5'
SYNTHETIC_SOURCE_SHA = '37a6beb22a65665ee7b5b0b6a2db20d21fcc2b04f16a5285f78f56783d1a016b'


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    base_url: str = BASE_URL
    key: str = field(default='', repr=False)
    workspace_id: str = ''
    volume_id: int = 0

    @classmethod
    def from_env(cls):
        volume = os.getenv('RFQ_MOI_VOLUME_ID', '')
        return cls(os.getenv('RFQ_ENABLE_PLATFORM_SNAPSHOT_REQUESTS') == '1',
                   os.getenv('RFQ_MOI_BASE_URL', BASE_URL), os.getenv('RFQ_MOI_API_KEY', ''),
                   os.getenv('RFQ_MOI_WORKSPACE_ID', ''), int(volume) if volume.isdecimal() else 0)

    def validate(self):
        # Pin the documented contract; never forward credentials to redirects/other gateways.
        if self.base_url != BASE_URL: raise ValueError('未核验的服务地址；本适配只支持已核实的v5契约')
        if not self.key or not self.workspace_id.strip() or type(self.volume_id) is not int or self.volume_id <= 0:
            raise ValueError('缺少个人访问令牌、目标工作区ID或有效目标卷ID')


@dataclass(frozen=True)
class Snapshot:
    content: bytes
    sha256: str
    case_id: str
    revision: int


def prepare_synthetic_snapshot(case, sources):
    """Local-only preparation; allowlisted fixture originals, no DB/file discovery.

Source allowlisting alone does not approve human notes. publish() additionally binds
the exact reviewed payload hash; current CLI only constructs the fixed synthetic fixture.
"""
    if not sources or any(hashlib.sha256(b).hexdigest() != SYNTHETIC_SOURCE_SHA for b in sources.values()):
        raise ValueError('只支持本轮已审查合成原件；真实/官方材料不得进入此适配')
    if not isinstance(case.get('revision'), int) or case['revision'] < 1: raise ValueError('缺少本地工作版本')
    source_refs = []
    rows = []
    for row in case['rows']:
        citations = list(row['sources'])
        for p in row.get('field_provenance', {}).values(): citations.extend(p.get('sources', []))
        for s in citations:
            if s.get('file') not in sources or s.get('sha256') != hashlib.sha256(sources[s['file']]).hexdigest():
                raise ValueError('出处未绑定本次允许的原件/hash')
            ref = {k:s[k] for k in ('file', 'sha256', 'location')}
            if ref not in source_refs: source_refs.append(ref)
        rows.append({'id':row['id'], 'revision':row['revision'], 'fields':{f:row[f] for f in FIELDS},
                     'original_fields':deepcopy(row['raw_fields']), 'excluded':row['excluded'],
                     'resolution':row['resolution'],
                     'field_sources':{f:[{k:s[k] for k in ('file','sha256','location')} for s in row.get('field_provenance',{}).get(f,{}).get('sources',row['sources'])] for f in FIELDS},
                     'provenance':{f:{k:deepcopy(v) for k,v in p.items() if k != 'sources'} for f,p in row.get('field_provenance',{}).items()}})
    doc = {'schema':'rfq-local-snapshot/v1', 'classification':'synthetic_contract_fixture',
           'platform_native_versioning':False, 'case_id':case['id'], 'revision':case['revision'],
           'price_version':case['price_version'], 'sources':source_refs, 'rows':rows,
           'human_decisions':[{k:deepcopy(d[k]) for k in ('id','row_id','field','from','to','actor','reason','kind')} for d in case.get('human_decisions',[])],
           'events':[{'action':e['action'],'time':e['time']} for e in case.get('events',[])]}
    content = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode('utf-8')
    if len(content) > 256*1024: raise ValueError('快照超过本适配256KiB范围')
    return Snapshot(content, hashlib.sha256(content).hexdigest(), case['id'], case['revision'])


class CatalogSnapshotAdapter:
    def __init__(self, settings=None, transport=None):
        self.settings = settings or Settings.from_env()
        if transport is not None and not isinstance(transport, httpx.MockTransport):
            raise ValueError('测试注入仅允许httpx.MockTransport')
        self.transport = transport

    async def publish(self, snapshot, *, expected_sha256, live_authorized=False):
        injected = self.transport is not None
        result = {'mode':'contract_injection' if injected else 'platform', 'platform_call':'not_run',
                  'native_versioning':'not_run', 'state':'disabled', 'requests':0,
                  'case_id':snapshot.case_id, 'revision':snapshot.revision, 'sha256':snapshot.sha256}
        if not self.settings.enabled: return result
        self.settings.validate()
        if not injected and live_authorized is not True:
            return {**result, 'state':'waiting_external_authorization'}
        actual_hash = hashlib.sha256(snapshot.content).hexdigest()
        if expected_sha256 != actual_hash or snapshot.sha256 != actual_hash:
            raise ValueError('快照与明确核对的hash不一致，未传输')
        payload = json.loads(snapshot.content)
        if payload.get('classification') != 'synthetic_contract_fixture' or payload.get('schema') != 'rfq-local-snapshot/v1':
            raise ValueError('不是本轮合成快照，未传输')
        if payload.get('case_id') != snapshot.case_id or payload.get('revision') != snapshot.revision:
            raise ValueError('快照工作单/版本绑定不一致')
        if not payload.get('sources') or any(s.get('sha256') != SYNTHETIC_SOURCE_SHA for s in payload['sources']):
            raise ValueError('快照含未允许的原件，未传输')
        result['platform_call'] = 'not_run' if injected else 'attempted'
        headers = {'X-API-Key':self.settings.key, 'X-Workspace-ID':self.settings.workspace_id}
        async with httpx.AsyncClient(transport=self.transport, trust_env=False, follow_redirects=False, timeout=10) as client:
            try:
                result.update(state='upload_outcome_unknown', requests=1)
                upload = await client.post(self.settings.base_url+'/catalog/file/upload', headers=headers,
                                           files={'file':(f'rfq-{snapshot.case_id}-r{snapshot.revision}-{snapshot.sha256[:12]}.json',snapshot.content,'application/json')})
                body = upload.json()
                if upload.status_code != 200 or body.get('code') != 'OK':
                    return {**result, 'state':'upload_failed_record_may_exist', 'http_status':upload.status_code}
                file_id = body.get('data',{}).get('file_id')
                if not isinstance(file_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',file_id):
                    return {**result, 'state':'upload_response_invalid_record_may_exist'}
                result.update(file_id=file_id,state='association_outcome_unknown',requests=2)
                linked = await client.post(self.settings.base_url+'/catalog/file/create', headers=headers,
                                           json={'volume_id':self.settings.volume_id,'file_ids':[file_id]})
                body = linked.json()
                if linked.status_code != 200 or body.get('code') != 'OK' or body.get('data','missing') is not None:
                    return {**result, 'state':'association_not_confirmed', 'http_status':linked.status_code}
                # Ack is not read-back verification, a native revision or competition compliance.
                return {**result, 'state':'contract_acknowledged' if injected else 'associated_readback_not_run'}
            except (httpx.HTTPError, ValueError, AttributeError, TypeError):
                # No retries: upload may have created a record. Never echo response bodies/secrets.
                return result
