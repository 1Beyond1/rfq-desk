import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from apps.api import main
from apps.api.platform_snapshot import CatalogSnapshotAdapter,Settings,prepare_synthetic_snapshot,BASE_URL
from scripts.platform_contract_fixture import fixture


def prepared():
    case,sources=fixture()
    return prepare_synthetic_snapshot(case,sources)


def settings(**values):
    return Settings(**({'enabled':True,'key':'test-only-secret','workspace_id':'test-workspace','volume_id':123}|values))


def publish(adapter,snapshot=None,**values):
    s=snapshot or prepared()
    return asyncio.run(adapter.publish(s,expected_sha256=values.pop('expected_sha256',s.sha256),**values))


def test_snapshot_keeps_business_identity_original_and_decision_without_mutating_input():
    case,sources=fixture();before=deepcopy(case);s=prepare_synthetic_snapshot(case,sources);doc=json.loads(s.content)
    assert case==before and s==prepare_synthetic_snapshot(case,sources)
    assert [r['fields']['rfq'] for r in doc['rows']]==['009501','009502']
    assert [r['fields']['quantity'] for r in doc['rows']]==['5','3']
    assert doc['rows'][0]['original_fields']['quantity']=='2'
    assert doc['rows'][0]['provenance']['quantity']['decision_id']==doc['human_decisions'][0]['id']
    assert doc['rows'][0]['field_sources']['quantity'][0]['sha256']==hashlib.sha256(sources['base.eml']).hexdigest()
    assert doc['platform_native_versioning'] is False and doc['revision']==2
    assert 'MIME text' in doc['sources'][0]['location'] and b'Subject:' not in s.content


def test_disabled_and_missing_live_authorization_make_no_request(monkeypatch):
    calls=[];transport=httpx.MockTransport(lambda r:calls.append(r))
    assert publish(CatalogSnapshotAdapter(Settings(),transport))['state']=='disabled' and not calls
    # Poison the network constructor: the un-authorized live path must stop before opening it.
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:pytest.fail('network client constructed'))
    assert publish(CatalogSnapshotAdapter(settings()))['state']=='waiting_external_authorization'


def test_public_multipart_and_association_contract():
    s=prepared();calls=[]
    def handler(r):
        calls.append(r)
        assert r.headers['X-API-Key']=='test-only-secret' and r.headers['X-Workspace-ID']=='test-workspace'
        assert 'authorization' not in r.headers and 'cookie' not in r.headers
        assert str(r.url).startswith(BASE_URL) and r.method=='POST'
        if len(calls)==1:
            assert r.url.path=='/v5/catalog/file/upload' and 'multipart/form-data' in r.headers['content-type']
            assert b'name="file"' in r.content and s.content in r.content
            return httpx.Response(200,json={'code':'OK','msg':'OK','data':{'file_id':'received-file-42'}})
        assert r.url.path=='/v5/catalog/file/create'
        assert json.loads(r.content)=={'volume_id':123,'file_ids':['received-file-42']}
        return httpx.Response(200,json={'code':'OK','msg':'OK','data':None})
    result=publish(CatalogSnapshotAdapter(settings(),httpx.MockTransport(handler)),s)
    assert len(calls)==2 and result['file_id']=='received-file-42'
    assert result['state']=='contract_acknowledged' and result['platform_call']=='not_run' and result['native_versioning']=='not_run'
    assert 'test-only-secret' not in json.dumps(result) and 'test-only-secret' not in repr(settings())


@pytest.mark.parametrize('failure',['upload_status','upload_invalid','upload_timeout','association_error','association_timeout','redirect'])
def test_partial_or_unknown_failure_is_honest_no_retry_no_delete(failure):
    calls=[]
    def handler(r):
        calls.append(r.url.path)
        if len(calls)==1:
            if failure=='upload_timeout':raise httpx.ReadTimeout('test secret must not be echoed',request=r)
            if failure=='upload_status':return httpx.Response(400,json={'code':'ErrParamInvalid','data':None})
            if failure=='upload_invalid':return httpx.Response(200,json={'code':'OK','data':{}})
            if failure=='redirect':return httpx.Response(307,headers={'Location':'https://example.invalid/steal'})
            return httpx.Response(200,json={'code':'OK','data':{'file_id':'received-file-42'}})
        if failure=='association_timeout':raise httpx.ReadTimeout('test secret',request=r)
        return httpx.Response(403,json={'code':'Denied','data':None})
    result=publish(CatalogSnapshotAdapter(settings(),httpx.MockTransport(handler)))
    assert result['state']!='contract_acknowledged' and len(calls)==(2 if failure.startswith('association') else 1)
    if failure.startswith('association'):assert result['file_id']=='received-file-42'
    if failure=='association_timeout':assert result['state']=='association_outcome_unknown'
    assert result['platform_call']=='not_run' and 'secret' not in json.dumps(result)


def test_invalid_binding_config_and_source_rejected_before_transport():
    calls=[];transport=httpx.MockTransport(lambda r:calls.append(r));s=prepared()
    for config in [settings(base_url='https://example.invalid/v5'),settings(workspace_id=''),settings(volume_id=0),settings(key='')]:
        with pytest.raises(ValueError):publish(CatalogSnapshotAdapter(config,transport),s)
    for snap,expected in [(s,'old-hash'),(replace(s,content=s.content+b' '),s.sha256),(replace(s,revision=1),s.sha256)]:
        with pytest.raises(ValueError):publish(CatalogSnapshotAdapter(settings(),transport),snap,expected_sha256=expected)
    case,sources=fixture()
    with pytest.raises(ValueError):prepare_synthetic_snapshot(case,{'base.eml':sources['base.eml']+b'private data'})
    case['rows'][0]['sources'][0]['file']='official.eml'
    with pytest.raises(ValueError):prepare_synthetic_snapshot(case,sources)
    assert not calls


def test_no_application_hook_or_default_network_behavior(monkeypatch):
    monkeypatch.delenv('RFQ_ENABLE_PLATFORM_SNAPSHOT_REQUESTS',raising=False)
    assert Settings.from_env().enabled is False
    monkeypatch.setenv('RFQ_ENABLE_PLATFORM_SNAPSHOT_REQUESTS','1')
    with TestClient(main.app) as client:
        health=client.get('/api/health').json()
        assert (health['mode'],health['model_connected'],health['platform_connected'])==('offline-local',False,False)
    assert not any('platform' in r.path or 'snapshot' in r.path for r in main.app.routes)
