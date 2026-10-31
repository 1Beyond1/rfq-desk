from pathlib import Path
import json
from fastapi.testclient import TestClient
from apps.api import main

ROOT=Path(__file__).resolve().parents[1]

def test_original_tampering_blocks_approval_and_export(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',tmp_path/'case.sqlite');client=TestClient(main.app)
    case=client.post('/api/lifecycle-demo').json();id=case['id'];row_id=case['rows'][0]['id']
    task=json.loads((ROOT/'evals/cases/tasks/lifecycle.json').read_text(encoding='utf-8-sig'))
    case=client.post(f'/api/cases/{id}/prices',json={'revision':case['revision'],'values':{'prices':task['events'][0]['prices']}}).json()
    checked=client.get(f'/api/cases/{id}/evidence/{row_id}').json()
    assert checked['integrity_ok'] and checked['fields']['quantity']['supported']
    case=client.post(f'/api/cases/{id}/approve',json={'revision':case['revision'],'values':{'actor':'synthetic test'}}).json()
    assert client.get(f'/api/cases/{id}/export').status_code==200
    path=ROOT/'var/uploads'/id/'lifecycle.eml';original=path.read_bytes()
    try:
        path.write_bytes(original+b'\nModified original')
        assert not client.get(f'/api/cases/{id}/evidence/{row_id}').json()['integrity_ok']
        assert client.get(f'/api/cases/{id}/export').status_code==409
        assert client.post(f'/api/cases/{id}/approve',json={'revision':case['revision'],'values':{'actor':'test'}}).status_code==422
    finally:path.write_bytes(original)

def test_human_correction_is_never_presented_as_original_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',tmp_path/'case.sqlite');client=TestClient(main.app)
    case=client.post('/api/lifecycle-demo').json();id=case['id'];row_id=case['rows'][0]['id']
    response=client.patch(f'/api/cases/{id}/rows/{row_id}',json={'revision':case['revision'],'values':{'quantity':'4','reason':'Synthetic human clarification: quantity is 4'}})
    assert response.status_code==200
    info=client.get(f'/api/cases/{id}/evidence/{row_id}').json()['fields']['quantity']
    assert info['original']=='3' and info['value']=='4' and info['manual'] and not info['supported']
    assert info['record']['fields']['quantity']=='3'
