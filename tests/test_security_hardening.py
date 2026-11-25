"""Regression tests covering P1-1..P1-5 and P2-1..P2-8 backend security hardening and bug fixes."""
import asyncio
import csv
import io
import json
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import zipfile
from copy import deepcopy
from email.message import EmailMessage
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import httpx
import openpyxl
import pytest
from fastapi.testclient import TestClient

from apps.api import accounts, agent, aux_models, domain, inbox, main, matrixone, model_config, parsing, price_intake, semantic
from evals.judges.evidence import EvidenceIndex
from scripts.serve_web import Handler, WebServer

ROOT = Path(__file__).resolve().parents[1]
PRICE = {
    'part': 'P-1', 'unit': 'EA', 'condition': 'FN', 'currency': 'USD', 'amount': '10.00',
    'valid_from': '2020-01-01', 'valid_until': '2099-12-31', 'lead_time': '7 days',
    'source': 'SYN-SEC', 'kind': 'synthetic',
}
TWO_ROWS_CSV = (
    'rfq,partnumber,quantity,unit,condition\n'
    'R1,P-1,2,EA,FN\n'
    'R2,P-1,3,EA,FN\n'
).encode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'DB', tmp_path / 'sec.sqlite3')
    monkeypatch.setattr(main, 'SCOPED', False)
    monkeypatch.setenv('RFQ_AUTH_REQUIRED', '0')
    monkeypatch.delenv('RFQ_MO_HOST', raising=False)
    monkeypatch.delenv('RFQ_ENABLE_DOCS', raising=False)
    yield TestClient(main.app), tmp_path
    main.app.dependency_overrides.clear()


@pytest.fixture
def auth_env(tmp_path, monkeypatch):
    monkeypatch.setenv('RFQ_AUTH_REQUIRED', '1')
    monkeypatch.setenv('RFQ_COOKIE_SECURE', '0')
    monkeypatch.setenv('RFQ_PUBLIC_ORIGIN', 'http://testserver')
    monkeypatch.delenv('RFQ_ENABLE_DOCS', raising=False)
    monkeypatch.delenv('RFQ_DEMO_IP_LIMIT', raising=False)
    monkeypatch.delenv('RFQ_DEMO_AI_CALLS', raising=False)
    monkeypatch.delenv('RFQ_DEMO_DAILY_CALLS', raising=False)
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'DB', tmp_path / 'auth.sqlite3')
    monkeypatch.setattr(main, 'SCOPED', False)
    shutil.copytree(ROOT / 'data/synthetic', tmp_path / 'data/synthetic')
    yield tmp_path
    main.app.dependency_overrides.clear()


def _approved_two_row_case(client):
    c = client.post('/api/import', files={'file': ('two.csv', TWO_ROWS_CSV)}).json()
    r = client.post(f"/api/cases/{c['id']}/prices", json={'revision': c['revision'], 'values': {'prices': [PRICE]}})
    assert r.status_code == 200, r.text
    c = r.json()
    r = client.post(f"/api/cases/{c['id']}/approve", json={'revision': c['revision'], 'values': {'actor': 'reviewer'}})
    assert r.status_code == 200, r.text
    return r.json()


def _enter_demo(client):
    r = client.post('/api/auth/demo', json={})
    assert r.status_code == 200, r.text
    s = r.json()
    client.headers.update({'X-RFQ-Account': s['user']['id'], 'X-CSRF-Token': s['csrf']})
    return s


# ---------------- P1-1: Approval Snapshot Invalidation ----------------

def test_p1_1_exclude_row_invalidates_approval_and_blocks_shrunken_export(env):
    client, _ = env
    c = _approved_two_row_case(client)
    url = f"/api/cases/{c['id']}"
    assert client.get(f"{url}/export?format=json&revision={c['revision']}").status_code == 200

    # Single-row exclude must invalidate approval so a shrunken 1-row quote cannot be exported.
    r = client.patch(
        f"{url}/rows/{c['rows'][0]['id']}",
        json={'revision': c['revision'], 'values': {'excluded': True, 'reason': 'remove first line'}},
    )
    assert r.status_code == 200, r.text
    c = r.json()
    assert not c['rows'][0]['approved']
    assert client.get(f"{url}/export?format=json&revision={c['revision']}").status_code == 409
    assert client.post(f"{url}/exports", json={'revision': c['revision'], 'values': {'format': 'json'}}).status_code == 409
    assert client.get(f"{url}/quote-preview?format=json&revision={c['revision']}").status_code == 409


def test_p1_1_bulk_exclude_then_restore_cannot_resurrect_approval(env):
    client, _ = env
    c = _approved_two_row_case(client)
    url = f"/api/cases/{c['id']}"
    row_id = c['rows'][0]['id']

    r = client.patch(
        f"{url}/rows",
        json={'revision': c['revision'], 'values': {'row_ids': [row_id], 'excluded': True, 'reason': 'bulk exclude'}},
    )
    assert r.status_code == 200, r.text
    c = r.json()
    assert client.post(f"{url}/exports", json={'revision': c['revision'], 'values': {'format': 'json'}}).status_code == 409

    # Restoring the excluded row via bulk PATCH must NOT resurrect its old approval.
    r = client.patch(
        f"{url}/rows",
        json={'revision': c['revision'], 'values': {'row_ids': [row_id], 'excluded': False, 'reason': 'bulk restore'}},
    )
    assert r.status_code == 200, r.text
    c = r.json()
    assert not c['rows'][0]['approved']
    assert client.post(f"{url}/exports", json={'revision': c['revision'], 'values': {'format': 'json'}}).status_code == 409
    assert client.get(f"{url}/export?format=json&revision={c['revision']}").status_code == 409


def test_p1_1_append_material_and_review_note_invalidate_prior_approval(env):
    client, _ = env
    c = _approved_two_row_case(client)
    url = f"/api/cases/{c['id']}"
    assert client.get(f"{url}/export?format=json&revision={c['revision']}").status_code == 200

    # Appending a new original invalidates prior approval.
    r = client.post(
        f"{url}/materials",
        data={'revision': c['revision']},
        files={'file': ('followup.txt', b'RFQ: R1\nPart: P-1\nQuantity: 9\nUnit: EA\nCondition: FN\n')},
    )
    assert r.status_code == 200, r.text
    c = r.json()
    assert client.get(f"{url}/export?format=json&revision={c['revision']}").status_code == 409
    assert client.post(f"{url}/exports", json={'revision': c['revision'], 'values': {'format': 'json'}}).status_code == 409

    # Re-approve then alter review_note -> prior approval must also become invalid.
    c = client.post(f"{url}/approve", json={'revision': c['revision'], 'values': {'actor': 'reviewer'}}).json()
    assert client.get(f"{url}/export?format=json&revision={c['revision']}").status_code == 200
    c = client.post(f"{url}/review", json={'revision': c['revision'], 'values': {'note': 'changed review note'}}).json()
    assert client.get(f"{url}/export?format=json&revision={c['revision']}").status_code == 409


