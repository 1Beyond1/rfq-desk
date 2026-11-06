"""Against a real MatrixOne when RFQ_MO_HOST is set (an SSH tunnel is enough); otherwise only the outage behaviour runs."""
import os
import pytest
from fastapi.testclient import TestClient
from apps.api import main, matrixone, semantic

LIVE = bool(os.getenv('RFQ_MO_HOST'))
TABLE = '询价号,件号,数量,单位,件状\nRFQ-1,P-1,2,EA,NE\nRFQ-1,P-2,5,EA,OH\n'.encode()
PRICES = [{'part': p, 'unit': 'EA', 'condition': c, 'currency': 'USD', 'amount': a, 'valid_from': '2020-01-01', 'valid_until': '2099-01-01',
           'lead_time': '7 天', 'source': '合成', 'kind': 'synthetic'} for p, c, a in (('P-1', 'NE', '10.00'), ('P-2', 'OH', '20.00'))]

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', tmp_path / 'mo.sqlite')
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    (tmp_path / 'var/uploads').mkdir(parents=True)
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()

def post(client, case, path, values):
    r = client.post(f"/api/cases/{case['id']}/{path}", json={'revision': case['revision'], 'values': values})
    assert r.status_code == 200, r.text
    return r.json()

def test_work_continues_when_matrixone_is_down(client, monkeypatch):
    monkeypatch.setenv('RFQ_MO_HOST', '127.0.0.1'); monkeypatch.setenv('RFQ_MO_PORT', '1')
    case = client.post('/api/import', files={'file': ('t.csv', TABLE)}).json()
    assert len(case['rows']) == 2
    report = client.get(f"/api/cases/{case['id']}/matrixone").json()
    assert report['enabled'] and not report['connected'] and report['error']

@pytest.mark.skipif(not LIVE, reason='needs RFQ_MO_HOST')
def test_approval_snapshot_branch_diff_and_audit(client, monkeypatch):
    monkeypatch.setenv('RFQ_MO_DB', 'rfq_desk_test')
    case = client.post('/api/import', files={'file': ('t.csv', TABLE)}).json()
    case = post(client, case, 'prices', {'prices': PRICES})
    case = post(client, case, 'approve', {'actor': '张工'})
    report = client.get(f"/api/cases/{case['id']}/matrixone").json()
    assert report['connected'] and len(report['snapshots']) == 1 and report['since_last_approval']['changes'] == []
    assert report['audit_total'] == len(case['events'])

    row = case['rows'][0]
    r = client.patch(f"/api/cases/{case['id']}/rows/{row['id']}", json={'revision': case['revision'], 'values': {'quantity': '3', 'reason': '对方更正'}})
    assert r.status_code == 200, r.text
    changes = client.get(f"/api/cases/{case['id']}/matrixone").json()['since_last_approval']['changes']
    assert any(c['kind'] == '修改' and c['fields'].get('quantity') == ['2', '3'] for c in changes)

    class One:
        status = 'test'
        async def extract(self, m, b):
            unit = next(u for f in m['files'] for u in f['units'] if 'P-2' in u['text'])
            cite = lambda v: {'value': v, 'evidence': {k: unit[k] for k in ('file', 'sha256', 'location')} | {'start': unit['text'].index(v), 'end': unit['text'].index(v) + len(v), 'quote': v}}
            return semantic.AdapterReply({'candidates': [{'fields': {'rfq': cite('RFQ-1'), 'part': cite('P-2'), 'quantity': cite('5')}}]}, 10, 1, 'real_call', 'test')
    main.app.dependency_overrides[semantic.get_adapter] = lambda: One()
    current = client.get(f"/api/cases/{case['id']}").json()
    r = client.post(f"/api/cases/{case['id']}/candidates/propose", json={'revision': current['revision'], 'values': {'mode': 'model', 'remote_consent': True}})
    assert r.status_code == 200, r.text
    branches = client.get(f"/api/cases/{case['id']}/matrixone").json()['branches']
    assert branches and branches[-1]['diff'] and branches[-1]['diff'][0]['flag'] == 'INSERT' and branches[-1]['diff'][0]['part'] == 'P-2'