def test_p1_1_pending_candidate_batch_blocks_approve_and_export_with_409(env):
    client, _ = env
    c = _approved_two_row_case(client)
    url = f"/api/cases/{c['id']}"
    r = client.post(
        f"{url}/materials",
        data={'revision': c['revision']},
        files={'file': ('rev.txt', b'RFQ: R1\nPart: P-1\nQuantity: 5\nUnit: EA\nCondition: FN\n')},
    )
    assert r.status_code == 200
    c = r.json()

    # Propose a pending candidate batch -> both approve() and export_data() must reject with 409!
    r = client.post(f"{url}/candidates/propose", json={'revision': c['revision'], 'values': {'mode': 'offline'}})
    assert r.status_code == 200, r.text
    c = r.json()['case']

    assert client.post(f"{url}/approve", json={'revision': c['revision'], 'values': {'actor': 'reviewer'}}).status_code == 409
    assert client.get(f"{url}/export?format=json&revision={c['revision']}").status_code == 409
    assert client.post(f"{url}/exports", json={'revision': c['revision'], 'values': {'format': 'json'}}).status_code == 409

    # Direct domain calls also raise ConflictError (subclass of ValueError).
    with main.connection() as db:
        raw_case = main.load(db, c['id'])
    with pytest.raises(domain.ConflictError):
        domain.approve(raw_case, 'reviewer')
    with pytest.raises(domain.ConflictError):
        domain.export_data(raw_case)

    # Rejecting the pending candidate unblocks re-approval and export.
    batch = c['candidate_batches'][-1]
    cand = batch['candidates'][0]
    r = client.post(
        f"{url}/candidates/{batch['id']}/{cand['id']}/review",
        json={'revision': c['revision'], 'values': {'action': 'reject', 'reason': 'not adopting'}},
    )
    assert r.status_code == 200, r.text
    c = r.json()
    r = client.post(f"{url}/approve", json={'revision': c['revision'], 'values': {'actor': 'reviewer'}})
    assert r.status_code == 200, r.text
    c = r.json()
    assert client.get(f"{url}/export?format=json&revision={c['revision']}").status_code == 200


# ---------------- P1-2: Demo Rate Limit, Per-Call Quota, Daily Cap & Cleanup ----------------

def test_p1_2_demo_ip_rate_limit_default_and_env(auth_env, monkeypatch):
    # Default per-IP limit is 6 / 15 min.
    for _ in range(6):
        with TestClient(main.app) as c:
            assert c.post('/api/auth/demo', json={}).status_code == 200
    with TestClient(main.app) as c:
        assert c.post('/api/auth/demo', json={}).status_code == 429

    # Custom RFQ_DEMO_IP_LIMIT=2 on a fresh DB.
    monkeypatch.setattr(main, 'DB', auth_env / 'auth2.sqlite3')
    monkeypatch.setenv('RFQ_DEMO_IP_LIMIT', '2')
    for _ in range(2):
        with TestClient(main.app) as c:
            assert c.post('/api/auth/demo', json={}).status_code == 200
    with TestClient(main.app) as c:
        assert c.post('/api/auth/demo', json={}).status_code == 429


def test_p1_2_demo_quota_charged_per_actual_model_and_aux_call_and_daily_cap(auth_env, monkeypatch):
    monkeypatch.setenv('RFQ_DEMO_AI_CALLS', '3')
    monkeypatch.setenv('RFQ_DEMO_DAILY_CALLS', '5')
    monkeypatch.setenv('RFQ_ENABLE_MODEL_REQUESTS', '1')
    monkeypatch.setenv('RFQ_MODEL_URL', 'https://model.example.invalid/v1/chat/completions')
    monkeypatch.setenv('RFQ_MODEL_KEY', 'test-key')
    monkeypatch.setenv('RFQ_MODEL_NAME', 'test-model')

    # Multi-step agent turn calling the model 3 times (using local non-model tools) consumes 3 demo calls (not 1!).
    class ThreeCallScript:
        tokens = 10
        requests = 0

        def __init__(self):
            self.steps = [
                {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 't1', 'type': 'function', 'function': {'name': 'get_case_state', 'arguments': '{}'}}]},
                {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 't2', 'type': 'function', 'function': {'name': 'check_prices', 'arguments': '{"part":"SYN-001"}'}}]},
                {'role': 'assistant', 'content': '完成三轮检查。'},
            ]

        async def call(self, messages, final, deadline):
            self.requests += 1
            return self.steps.pop(0)

    main.app.dependency_overrides[main.get_agent_session] = lambda: ThreeCallScript()

    with TestClient(main.app) as demo_a:
        sa = _enter_demo(demo_a)
        case = demo_a.post('/api/guided-demo').json()
        r = demo_a.post(f"/api/cases/{case['id']}/agent", json={'message': '检查一下', 'consent': True})
        assert r.status_code == 200, r.text
        # All 3 calls consumed -> next turn immediately rejected at entry with 429!
        r2 = demo_a.post(f"/api/cases/{case['id']}/agent", json={'message': '再查一次', 'consent': True})
        assert r2.status_code == 429

    # Demo B uses auxiliary model calls (embeddings / rerank); daily demo limit = 5 (3 already used -> only 2 left).
    with TestClient(main.app) as demo_b:
        sb = _enter_demo(demo_b)
        tok = accounts.USER.set(sb['user'])
        try:
            def mock_aux(req):
                if str(req.url).endswith('/embeddings'):
                    return httpx.Response(200, json={'data': [{'index': 0, 'embedding': [0.1, 0.2]}]})
                return httpx.Response(200, json={'results': [{'index': 0, 'relevance_score': 0.9}]})

            transport = httpx.MockTransport(mock_aux)
            assert aux_models.embeddings(['hello'], transport=transport) == [[0.1, 0.2]]  # daily 4
            assert aux_models.rerank('q', ['doc'], transport=transport)[0]['index'] == 0  # daily 5
            # 6th daily demo call hits RFQ_DEMO_DAILY_CALLS even though demo_b only used 2 < 3!
            with pytest.raises(Exception) as exc:
                aux_models.embeddings(['again'], transport=transport)
            assert exc.value.status_code == 429
        finally:
            accounts.USER.reset(tok)

    # Formal users are NOT blocked by demo daily cap.
    formal = main.ACCOUNTS.create('formal1', '正式用户', 'Synthetic formal password 2026', must_change=False)
    tok = accounts.USER.set(formal)
    try:
        main.ACCOUNTS.reserve_demo_call()  # no-op for non-demo role
    finally:
        accounts.USER.reset(tok)


def test_p1_2_cleanup_expired_demos_reclaims_db_and_uploads(auth_env):
    with TestClient(main.app) as demo_a, TestClient(main.app) as demo_b:
        sa = _enter_demo(demo_a)
        sb = _enter_demo(demo_b)
        case_a = demo_a.post('/api/guided-demo').json()
        case_b = demo_b.post('/api/guided-demo').json()
        demo_a.post('/api/inbox/samples')
        demo_b.post('/api/inbox/samples')
        with main.connection() as c:
            c.execute('CREATE TABLE IF NOT EXISTS agent_home_turns (owner TEXT,seq INTEGER PRIMARY KEY AUTOINCREMENT,body TEXT)')
            c.execute('INSERT INTO agent_turns(case_id,body) VALUES (?,?)', (case_a['id'], '{}'))
            c.execute('INSERT INTO agent_home_turns(owner,body) VALUES (?,?)', ('user:' + sa['user']['id'], '{}'))
            # Expire demo_a's session.
            c.execute('UPDATE auth_sessions SET expires=? WHERE user_id=?', (int(time.time()) - 10, sa['user']['id']))

        upload_a = auth_env / 'var/uploads' / case_a['id']
        upload_b = auth_env / 'var/uploads' / case_b['id']
        assert upload_a.is_dir() and upload_b.is_dir()

        # Creating a new demo space triggers cleanup_expired_demos().
        with TestClient(main.app) as demo_c:
            _enter_demo(demo_c)

        assert not upload_a.exists()
        assert upload_b.is_dir()
        with main.connection() as c:
            assert c.execute('SELECT COUNT(*) FROM auth_users WHERE id=?', (sa['user']['id'],)).fetchone()[0] == 0
            assert c.execute('SELECT COUNT(*) FROM auth_sessions WHERE user_id=?', (sa['user']['id'],)).fetchone()[0] == 0
            assert c.execute('SELECT COUNT(*) FROM cases WHERE id=?', (case_a['id'],)).fetchone()[0] == 0
            assert c.execute('SELECT COUNT(*) FROM case_owners WHERE case_id=?', (case_a['id'],)).fetchone()[0] == 0
            assert c.execute('SELECT COUNT(*) FROM agent_turns WHERE case_id=?', (case_a['id'],)).fetchone()[0] == 0
            assert c.execute('SELECT COUNT(*) FROM inbox_messages WHERE owner=?', ('user:' + sa['user']['id'],)).fetchone()[0] == 0
            assert c.execute('SELECT COUNT(*) FROM agent_home_turns WHERE owner=?', ('user:' + sa['user']['id'],)).fetchone()[0] == 0
            # Active demo_b remains untouched.
            assert c.execute('SELECT COUNT(*) FROM auth_users WHERE id=?', (sb['user']['id'],)).fetchone()[0] == 1
            assert c.execute('SELECT COUNT(*) FROM cases WHERE id=?', (case_b['id'],)).fetchone()[0] == 1


# ---------------- P1-3: File Parsing Bomb Protection & Non-blocking Uploads ----------------

def test_p1_3_xlsx_zip_bomb_entry_limit_and_xxe_rejected(env):
    client, _ = env

    # 1. > 200 zip entries
    many = io.BytesIO()
    with zipfile.ZipFile(many, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(205):
            zf.writestr(f'f{i}.txt', b'x')
    with pytest.raises(ValueError):
        parsing.validate_xlsx(many.getvalue())
    assert client.post('/api/import', files={'file': ('many.xlsx', many.getvalue())}).status_code == 422

    # 2. > 30 MB uncompressed zip bomb (compresses to ~30 KB)
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('xl/worksheets/sheet1.xml', b'0' * (31 * 1024 * 1024))
    assert len(bomb.getvalue()) < 1024 * 1024
    with pytest.raises(ValueError):
        parsing.validate_xlsx(bomb.getvalue())
    assert client.post('/api/import', files={'file': ('bomb.xlsx', bomb.getvalue())}).status_code == 422

    # 3. XXE <!DOCTYPE / <!ENTITY inside XML entry
    wb = openpyxl.Workbook()
    wb.active.append(['RFQ No.', 'Part Number', 'Quantity', 'Unit', 'Condition'])
    wb.active.append(['R1', 'P1', 2, 'EA', 'FN'])
    base = io.BytesIO()
    wb.save(base)
    xxe = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base.getvalue()), 'r') as zin, zipfile.ZipFile(xxe, 'w') as zout:
        for info in zin.infolist():
            raw = zin.read(info.filename)
            if info.filename == 'xl/workbook.xml':
                raw = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe "boom">]>' + raw
            zout.writestr(info, raw)
    xxe_bytes = xxe.getvalue()
    with pytest.raises(ValueError):
        parsing.parse_file('xxe.xlsx', xxe_bytes)
    with pytest.raises(ValueError):
        price_intake.parse_prices('xxe.xlsx', xxe_bytes)
    with pytest.raises(ValueError):
        EvidenceIndex().add('xxe.xlsx', xxe_bytes)
    assert client.post('/api/import', files={'file': ('xxe.xlsx', xxe_bytes)}).status_code == 422

    # 4. > 30 sheets rejected
    wb_sheets = openpyxl.Workbook()
    for i in range(31):
        wb_sheets.create_sheet(f'S{i}')
    buf = io.BytesIO()
    wb_sheets.save(buf)
    with pytest.raises(ValueError):
        parsing.parse_file('sheets.xlsx', buf.getvalue())


def test_p1_3_price_intake_streams_xlsx_and_caps_rows():
    # Spoofed A1:XFD1048576 dimension must NOT hang or OOM.
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(price_intake.COLUMNS))
    ws.append([PRICE[k] for k in price_intake.COLUMNS])
    raw = io.BytesIO()
    wb.save(raw)
    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw.getvalue()), 'r') as zin, zipfile.ZipFile(tampered, 'w') as zout:
        for info in zin.infolist():
            content = zin.read(info.filename)
            if info.filename == 'xl/worksheets/sheet1.xml':
                content = content.replace(b'A1:J2', b'A1:XFD1048576')
            zout.writestr(info, content)
    parsed = price_intake.parse_prices('dim.xlsx', tampered.getvalue())
    assert not parsed['errors'] and len(parsed['rows']) == 1

    # > 1000 price rows rejected cleanly without loading unbounded memory.
    wb2 = openpyxl.Workbook()
    ws2 = wb2.active
    ws2.append(list(price_intake.COLUMNS))
    for i in range(1005):
        ws2.append([f'P-{i}', 'EA', 'FN', 'USD', '10', '2020-01-01', '2099-01-01', '7d', 'src', 'synthetic'])
    buf2 = io.BytesIO()
    wb2.save(buf2)
    with pytest.raises(ValueError, match='1000'):
        price_intake.parse_prices('many.xlsx', buf2.getvalue())


def test_p1_3_eml_depth_attachment_count_and_rfc822_submessage():
    # Nested message/rfc822 attachment where part.get_payload(decode=True) is None!
    inner = EmailMessage()
    inner['Subject'] = 'Inner RFQ-100'
    inner.set_content('RFQ No.\tPart Number\tQuantity\tUnit\tCondition\nRFQ-100\tSUB-1\t4\tEA\tFN\n')
    outer = EmailMessage()
    outer['Subject'] = 'Forward'
    outer.set_content('Please see attached email.')
    outer.add_attachment(inner, filename='inner.eml')
    raw = outer.as_bytes()
    parsed = parsing.parse_file('outer.eml', raw)
    assert any(r['fields']['part'] == 'SUB-1' for r in parsed['rows'])
    idx = EvidenceIndex()
    idx.add('outer.eml', raw)
    assert any(rec['fields'].get('part') == 'SUB-1' for rec in idx.records.values())

    # Depth > 3 rejected.
    cur = inner
    for i in range(5):
        wrap = EmailMessage()
        wrap['Subject'] = f'Wrap {i}'
        wrap.set_content('nested')
        wrap.add_attachment(cur, filename=f'nest{i}.eml')
        cur = wrap
    with pytest.raises(ValueError, match='深度'):
        parsing.parse_file('deep.eml', cur.as_bytes())

    # > 30 attachments rejected.
    many_att = EmailMessage()
    many_att['Subject'] = 'Many attachments'
    many_att.set_content('body')
    for i in range(31):
        many_att.add_attachment(b'hello', maintype='text', subtype='plain', filename=f'a{i}.txt')
    with pytest.raises(ValueError, match='附件数量'):
        parsing.parse_file('many.eml', many_att.as_bytes())


def test_p1_3_pdf_page_limit_and_single_extract_text_call(monkeypatch):
    class FakePage:
        def __init__(self, text):
            self.text = text
            self.calls = 0

        def extract_text(self):
            self.calls += 1
            return self.text

        def extract_tables(self):
            return []

    class FakePDF:
        def __init__(self, pages):
            self.pages = pages

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    # > 100 pages rejected.
    monkeypatch.setattr(parsing.pdfplumber, 'open', lambda _: FakePDF([FakePage('p')] * 101))
    with pytest.raises(ValueError, match='100'):
        parsing.parse_file('big.pdf', b'%PDF-fake')

    # extract_text called strictly ONCE per page in both parsing.py and evidence.py.
    pages1 = [FakePage('RFQ-55\n0010 PART-1 2 EA\nValve\n'), FakePage('0020 PART-2 3 EA\nSeal\n')]
    monkeypatch.setattr(parsing.pdfplumber, 'open', lambda _: FakePDF(pages1))
    parsing.parse_file('ok.pdf', b'%PDF-fake')
    assert [p.calls for p in pages1] == [1, 1]

    import evals.judges.evidence as ev_mod
    pages2 = [FakePage('RFQ-55\n0010 PART-1 2 EA\nValve\n'), FakePage('0020 PART-2 3 EA\nSeal\n')]
    monkeypatch.setattr(ev_mod.pdfplumber, 'open', lambda _: FakePDF(pages2))
    EvidenceIndex().add('ok.pdf', b'%PDF-fake')
    assert [p.calls for p in pages2] == [1, 1]


def test_p1_3_max_case_materials_and_async_upload_uses_to_thread(env, monkeypatch):
    client, _ = env
    called = []
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(func, /, *args, **kwargs):
        called.append(func.__name__)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(main.asyncio, 'to_thread', spy_to_thread)

    c = client.post('/api/import', files={'file': ('init.txt', b'RFQ: R1\nPart: P1\n')}).json()
    assert 'import_bytes' in called

    for i in range(main.MAX_CASE_MATERIALS - 1):
        r = client.post(
            f"/api/cases/{c['id']}/materials",
            data={'revision': c['revision']},
            files={'file': (f'm{i}.txt', f'note {i}\n'.encode())},
        )
        assert r.status_code == 200, r.text
        c = r.json()
    assert 'append_file' in called

    # 26th material must be rejected with 422.
    overflow = client.post(
        f"/api/cases/{c['id']}/materials",
        data={'revision': c['revision']},
        files={'file': ('overflow.txt', b'too many')},
    )
    assert overflow.status_code == 422

    # price_preview also runs via asyncio.to_thread.
    csv_buf = io.StringIO()
    w = csv.writer(csv_buf)
    w.writerow(price_intake.COLUMNS)
    w.writerow([PRICE[k] for k in price_intake.COLUMNS])
    r = client.post(
        f"/api/cases/{c['id']}/prices/import/preview",
        data={'revision': c['revision']},
        files={'file': ('p.csv', csv_buf.getvalue().encode())},
    )
    assert r.status_code == 200
    assert '_run_price_preview' in called


# ---------------- P1-4: SQLite WAL / Timeout / Close & MatrixOne Sync Outside Lock ----------------

def test_p1_4_sqlite_wal_busy_timeout_and_matrixone_sync_outside_transaction(env, monkeypatch):
    client, tmp_path = env
    with main.connection() as c:
        mode = c.execute('PRAGMA journal_mode').fetchone()[0].lower()
        timeout = c.execute('PRAGMA busy_timeout').fetchone()[0]
        assert mode == 'wal'
        assert timeout >= 10000

    # Verify matrixone.sync runs AFTER SQLite transaction commits and releases the write lock.
    lock_free = []

    def spy_sync(case, rows):
        # Opening an independent connection and starting BEGIN IMMEDIATE would fail with
        # OperationalError: database is locked if save() still held the write lock!
        other = sqlite3.connect(main.DB, timeout=0.1)
        try:
            other.execute('BEGIN IMMEDIATE')
            stored = other.execute('SELECT body FROM cases WHERE id=?', (case['id'],)).fetchone()
            assert stored is not None and json.loads(stored[0])['revision'] == case['revision']
            other.rollback()
            lock_free.append(case['revision'])
        finally:
            other.close()

    monkeypatch.setattr(matrixone, 'sync', spy_sync)
    c = client.post('/api/import', files={'file': ('t.csv', TWO_ROWS_CSV)}).json()
    r = client.post(f"/api/cases/{c['id']}/prices", json={'revision': c['revision'], 'values': {'prices': [PRICE]}})
    assert r.status_code == 200
    assert lock_free == [1, 2]


# ---------------- P1-5: Unauth Origin/CSRF, GET /export Protection, Signed rfq_visitor ----------------

def test_p1_5_unauth_mode_blocks_cross_origin_and_sec_fetch_site_writes(env):
    client, _ = env
    # No browser fetch headers -> allowed (CLI / TestClient).
    assert client.post('/api/import', files={'file': ('a.csv', TWO_ROWS_CSV)}).status_code == 200
    # Local workbench origin -> allowed.
    assert client.post(
        '/api/import',
        files={'file': ('b.csv', TWO_ROWS_CSV)},
        headers={'Origin': 'http://127.0.0.1:5311', 'Sec-Fetch-Site': 'same-site'},
    ).status_code == 200
    # Cross-origin / null / cross-site -> 403!
    assert client.post('/api/import', files={'file': ('c.csv', TWO_ROWS_CSV)}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/import', files={'file': ('c.csv', TWO_ROWS_CSV)}, headers={'Origin': 'null'}).status_code == 403
    assert client.post('/api/import', files={'file': ('c.csv', TWO_ROWS_CSV)}, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403


def test_p1_5_get_export_blocks_cross_site_state_write(env):
    client, _ = env
    c = _approved_two_row_case(client)
    url = f"/api/cases/{c['id']}"
    events_before = len(client.get(url).json()['events'])

    for headers in (
        {'Sec-Fetch-Site': 'cross-site'},
        {'Origin': 'https://evil.example'},
        {'Referer': 'https://evil.example/attack.html'},
    ):
        r = client.get(f"{url}/export?format=json&revision={c['revision']}", headers=headers)
        assert r.status_code == 403, headers
        assert len(client.get(url).json()['events']) == events_before


def test_p1_5_scoped_visitor_cookie_hmac_signed_and_ignores_x_forwarded_proto(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'DB', tmp_path / 'scoped.sqlite3')
    monkeypatch.setattr(main, 'SCOPED', True)
    monkeypatch.setenv('RFQ_AUTH_REQUIRED', '0')

    with TestClient(main.app, base_url='http://testserver') as client:
        forged = 'A' * 43
        r = client.get('/api/cases', headers={'Cookie': f'rfq_visitor={forged}', 'X-Forwarded-Proto': 'https'})
        assert r.status_code == 200
        set_cookie = r.headers.get('set-cookie', '')
        # Must reject forged cookie and issue a fresh signed cookie.
        assert 'rfq_visitor=' in set_cookie and forged not in set_cookie
        issued = client.cookies.get('rfq_visitor', '')
        assert '.' in issued and len(issued.rsplit('.', 1)[1]) == 64
        # Must NOT trust spoofed X-Forwarded-Proto over plain HTTP!
        assert 'secure' not in set_cookie.lower()

    with TestClient(main.app, base_url='https://testserver') as tls_client:
        r = tls_client.get('/api/cases')
        assert 'secure' in r.headers.get('set-cookie', '').lower()


# ---------------- P2-1: Split CASE_TOOLS & HOME_TOOLS + Defensive Dispatch ----------------

def test_p2_1_case_and_home_tools_split_and_no_attribute_error(env):
    client, _ = env
    case_names = {t['function']['name'] for t in agent.CASE_TOOLS}
    home_names = {t['function']['name'] for t in agent.HOME_TOOLS}
    assert 'pending_overview' not in case_names and 'list_mails' not in case_names
    assert 'pending_overview' in home_names and 'list_mails' in home_names
    assert 'extract_candidates' not in home_names

    # Verify CaseWorkspace sends CASE_TOOLS and handles home-only tool calls without AttributeError 500.
    seen_tools = []

    def handler(request):
        body = json.loads(request.content)
        seen_tools.append({t['function']['name'] for t in body['tools']})
        if len(seen_tools) == 1:
            return httpx.Response(200, json={
                'choices': [{'message': {'content': '', 'tool_calls': [
                    {'id': '1', 'type': 'function', 'function': {'name': 'pending_overview', 'arguments': '{}'}},
                    {'id': '2', 'type': 'function', 'function': {'name': 'list_mails', 'arguments': '{}'}},
                ]}}],
                'usage': {'total_tokens': 10},
            })
        return httpx.Response(200, json={'choices': [{'message': {'content': '工单内已处理。'}}], 'usage': {'total_tokens': 5}})

    session = agent.ModelSession(
        model_config.ModelSettings('https://x.invalid/v1/chat/completions', 'k', 'm'),
        transport=httpx.MockTransport(handler),
    )
    main.app.dependency_overrides[main.get_agent_session] = lambda: session
    c = client.post('/api/import', files={'file': ('m.txt', b'RFQ: R1\nPart: P1\n')}).json()
    r = client.post(f"/api/cases/{c['id']}/agent", json={'message': '看下待办', 'consent': True})
    assert r.status_code == 200, r.text
    assert seen_tools[0] == case_names


# ---------------- P2-2: CSV Formula Injection & Whitespace Normalization ----------------

def test_p2_2_csv_formula_injection_and_whitespace_normalization(env):
    client, _ = env
    # Direct unit test of CSV cell sanitizer.
    for dangerous in (' =CMD()', '\n=1+1', '\t+1', '\r-2', '  @SUM(A1)', '-10'):
        assert main._csv_cell(dangerous).startswith("'"), dangerous
    assert main._csv_cell('37.05') == '37.05'

    # End-to-end CSV export with whitespace-padded formula in price source & leading-space actor.
    c = client.post('/api/import', files={'file': ('two.csv', TWO_ROWS_CSV)}).json()
    padded_price = {
        **PRICE,
        'part': '  P-1  ',
        'unit': ' EA ',
        'condition': ' FN ',
        'currency': ' USD ',
        'amount': ' 10.00 ',
        'valid_from': ' 2020-01-01 ',
        'valid_until': ' 2099-12-31 ',
        'lead_time': ' 7 days ',
        'source': ' =HYPERLINK("http://evil")',
        'kind': ' synthetic ',
    }
    r = client.post(f"/api/cases/{c['id']}/prices", json={'revision': c['revision'], 'values': {'prices': [padded_price]}})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c['prices'][0]['part'] == 'P-1' and c['prices'][0]['amount'] == '10.00'

    r = client.post(f"/api/cases/{c['id']}/approve", json={'revision': c['revision'], 'values': {'actor': '  张工  '}})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c['rows'][0]['approval']['actor'] == '张工'

    csv_resp = client.get(f"/api/cases/{c['id']}/export?format=csv&revision={c['revision']}")
    assert csv_resp.status_code == 200
    parsed_rows = list(csv.DictReader(io.StringIO(csv_resp.content.decode('utf-8-sig'))))
    assert parsed_rows[0]['价格依据'].startswith("'")


# ---------------- P2-3: 5 Core Business Semantic Bugs ----------------

def test_p2_3_extract_dedup_keeps_due_requirements_priority_description_revisions(env):
    client, _ = env
    table = '询价号,件号,数量,单位,件状\nRFQ-77,PL-9,2,EA,NE\n'.encode()
    c = client.post('/api/import', files={'file': ('t.csv', table)}).json()
    c = client.post(
        f"/api/cases/{c['id']}/materials",
        data={'revision': c['revision']},
        files={'file': ('rev.txt', b'RFQ: RFQ-77\nPart: PL-9\nQuantity: 2\nUnit: EA\nCondition: NE\nDue date: 2028-05-01\n')},
    ).json()

    class DueRevisionAdapter:
        status = 'test'

        async def extract(self, m, b):
            rev_file = next(f for f in m['files'] if f['file'] == 'rev.txt')
            fields = {}
            for k, v in (('rfq', 'RFQ-77'), ('part', 'PL-9'), ('quantity', '2'), ('unit', 'EA'), ('condition', 'NE'), ('due', '2028-05-01')):
                u = next(u for u in rev_file['units'] if v in u['text'])
                a = u['text'].index(v)
                fields[k] = {'value': v, 'evidence': {x: u[x] for x in ('file', 'sha256', 'location')} | {'start': a, 'end': a + len(v), 'quote': v}}
            return semantic.AdapterReply({'candidates': [{'fields': fields}]}, 10, 1, 'real_call', 'test')

    ws = main.CaseWorkspace(c['id'], DueRevisionAdapter())
    result = asyncio.run(ws.extract())
    assert result['status'] == '已生成待审候选'
    after = client.get(f"/api/cases/{c['id']}").json()
    assert after['candidate_batches'][-1]['candidates'][0]['fields']['due'] == '2028-05-01'


def test_p2_3_xlsx_float_integer_and_multisection_number_format():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['RFQ No.', 'Part Number', 'Quantity', 'Unit', 'Condition'])
    ws.append([1234.0, 12.0, 5.0, 'EA', 'FN'])
    ws['B2'].number_format = '00000;-00000;0'
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()

    parsed = parsing.parse_file('num.xlsx', data)['rows'][0]['fields']
    assert parsed['rfq'] == '1234' and parsed['part'] == '00012' and parsed['quantity'] == '5'

    mat = main.material_files('num.xlsx', data)[0]['units'][1]['text']
    assert mat == '1234\t00012\t5\tEA\tFN'

    idx = EvidenceIndex()
    idx.add('num.xlsx', data)
    rec = next(iter(idx.records.values()))['fields']
    assert rec['rfq'] == '1234' and rec['part'] == '00012' and rec['quantity'] == '5'


def test_p2_3_local_mode_owns_and_inbox_revision_binding(env):
    client, tmp_path = env
    shutil.copytree(ROOT / 'data/synthetic', tmp_path / 'data/synthetic')
    own = client.post('/api/guided-demo').json()
    mails = client.post('/api/inbox/samples').json()
    mail = mails[3]
    reviewed = client.post(
        f"/api/inbox/{mail['id']}/review",
        json={'revision': mail['revision'], 'category': 'revision', 'reason': '本地模式绑定到已有工作单'},
    ).json()
    assert client.post(f"/api/inbox/{mail['id']}/open", json={'revision': reviewed['revision'], 'case_id': 'nonexistent'}).status_code == 404
    opened = client.post(f"/api/inbox/{mail['id']}/open", json={'revision': reviewed['revision'], 'case_id': own['id']})
    assert opened.status_code == 200, opened.text
    assert opened.json()['case_id'] == own['id']


def test_p2_3_bulk_edit_rows_preserves_authenticated_actor(auth_env):
    main.ACCOUNTS.create('alice', '用户甲', 'Synthetic account password 2026', must_change=False)
    with TestClient(main.app) as client:
        state = client.post('/api/auth/login', json={'username': 'alice', 'password': 'Synthetic account password 2026'}).json()
        client.headers.update({'X-CSRF-Token': state['csrf'], 'X-RFQ-Account': state['user']['id']})
        c = client.post('/api/import', files={'file': ('two.csv', TWO_ROWS_CSV)}).json()
        r = client.patch(
            f"/api/cases/{c['id']}/rows",
            json={'revision': c['revision'], 'values': {'row_ids': [c['rows'][0]['id']], 'due': '2030-01-01', 'reason': '批量改交期'}},
        )
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated['human_decisions'][-1]['actor'] == '用户甲 (alice)'


def test_p2_3_clarification_superseded_ignores_target_field(env):
    client, _ = env
    csv_missing_rfq = b'rfq,partnumber,quantity,unit,condition\n,P-1,2,EA,FN\n'
    c = client.post('/api/import', files={'file': ('m.csv', csv_missing_rfq)}).json()
    url = f"/api/cases/{c['id']}"
    c = client.post(f"{url}/clarifications/register", json={'revision': c['revision'], 'values': {}}).json()
    q = next(x for x in c['clarifications'] if x['field'] == 'rfq')

    # Editing rfq itself (the clarification's own field) does NOT change target identity (part).
    c = client.patch(
        f"{url}/rows/{c['rows'][0]['id']}",
        json={'revision': c['revision'], 'values': {'rfq': 'R-NEW', 'reason': 'fill rfq'}},
    ).json()
    r = client.post(
        f"{url}/clarifications/{q['id']}/resolve",
        json={'revision': c['revision'], 'values': {'method': 'superseded', 'base_row_revision': c['rows'][0]['revision'], 'actor': 't', 'reason': 'not actually reassigned'}},
    )
    assert r.status_code == 422

    # Changing part (the non-target identity field) genuinely reassigns target -> superseded allowed.
    c = client.patch(
        f"{url}/rows/{c['rows'][0]['id']}",
        json={'revision': c['revision'], 'values': {'part': 'P-OTHER', 'reason': 'reassign part'}},
    ).json()
    r = client.post(
        f"{url}/clarifications/{q['id']}/resolve",
        json={'revision': c['revision'], 'values': {'method': 'superseded', 'base_row_revision': c['rows'][0]['revision'], 'actor': 't', 'reason': 'reassigned to P-OTHER'}},
    )
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()['clarifications'] if x['id'] == q['id'])['state'] == 'superseded'


# ---------------- P2-4: Upload-Time Encoding/Parse Validation & Safe strptime ----------------

def test_p2_4_import_and_append_reject_invalid_files_and_safe_encoding_and_strptime(env, monkeypatch):
    client, tmp_path = env
    # Binary / NUL-byte .txt rejected at import.
    assert client.post('/api/import', files={'file': ('bin.txt', b'\x00\xff\xfehello')}).status_code == 422

    # Valid GB18030 .txt succeeds and reads cleanly in materials & evidence.
    gb_txt = '询价号: R-GB\n件号: P-GB\n数量: 3\n'.encode('gb18030')
    r = client.post('/api/import', files={'file': ('gb.txt', gb_txt)})
    assert r.status_code == 200, r.text
    c = r.json()
    assert client.get(f"/api/cases/{c['id']}/materials").status_code == 200

    # Corrupt PDF and invalid-encoding TXT rejected at append_material without leaving files on disk.
    for fname, blob in (('bad.pdf', b'%PDF-not-really-a-pdf'), ('bad.txt', b'\x00\xffbad')):
        res = client.post(f"/api/cases/{c['id']}/materials", data={'revision': c['revision']}, files={'file': (fname, blob)})
        assert res.status_code == 422
        assert not (tmp_path / 'var/uploads' / c['id'] / fname).exists()

    # EML with unknown charset header falls back safely across parsing, materials, and evidence.
    unknown_eml = b'Subject: Test\nContent-Type: text/plain; charset="x-unknown-999"\n\nRFQ No.\tPart Number\tQuantity\tUnit\tCondition\nR1\tP1\t2\tEA\tFN\n'
    assert parsing.parse_file('u.eml', unknown_eml)['rows'][0]['fields']['part'] == 'P1'
    assert main.material_files('u.eml', unknown_eml)[0]['units']
    idx = EvidenceIndex()
    idx.add('u.eml', unknown_eml)
    assert idx.records

    # Invalid PDF Respond by date must not crash strptime in parsing or evidence.
    class FakePage:
        def extract_text(self): return 'RFQ-1\nRespond by: 99-Foo-2026\n0010 P-1 2 EA\nDesc\n'
        def extract_tables(self): return []

    class FakePDF:
        pages = [FakePage()]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import evals.judges.evidence as ev_mod
    monkeypatch.setattr(parsing.pdfplumber, 'open', lambda _: FakePDF())
    monkeypatch.setattr(ev_mod.pdfplumber, 'open', lambda _: FakePDF())
    assert parsing.parse_file('bad_date.pdf', b'%PDF')['rows'][0]['fields']['due'] == ''
    idx2 = EvidenceIndex()
    idx2.add('bad_date.pdf', b'%PDF')
    assert next(iter(idx2.records.values()))['fields']['due'] == ''


# ---------------- P2-5: MatrixOne Snapshot Whitelist & Error Redaction ----------------

def test_p2_5_matrixone_snapshot_whitelist_and_error_redaction(env, monkeypatch):
    client, _ = env
    assert matrixone.validate_snapshot_name('rfq_abcdef012345_r2_20261124120000')
    for bad in ("rfq_a'} UNION SELECT 1--", 'rfq_1; DROP TABLE rfq_lines', '', 'not_a_snapshot'):
        with pytest.raises(ValueError):
            matrixone.validate_snapshot_name(bad)
        called = []
        dummy_cur = SimpleNamespace(execute=lambda *a, **kw: called.append(a), fetchall=lambda: [])
        with pytest.raises(ValueError):
            matrixone.rows_at(dummy_cur, 'c1', bad)
        assert called == []

    monkeypatch.setenv('RFQ_MO_HOST', '127.0.0.1')
    monkeypatch.setenv('RFQ_MO_PORT', '1')
    c = client.post('/api/import', files={'file': ('t.csv', TWO_ROWS_CSV)}).json()
    rep = client.get(f"/api/cases/{c['id']}/matrixone").json()
    assert rep['enabled'] and not rep['connected'] and rep['error']
    for leaked in ('127.0.0.1', 'OperationalError', 'pymysql', 'Traceback', '2003'):
        assert leaked not in rep['error']


# ---------------- P2-7: serve_web.py, HTML Quote CSP & model_config URL Validation ----------------

def test_p2_7_serve_web_security_headers_no_dirlist_and_overlong_range(tmp_path):
    (tmp_path / 'sample.txt').write_bytes(b'0123456789')
    (tmp_path / 'sub').mkdir()
    assert WebServer.daemon_threads is True
    assert Handler.timeout and Handler.timeout > 0

    server = WebServer(('127.0.0.1', 0), partial(Handler, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        # Security headers present on static responses.
        with urllib.request.urlopen(base + '/sample.txt') as r:
            assert r.status == 200
            csp = r.headers['Content-Security-Policy']
            assert 'http://127.0.0.1:8311' in csp and "'unsafe-inline'" in csp
            assert r.headers['X-Content-Type-Options'] == 'nosniff'
            assert r.headers['Referrer-Policy'] == 'no-referrer'

        # Directory browsing disabled (404).
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + '/sub/')
        assert exc.value.code == 404

        # Overlong Range digits (> 4300 digits) must NOT crash with 500!
        req = urllib.request.Request(base + '/sample.txt', headers={'Range': 'bytes=0-' + '9' * 5000})
        with urllib.request.urlopen(req) as r:
            assert r.status == 200 and r.read() == b'0123456789'
    finally:
        server.shutdown()
        server.server_close()


def test_p2_7_html_quote_headers_and_model_endpoint_validation(env, monkeypatch):
    client, _ = env
    c = _approved_two_row_case(client)
    r = client.get(f"/api/cases/{c['id']}/quote-preview?format=html&revision={c['revision']}")
    assert r.status_code == 200
    assert r.headers['content-security-policy'] == "default-src 'none'; style-src 'unsafe-inline'"
    assert r.headers['x-content-type-options'] == 'nosniff'

    for bad_url in (
        'http://remote.example/v1/chat/completions',
        'file:///etc/passwd',
        'https://user:pass@api.example/v1/chat/completions',
        'not-a-url',
    ):
        monkeypatch.setenv('RFQ_MODEL_URL', bad_url)
        with pytest.raises(ValueError):
            model_config.ModelSettings.from_env()

    for ok_url in (
        'https://api.example/v1/chat/completions',
        'http://127.0.0.1:8000/v1/chat/completions',
        'http://localhost:8000/v1/chat/completions',
    ):
        monkeypatch.setenv('RFQ_MODEL_URL', ok_url)
        assert model_config.ModelSettings.from_env().endpoint == ok_url


# ---------------- P2-8: HASH_SLOTS, Docs Disabled, Input Type & Limit Checks ----------------

def test_p2_8_hash_slots_docs_disabled_and_input_type_limits(auth_env, monkeypatch):
    # HASH_SLOTS raised to 6.
    acquired = 0
    try:
        while accounts.HASH_SLOTS.acquire(blocking=False):
            acquired += 1
        assert acquired == 6
    finally:
        for _ in range(acquired):
            accounts.HASH_SLOTS.release()

    # /docs, /redoc, /openapi.json disabled when RFQ_AUTH_REQUIRED=1 and RFQ_ENABLE_DOCS != 1.
    with TestClient(main.app) as client:
        for path in ('/docs', '/redoc', '/openapi.json'):
            assert client.get(path).status_code == 404, path
        monkeypatch.setenv('RFQ_ENABLE_DOCS', '1')
        assert client.get('/openapi.json').status_code == 200

    # Non-string reason/note/field values and oversized payloads return 422 (never 500).
    monkeypatch.setenv('RFQ_AUTH_REQUIRED', '0')
    with TestClient(main.app) as client:
        c = client.post('/api/import', files={'file': ('two.csv', TWO_ROWS_CSV)}).json()
        url = f"/api/cases/{c['id']}"
        row_id = c['rows'][0]['id']

        for bad_reason in (123, None, ['a'], {'x': 1}, 'x' * 4001):
            r = client.patch(f"{url}/rows/{row_id}", json={'revision': c['revision'], 'values': {'quantity': '5', 'reason': bad_reason}})
            assert r.status_code == 422, bad_reason

        r = client.patch(f"{url}/rows/{row_id}", json={'revision': c['revision'], 'values': {'quantity': 5, 'reason': 'ok'}})
        assert r.status_code == 422

        for bad_note in (123, None, ['n'], {'k': 'v'}, 'n' * 4001):
            r = client.post(f"{url}/review", json={'revision': c['revision'], 'values': {'note': bad_note}})
            assert r.status_code == 422, bad_note

        too_many_prices = [PRICE] * (domain.MAX_PRICES + 1)
        r = client.post(f"{url}/prices", json={'revision': c['revision'], 'values': {'prices': too_many_prices}})
        assert r.status_code == 422


# ---------------- Red-Team Convergence Regression Tests (P1-A, P2-A, P2-B) ----------------

def test_p1_a_case_approved_flag_tracks_invalidation_for_ui(env):
    client, _ = env
    c = _approved_two_row_case(client)
    url = f"/api/cases/{c['id']}"
    assert c['case_approved'] is True
    assert c['progress']['case_approved'] is True

    # Excluding one row invalidates case_approved immediately in view() & progress()
    r = client.patch(
        f"{url}/rows/{c['rows'][0]['id']}",
        json={'revision': c['revision'], 'values': {'excluded': True, 'reason': '取消第一行'}},
    )
    assert r.status_code == 200
    c2 = r.json()
    assert c2['case_approved'] is False
    assert c2['progress']['case_approved'] is False
    assert client.post(f"{url}/exports", json={'revision': c2['revision'], 'values': {'format': 'csv'}}).status_code == 409

    # Re-approving restores case_approved=True and unlocks export
    c3 = client.post(f"{url}/approve", json={'revision': c2['revision'], 'values': {'actor': '复核人'}}).json()
    assert c3['case_approved'] is True
    assert c3['progress']['case_approved'] is True
    assert client.post(f"{url}/exports", json={'revision': c3['revision'], 'values': {'format': 'csv'}}).status_code == 200


def test_p2_a_pending_candidates_cannot_be_bypassed_by_unrelated_price_bump(env):
    client, _ = env
    c = _approved_two_row_case(client)
    url = f"/api/cases/{c['id']}"
    # Append a revision with a new candidate & propose
    appended = client.post(
        f"{url}/materials",
        data={'revision': c['revision']},
        files={'file': ('rev.txt', b'RFQ: R-01\nPart: P-1\nQuantity: 9\nUnit: EA\nCondition: FN\n')},
    ).json()
    proposed = client.post(
        f"{url}/candidates/propose",
        json={'revision': appended['revision'], 'values': {'mode': 'offline'}},
    ).json()['case']
    assert proposed['case_approved'] is False
    assert proposed['progress']['pending_candidates'] >= 1

    # Adding an unrelated price bumps revision, but pending candidates MUST still block approve & export!
    unrelated = {**PRICE, 'part': 'UNRELATED-999'}
    bumped = client.post(
        f"{url}/prices",
        json={'revision': proposed['revision'], 'values': {'prices': [PRICE, unrelated]}},
    ).json()
    assert bumped['case_approved'] is False
    assert bumped['progress']['pending_candidates'] >= 1
    assert client.post(f"{url}/approve", json={'revision': bumped['revision'], 'values': {'actor': '绕过测试'}}).status_code == 409
    assert client.post(f"{url}/exports", json={'revision': bumped['revision'], 'values': {'format': 'csv'}}).status_code == 409


def test_p2_b_corrupt_deflate_and_utf16_doctype_xlsx_return_422(env):
    client, _ = env
    c = client.post('/api/import', files={'file': ('two.csv', TWO_ROWS_CSV)}).json()
    url = f"/api/cases/{c['id']}"

    # 1. Corrupt deflate payload in zip entry -> 422 (never 500 zlib.error)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('xl/workbook.xml', b'<workbook>' + b'A' * 200 + b'</workbook>')
    raw = bytearray(buf.getvalue())
    # Corrupt compressed bytes after local file header
    hdr_end = raw.find(b'xl/workbook.xml') + len(b'xl/workbook.xml')
    for i in range(hdr_end + 2, min(hdr_end + 18, len(raw))):
        raw[i] ^= 0xFF
    r = client.post(
        f"{url}/prices/import/preview",
        data={'revision': c['revision']},
        files={'file': ('corrupt.xlsx', bytes(raw))},
    )
    assert r.status_code == 422

    # 2. UTF-16 encoded <!DOCTYPE> inside xlsx XML -> rejected with ValueError
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('xl/workbook.xml', '<?xml version="1.0"?><!DOCTYPE foo><workbook/>'.encode('utf-16-le'))
    with pytest.raises(ValueError, match='XML'):
        parsing.validate_xlsx(buf2.getvalue())
