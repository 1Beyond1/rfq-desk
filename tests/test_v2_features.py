"""Tests for v2 backend features: SQLite snapshots/diff, XLSX & email export, offline home assistant, archive/delete & overview counts."""
import asyncio
import copy
import io
import json
import shutil
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from apps.api import agent, domain, main, quote_export, references

ROOT = Path(__file__).resolve().parents[1]

TWO_ROWS_CSV = (
    'rfq,partnumber,description,quantity,unit,condition,requirements\n'
    '000301,00012,液压滤芯,2,EA,FN,=SUM(A1:A2)\n'
    '000302,00099,密封组件,3,EA,OH,+CMD()\n'
).encode('utf-8')

USD_PRICE = {
    'part': '00012', 'unit': 'EA', 'condition': 'FN', 'currency': 'USD', 'amount': '12.50',
    'valid_from': '2020-01-01', 'valid_until': '2099-12-31', 'lead_time': '7 天',
    'source': ' =HYPERLINK("http://evil.example")', 'kind': 'synthetic',
}
EUR_PRICE = {
    'part': '00099', 'unit': 'EA', 'condition': 'OH', 'currency': 'EUR', 'amount': '20.00',
    'valid_from': '2020-01-01', 'valid_until': '2099-12-31', 'lead_time': '14 天',
    'source': 'SYN-EUR-CARD', 'kind': 'synthetic',
}
AUTH_USD_PRICE = {
    'part': '00012', 'unit': 'EA', 'condition': 'FN', 'currency': 'USD', 'amount': '12.50',
    'valid_from': '2020-01-01', 'valid_until': '2099-12-31', 'lead_time': '7 天',
    'source': 'AUTH-CARD-01', 'kind': 'authorized',
}
AUTH_EUR_PRICE = {
    'part': '00099', 'unit': 'EA', 'condition': 'OH', 'currency': 'EUR', 'amount': '20.00',
    'valid_from': '2020-01-01', 'valid_until': '2099-12-31', 'lead_time': '14 天',
    'source': 'AUTH-CARD-02', 'kind': 'authorized',
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'DB', tmp_path / 'v2.sqlite3')
    monkeypatch.setattr(main, 'SCOPED', False)
    monkeypatch.setenv('RFQ_AUTH_REQUIRED', '0')
    monkeypatch.setenv('RFQ_ENABLE_MODEL_REQUESTS', '0')
    monkeypatch.delenv('RFQ_MO_HOST', raising=False)
    shutil.copytree(ROOT / 'data/synthetic', tmp_path / 'data/synthetic')
    yield TestClient(main.app), tmp_path
    main.app.dependency_overrides.clear()


@pytest.fixture
def auth_env(tmp_path, monkeypatch):
    monkeypatch.setenv('RFQ_AUTH_REQUIRED', '1')
    monkeypatch.setenv('RFQ_COOKIE_SECURE', '0')
    monkeypatch.setenv('RFQ_PUBLIC_ORIGIN', 'http://testserver')
    monkeypatch.setenv('RFQ_ENABLE_MODEL_REQUESTS', '0')
    monkeypatch.delenv('RFQ_MO_HOST', raising=False)
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'DB', tmp_path / 'v2_auth.sqlite3')
    monkeypatch.setattr(main, 'SCOPED', False)
    shutil.copytree(ROOT / 'data/synthetic', tmp_path / 'data/synthetic')
    yield tmp_path
    main.app.dependency_overrides.clear()


def _enter_demo(client):
    r = client.post('/api/auth/demo', json={})
    assert r.status_code == 200, r.text
    s = r.json()
    client.headers.update({'X-RFQ-Account': s['user']['id'], 'X-CSRF-Token': s['csrf']})
    return s


def _approved_multicurrency_case(client, authorized=False):
    c = client.post('/api/import', files={'file': ('mc.csv', TWO_ROWS_CSV)}).json()
    url = f"/api/cases/{c['id']}"
    # Clear requirements review issue by resolving both rows with notes while preserving requirements text
    for r in c['rows']:
        resp = client.patch(
            f"{url}/rows/{r['id']}",
            json={'revision': c['revision'], 'values': {'reason': '已核验特殊要求条款'}},
        )
        assert resp.status_code == 200, resp.text
        c = resp.json()
    prices = [AUTH_USD_PRICE, AUTH_EUR_PRICE] if authorized else [USD_PRICE, EUR_PRICE]
    resp = client.post(f"{url}/prices", json={'revision': c['revision'], 'values': {'prices': prices}})
    assert resp.status_code == 200, resp.text
    c = resp.json()
    resp = client.post(f"{url}/approve", json={'revision': c['revision'], 'values': {'actor': '李工'}})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------- 1. SQLite Snapshots & Field-Level Diff ----------------

def test_sqlite_snapshots_diff_and_offline_workspace_history(env):
    client, _ = env
    simple_csv = b'rfq,partnumber,quantity,unit,condition\nR-100,P-100,2,EA,FN\nR-101,P-100,3,EA,FN\n'
    price1 = {
        'part': 'P-100', 'unit': 'EA', 'condition': 'FN', 'currency': 'USD', 'amount': '10.00',
        'valid_from': '2020-01-01', 'valid_until': '2099-12-31', 'lead_time': '5 天',
        'source': 'SYN-CARD-1', 'kind': 'synthetic',
    }
    c = client.post('/api/import', files={'file': ('s.csv', simple_csv)}).json()
    url = f"/api/cases/{c['id']}"

    # Before approval, default_from falls back to earliest snapshot (rev 1 import).
    d0 = client.get(f"{url}/diff").json()
    assert d0['default_from'] == 1 and d0['current_revision'] == 1
    assert d0['snapshots'][0]['kind'] == 'import'
    assert d0['diff']['rows'] == [] and d0['diff']['summary']['unchanged'] == 2

    # Price + approve
    c = client.post(f"{url}/prices", json={'revision': c['revision'], 'values': {'prices': [price1]}}).json()
    c = client.post(f"{url}/approve", json={'revision': c['revision'], 'values': {'actor': '张工'}}).json()
    approved_rev = c['revision']

    # Verify snapshots omit bulky events/fragments
    with main.connection() as db:
        snap_body = json.loads(
            db.execute(
                'SELECT body FROM case_snapshots WHERE case_id=? AND revision=?',
                (c['id'], approved_rev),
            ).fetchone()[0]
        )
    assert 'events' not in snap_body and 'fragments' not in snap_body

    # Right after approval: default_from is approved_rev, 0 row changes
    d_ok = client.get(f"{url}/diff").json()
    assert d_ok['default_from'] == approved_rev
    assert d_ok['diff']['from_kind'] == 'approve'
    assert d_ok['diff']['to_kind'] == 'current'
    assert d_ok['diff']['from_actor'] == '张工'
    assert d_ok['diff']['rows'] == []
    assert d_ok['diff']['summary']['unchanged'] == 2

    # Mutate quantity on row 0, exclude row 1, update price, append material
    row0, row1 = c['rows'][0]['id'], c['rows'][1]['id']
    c = client.patch(
        f"{url}/rows/{row0}",
        json={'revision': c['revision'], 'values': {'quantity': '5', 'reason': '客户增订'}},
    ).json()
    c = client.patch(
        f"{url}/rows/{row1}",
        json={'revision': c['revision'], 'values': {'excluded': True, 'reason': '取消第二行'}},
    ).json()
    excl_rev = c['revision']
    price2 = {**price1, 'amount': '14.50', 'source': 'SYN-CARD-2'}
    c = client.post(f"{url}/prices", json={'revision': c['revision'], 'values': {'prices': [price2]}}).json()
    c = client.post(
        f"{url}/materials",
        data={'revision': c['revision']},
        files={'file': ('addendum.txt', b'RFQ: R-100\nPart: P-100\nQuantity: 5\n')},
    ).json()

    # Diff defaults from last approval -> current
    res = client.get(f"{url}/diff").json()
    assert res['default_from'] == approved_rev
    diff = res['diff']
    assert diff['from_revision'] == approved_rev and diff['to_revision'] == c['revision']
    assert diff['price_version_before'] == 1 and diff['price_version_after'] == 2
    assert diff['materials_changed'] is True
    assert diff['summary']['changed'] == 1
    assert diff['summary']['excluded'] == 1
    assert diff['summary']['price_changed'] == 2
    assert diff['summary']['unchanged'] == 0

    by_id = {r['row_id']: r for r in diff['rows']}
    assert by_id[row0]['status'] == 'changed'
    r0_changes = {ch['field']: (ch['before'], ch['after']) for ch in by_id[row0]['changes']}
    assert r0_changes['quantity'] == ('2', '5')
    assert r0_changes['price_amount'] == ('10.00', '14.50')
    assert r0_changes['price_source'] == ('SYN-CARD-1', 'SYN-CARD-2')
    assert r0_changes['approved'] == (True, False)
    assert by_id[row1]['status'] == 'excluded'
    r1_changes = {ch['field']: (ch['before'], ch['after']) for ch in by_id[row1]['changes']}
    assert r1_changes['excluded'] == (False, True)

    # Restore row 1 and diff excl_rev -> restored rev
    c = client.patch(
        f"{url}/rows/{row1}",
        json={'revision': c['revision'], 'values': {'excluded': False, 'reason': '恢复第二行'}},
    ).json()
    restored = client.get(f"{url}/diff", params={'from_rev': excl_rev, 'to_rev': c['revision']}).json()['diff']
    assert restored['summary']['restored'] == 1
    assert any(r['row_id'] == row1 and r['status'] == 'restored' for r in restored['rows'])

    # Missing snapshot revision -> 404
    assert client.get(f"{url}/diff", params={'from_rev': 999}).status_code == 404
    assert client.get(f"{url}/diff", params={'to_rev': 999}).status_code == 404

    # CaseWorkspace.history() offline fallback returns real local field diff (no MatrixOne needed)
    hist = main.CaseWorkspace(c['id'], None).history()
    assert hist['source'] == 'local_sqlite'
    assert not hist['connected']
    assert hist['since_last_approval']['from_revision'] == approved_rev
    assert any(
        r['row_id'] == row0 and any(ch['field'] == 'quantity' and ch['after'] == '5' for ch in r['changes'])
        for r in hist['since_last_approval']['changes']
    )
    assert hist['audit_total'] == len(c['events'])

    # Legacy case with no case_snapshots rows returns empty metadata and diff=None cleanly
    with main.connection() as db:
        db.execute('DELETE FROM case_snapshots WHERE case_id=?', (c['id'],))
    legacy = client.get(f"{url}/diff").json()
    assert legacy == {'snapshots': [], 'default_from': None, 'current_revision': c['revision'], 'diff': None}
    assert client.get(f"{url}/diff", params={'from_rev': 1}).status_code == 404


def test_diff_snapshots_added_and_removed_rows():
    before = {
        'id': 'c1', 'revision': 1, 'price_version': 0, 'materials_snapshot': 's1', 'warnings': [], 'prices': [],
        'rows': [{
            'id': 'r1', 'rfq': 'Q1', 'part': 'P1', 'description': '', 'quantity': '2', 'unit': 'EA',
            'condition': 'FN', 'due': '', 'requirements': '', 'priority': '', 'excluded': False,
            'resolution': '', 'revision': 1, 'approval': None, 'raw_fields': {}, 'sources': [],
        }],
    }
    after = copy.deepcopy(before)
    after['revision'] = 2
    after['rows'] = [{
        'id': 'r2', 'rfq': 'Q2', 'part': 'P2', 'description': '', 'quantity': '4', 'unit': 'EA',
        'condition': 'OH', 'due': '', 'requirements': '', 'priority': '', 'excluded': False,
        'resolution': '', 'revision': 1, 'approval': None, 'raw_fields': {}, 'sources': [],
    }]
    diff = domain.diff_snapshots(before, after, from_meta={'kind': 'import'}, to_meta={'kind': 'edit'})
    assert diff['summary']['added'] == 1 and diff['summary']['removed'] == 1
    statuses = {r['row_id']: r['status'] for r in diff['rows']}
    assert statuses == {'r1': 'removed', 'r2': 'added'}


# ---------------- 2. Formatted XLSX Export & Bilingual Quote Email ----------------

def test_xlsx_export_audit_dual_sheets_leading_zeros_formula_guard_and_multicurrency(env):
    client, _ = env
    # Unapproved case must be blocked with 409
    raw = client.post('/api/import', files={'file': ('mc.csv', TWO_ROWS_CSV)}).json()
    assert client.post(
        f"/api/cases/{raw['id']}/exports",
        json={'revision': raw['revision'], 'values': {'format': 'xlsx'}},
    ).status_code == 409

    # Approved synthetic multi-currency case
    c = _approved_multicurrency_case(client, authorized=False)
    url = f"/api/cases/{c['id']}"
    events_before = len(c['events'])

    assert client.post(f"{url}/exports", json={'revision': c['revision'], 'values': {'format': 'pdf'}}).status_code == 422

    resp = client.post(f"{url}/exports", json={'revision': c['revision'], 'values': {'format': 'xlsx'}})
    assert resp.status_code == 200, resp.text
    assert resp.headers['content-type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert f'quote-{c["id"]}-r{c["revision"]}.xlsx' in resp.headers['content-disposition']
    assert resp.headers['x-content-type-options'] == 'nosniff'
    assert resp.headers['x-rfq-business-revision'] == str(c['revision'])

    # Audit event recorded without invalidating approval or bumping business revision
    after = client.get(url).json()
    assert after['revision'] == c['revision'] and after['case_approved'] is True
    assert len(after['events']) == events_before + 1
    assert after['events'][-1]['action'] == 'export' and after['events'][-1]['detail']['format'] == 'xlsx'

    # Read back workbook with openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ['正式报价单', '原件与价格溯源']

    ws1 = wb['正式报价单']
    assert '合成演示报价单' in str(ws1['A1'].value)
    # Row 6 & Row 7 are the 2 line items
    assert ws1.cell(row=6, column=1).value == '000301'
    assert ws1.cell(row=6, column=1).number_format == '@'
    assert ws1.cell(row=6, column=2).value == '00012'
    assert ws1.cell(row=6, column=2).number_format == '@'
    assert ws1.cell(row=7, column=1).value == '000302'
    assert ws1.cell(row=7, column=2).value == '00099'
    assert ws1.cell(row=6, column=8).value == '12.50'
    assert ws1.cell(row=6, column=9).value == '25.00'
    assert ws1.cell(row=7, column=9).value == '60.00'
    # Formula injection escaped in requirements column (col 11)
    assert str(ws1.cell(row=6, column=11).value).startswith("'")
    assert str(ws1.cell(row=7, column=11).value).startswith("'")

    # Separate currency totals (EUR 60.00 and USD 25.00, never combined)
    sheet1_texts = [str(cell.value) for row in ws1.iter_rows() for cell in row if cell.value is not None]
    assert 'EUR' in sheet1_texts and 'USD' in sheet1_texts
    assert '合计 (EUR)' in sheet1_texts and '合计 (USD)' in sheet1_texts
    assert '60.00' in sheet1_texts and '25.00' in sheet1_texts
    assert any('不折汇' in t and '待' in t for t in sheet1_texts)

    # Sheet 2 traceability + formula injection guard on price source
    ws2 = wb['原件与价格溯源']
    assert ws2.cell(row=2, column=1).value == '000301' and ws2.cell(row=2, column=1).number_format == '@'
    assert ws2.cell(row=2, column=2).value == '00012' and ws2.cell(row=2, column=2).number_format == '@'
    assert 'mc.csv' in str(ws2.cell(row=2, column=3).value)
    assert str(ws2.cell(row=2, column=4).value).startswith("'")  # escaped =HYPERLINK(...)
    assert '2020-01-01 ~ 2099-12-31' == ws2.cell(row=2, column=5).value

    # Formal (authorized) workbook title must say 正式报价响应, not 合成演示报价单
    c_auth = _approved_multicurrency_case(client, authorized=True)
    resp_auth = client.post(
        f"/api/cases/{c_auth['id']}/exports",
        json={'revision': c_auth['revision'], 'values': {'format': 'xlsx'}},
    )
    assert resp_auth.status_code == 200
    wb_auth = openpyxl.load_workbook(io.BytesIO(resp_auth.content))
    assert '正式报价响应' in str(wb_auth['正式报价单']['A1'].value)
    assert '合成演示报价单' not in str(wb_auth['正式报价单']['A1'].value)

    # Editing after approval blocks xlsx export with 409
    edited = client.patch(
        f"{url}/rows/{c['rows'][0]['id']}",
        json={'revision': c['revision'], 'values': {'quantity': '9', 'reason': '改数量使批准失效'}},
    ).json()
    assert client.post(
        f"{url}/exports",
        json={'revision': edited['revision'], 'values': {'format': 'xlsx'}},
    ).status_code == 409


def test_quote_email_bilingual_preview_no_audit_and_guards(env):
    client, _ = env
    raw = client.post('/api/import', files={'file': ('mc.csv', TWO_ROWS_CSV)}).json()
    assert client.get(f"/api/cases/{raw['id']}/quote-email", params={'revision': raw['revision'], 'lang': 'zh'}).status_code == 409

    c = _approved_multicurrency_case(client, authorized=False)
    url = f"/api/cases/{c['id']}"
    events_before = len(c['events'])

    # Invalid lang / missing revision -> 422; stale revision -> 409
    assert client.get(f"{url}/quote-email", params={'revision': c['revision'], 'lang': 'fr'}).status_code == 422
    assert client.get(f"{url}/quote-email", params={'lang': 'zh'}).status_code == 422
    assert client.get(f"{url}/quote-email", params={'revision': c['revision'] - 1, 'lang': 'zh'}).status_code == 409

    # Chinese preview
    zh = client.get(f"{url}/quote-email", params={'revision': c['revision'], 'lang': 'zh'})
    assert zh.status_code == 200, zh.text
    zh_data = zh.json()
    assert zh_data['lang'] == 'zh' and zh_data['revision'] == c['revision'] and zh_data['synthetic'] is True
    assert '合成演示' in zh_data['subject'] and '合成演示' in zh_data['body']
    assert 'USD 25.00' in zh_data['body'] and 'EUR 60.00' in zh_data['body']
    assert '不自动折汇' in zh_data['body'] and '暂未提供' in zh_data['body']

    # English preview
    en = client.get(f"{url}/quote-email", params={'revision': c['revision'], 'lang': 'en'})
    assert en.status_code == 200, en.text
    en_data = en.json()
    assert en_data['lang'] == 'en' and en_data['revision'] == c['revision'] and en_data['synthetic'] is True
    assert '[SYNTHETIC DEMO]' in en_data['subject']
    assert 'USD 25.00' in en_data['body'] and 'EUR 60.00' in en_data['body']
    assert 'not provided' in en_data['body']

    # Pure preview must NOT write any audit events
    assert len(client.get(url).json()['events']) == events_before

    # Authorized (non-synthetic) email must NOT include synthetic tag
    c_auth = _approved_multicurrency_case(client, authorized=True)
    auth_en = client.get(
        f"/api/cases/{c_auth['id']}/quote-email",
        params={'revision': c_auth['revision'], 'lang': 'en'},
    ).json()
    assert auth_en['synthetic'] is False and 'SYNTHETIC' not in auth_en['subject']


# ---------------- 3. Offline Home Assistant & Reference Search Fixes (U18) ----------------

def test_references_case_insensitive_and_chinese_bigram_search(env):
    _, tmp_path = env
    store = references.References(tmp_path)

    # Case-insensitive condition/unit/currency/part normalization
    stock = store.stock(' syn-002 ', 'fn', 'ea', '6')
    assert stock['eligible_groups'] == [{'condition': 'FN', 'unit': 'EA', 'available': 4, 'shortage': '2'}]
    assert len(stock['records']) == 1

    quotes = store.history('syn-001', condition='fn', unit='ea', currency='usd', quantity='10')
    q1 = next(r for r in quotes['records'] if r['id'] == 'QUOTE-001')
    assert not any('件状不同' in d or '单位不同' in d or '币种不同' in d for d in q1['differences'])

    alt = store.alternatives('syn-002')
    assert alt['records'][0]['alternative'] == 'SYN-012'

    # Overlapping Chinese bigram tokenization
    assert store._tokenize('小油泵') == ['小油', '油泵']

    # Natural Chinese query hits hydraulic seal ring SYN-051 at top
    found = store.search('stock', '液压系统那个密封圈还有多少库存？', semantic=False)
    assert found['records']
    assert found['records'][0]['part'] == 'SYN-051'
    assert '密封圈' in found['records'][0]['description'] and '液压系统' in found['records'][0]['description']


def test_offline_home_assistant_routes_and_preserves_demo_quota(auth_env, monkeypatch):
    monkeypatch.setenv('RFQ_DEMO_AI_CALLS', '1')
    with TestClient(main.app) as c:
        s = _enter_demo(c)
        c.post('/api/inbox/samples')
        c.post('/api/guided-demo')

        # Validation checks
        assert c.post('/api/agent/home', json={'message': '   '}).status_code == 422
        assert c.post('/api/agent/home', json={'message': 'x' * 601}).status_code == 422

        # 1. Todo / inbox query
        r1 = c.post('/api/agent/home', json={'message': '现在有什么待办要审？看看收件箱邮件和工作单'})
        assert r1.status_code == 200, r1.text
        t1 = r1.json()['turn']
        assert t1['local'] is True and t1['mode'] == 'offline-local' and t1['models'] == []
        assert t1['reply'].startswith('【本地确定性查询 · 未调用模型】')
        assert t1['tools'] == ['pending_overview', 'list_mails']
        assert len(t1['steps']) == 2 and len(t1['mails']) > 0

        # 2. Descriptive Chinese query with stock intent -> search_parts + auto lookup_stock
        r2 = c.post('/api/agent/home', json={'message': '液压系统那个密封圈还有多少库存？'})
        assert r2.status_code == 200, r2.text
        t2 = r2.json()['turn']
        assert t2['local'] is True and t2['mode'] == 'offline-local'
        assert t2['tools'] == ['search_parts', 'lookup_stock']
        assert len(t2['references']) == 2 and len(t2['steps']) == 2
        assert t2['references'][0]['result']['records'][0]['part'] == 'SYN-051'
        assert t2['references'][1]['query']['part'] == 'SYN-051'
        assert 'SYN-051' in t2['reply'] and '8' in t2['reply']

        # 3. Explicit part number (even adjacent to Chinese characters without spaces)
        r3 = c.post('/api/agent/home', json={'message': '查一下SYN-002库存、历史报价和替代件'})
        assert r3.status_code == 200, r3.text
        t3 = r3.json()['turn']
        assert t3['tools'] == ['lookup_stock', 'historical_quotes', 'find_alternatives']
        assert len(t3['references']) == 3
        assert 'SYN-002' in t3['reply'] and 'SYN-012' in t3['reply']

        # 4. Business rules query
        r4 = c.post('/api/agent/home', json={'message': '同件号不同询价合并规则和冲突怎么处理？'})
        assert r4.status_code == 200, r4.text
        t4 = r4.json()['turn']
        assert t4['tools'] == ['search_rules']
        assert len(t4['references']) == 1 and len(t4['references'][0]['result']['records']) >= 1

        # All 4 turns persisted in agent_home_turns
        turns = c.get('/api/agent/home').json()['turns']
        assert len(turns) == 4

        # Offline deterministic queries must NOT consume demo AI call quota
        with main.connection() as db:
            main.ACCOUNTS.schema(db)
            used = db.execute('SELECT count FROM auth_demo_calls WHERE user_id=?', (s['user']['id'],)).fetchone()
        assert used is None or used[0] == 0


# ---------------- 4. Soft Archive, Safe Delete & Accurate overview() Counts (U11) ----------------

def test_archive_unarchive_preserves_approval_and_excludes_from_overview(env):
    client, _ = env
    c = _approved_multicurrency_case(client, authorized=True)
    url = f"/api/cases/{c['id']}"
    assert c['archived'] is False
    assert client.get('/api/cases').json()[0]['archived'] is False

    # Invalid type / stale revision rejected
    assert client.patch(f"{url}/archive", json={'revision': c['revision'], 'values': {'archived': 'yes'}}).status_code == 422
    assert client.patch(f"{url}/archive", json={'revision': c['revision'] - 1, 'values': {'archived': True}}).status_code == 409

    # Archive approved case -> approval preserved!
    archived = client.patch(f"{url}/archive", json={'revision': c['revision'], 'values': {'archived': True}})
    assert archived.status_code == 200, archived.text
    c2 = archived.json()
    assert c2['archived'] is True and c2['case_approved'] is True
    assert all(r['approved'] for r in c2['rows'])
    assert c2['events'][-1]['action'] == 'archive'
    assert client.get('/api/cases').json()[0]['archived'] is True

    # Formal export still works at archived revision (approval was not broken)
    assert client.post(f"{url}/exports", json={'revision': c2['revision'], 'values': {'format': 'json'}}).status_code == 200

    # Overview excludes archived case from active counts and todos
    ov = client.get('/api/agent/overview').json()
    assert ov['case_total'] == 0 and ov['archived_total'] == 1 and ov['cases'] == []

    # Idempotent archive does not bump revision
    same = client.patch(f"{url}/archive", json={'revision': c2['revision'], 'values': {'archived': True}}).json()
    assert same['revision'] == c2['revision']

    # Unarchive -> restores to active overview while keeping approval intact
    c3 = client.patch(f"{url}/archive", json={'revision': c2['revision'], 'values': {'archived': False}}).json()
    assert c3['archived'] is False and c3['case_approved'] is True
    assert c3['events'][-1]['action'] == 'unarchive'
    ov2 = client.get('/api/agent/overview').json()
    assert ov2['case_total'] == 1 and ov2['archived_total'] == 0


def test_delete_case_security_cleanup_inbox_unlink_and_demo_quota_release(auth_env):
    with TestClient(main.app) as a, TestClient(main.app) as b:
        sa = _enter_demo(a)
        _enter_demo(b)

        # Open a case from an inbox sample mail
        mails = a.post('/api/inbox/samples').json()
        mail = mails[0]
        reviewed = a.post(
            f"/api/inbox/{mail['id']}/review",
            json={'revision': mail['revision'], 'category': 'new_rfq', 'reason': '人工确认新询价测试删除解绑'},
        ).json()
        opened = a.post(f"/api/inbox/{mail['id']}/open", json={'revision': reviewed['revision']}).json()
        cid = opened['case_id']

        # Seed a dummy price-imports artifact and an agent_turns row for cid
        pi_dir = auth_env / 'var/price-imports' / cid
        pi_dir.mkdir(parents=True, exist_ok=True)
        (pi_dir / 'tmp.csv').write_text('dummy', encoding='utf-8')
        with main.connection() as db:
            db.execute('INSERT INTO agent_turns (case_id, body) VALUES (?, ?)', (cid, '{}'))
        assert (auth_env / 'var/uploads' / cid).is_dir()

        # Cross-account delete -> 404!
        assert b.delete(f"/api/cases/{cid}").status_code == 404

        # Cross-origin & missing CSRF -> 403!
        assert a.delete(f"/api/cases/{cid}", headers={'Origin': 'https://evil.example'}).status_code == 403
        saved_csrf = a.headers.pop('X-CSRF-Token')
        assert a.delete(f"/api/cases/{cid}").status_code == 403
        a.headers['X-CSRF-Token'] = saved_csrf

        # Fill demo quota to 6 work orders (1 already opened + 5 more = 6; 7th blocked with 429)
        for _ in range(5):
            assert a.post('/api/guided-demo').status_code == 200
        assert a.post('/api/guided-demo').status_code == 429

        # Owner deletes cid -> 200
        deleted = a.delete(f"/api/cases/{cid}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {'deleted': True, 'id': cid}

        # Deleting again -> 404
        assert a.delete(f"/api/cases/{cid}").status_code == 404

        # DB rows & disk folders cleaned up
        assert not (auth_env / 'var/uploads' / cid).exists()
        assert not (auth_env / 'var/price-imports' / cid).exists()
        with main.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM cases WHERE id=?', (cid,)).fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM case_owners WHERE case_id=?', (cid,)).fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM agent_turns WHERE case_id=?', (cid,)).fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM case_snapshots WHERE case_id=?', (cid,)).fetchone()[0] == 0

        # Inbox mail is unlinked (case_id is None) and demo quota is released so it can be re-opened!
        latest_mail = next(m for m in a.get('/api/inbox').json() if m['id'] == mail['id'])
        assert latest_mail['case_id'] is None
        reopened = a.post(f"/api/inbox/{mail['id']}/open", json={'revision': latest_mail['revision']})
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()['case_id'] != cid and reopened.json()['already_opened'] is False


def test_overview_accurate_case_total_beyond_12_cases(env):
    client, _ = env
    simple_csv = b'rfq,partnumber,quantity,unit,condition\nR-1,P-1,1,EA,FN\n'
    created = []
    for i in range(17):
        r = client.post('/api/import', files={'file': (f'case_{i}.csv', simple_csv)})
        assert r.status_code == 200
        created.append(r.json())

    # Archive 2 of the 17 cases -> 15 active, 2 archived
    for c in created[:2]:
        r = client.patch(
            f"/api/cases/{c['id']}/archive",
            json={'revision': c['revision'], 'values': {'archived': True}},
        )
        assert r.status_code == 200

    ov = client.get('/api/agent/overview').json()
    assert len(ov['cases']) == 12
    assert ov['case_total'] == 15
    assert ov['archived_total'] == 2
    approve_todo = next(t for t in ov['todo'] if t['kind'] == 'approve')
    assert approve_todo['count'] == 15


# ---------------- V2 Red-Team Convergence Regression Tests ----------------

def test_p1_1_and_p2_2_xlsx_control_chars_unicode_formula_no_ghost_audit_and_email_newlines(env, monkeypatch):
    client, _ = env
    c = _approved_multicurrency_case(client)
    url = f"/api/cases/{c['id']}"

    # Direct unit test of _safe_cell for leading control char + full-width space formula
    assert quote_export._safe_cell('\x0b\u3000=SUM(1,2)') == "'\u3000=SUM(1,2)"

    # Inject embedded illegal XML control char (\x0b, \x07), newline (\n), and formula payload
    r = client.patch(
        f"{url}/rows/{c['rows'][0]['id']}",
        json={
            'revision': c['revision'],
            'values': {
                'description': '=SUM(1,2)\x0b\nfake terms',
                'reason': '测试非法控制字符与换行',
            },
        },
    )
    assert r.status_code == 200
    c = r.json()
    c = client.post(f"{url}/approve", json={'revision': c['revision'], 'values': {'actor': '测试\x07批准人\n换行'}}).json()

    # XLSX export MUST succeed (no openpyxl IllegalCharacterError 500!) and neutralize formula
    xlsx_resp = client.post(f"{url}/exports", json={'revision': c['revision'], 'values': {'format': 'xlsx'}})
    assert xlsx_resp.status_code == 200, xlsx_resp.text
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_resp.content))
    ws = wb['正式报价单']
    cell_vals = [ws.cell(row=ri, column=ci).value for ri in range(1, ws.max_row + 1) for ci in range(1, ws.max_column + 1)]
    assert any(isinstance(v, str) and v.startswith("'=SUM(1,2)") for v in cell_vals), cell_vals
    assert not any(isinstance(v, str) and ('\x0b' in v or '\x07' in v) for v in cell_vals)

    # Quote email collapses newlines in subject & single-line items
    em = client.get(f"{url}/quote-email?revision={c['revision']}&lang=zh").json()
    assert '\n' not in em['subject'] and '\r' not in em['subject']
    assert '\x0b' not in em['body'] and '\x07' not in em['body']
    item_lines = [ln for ln in em['body'].splitlines() if ln.startswith('1. ')]
    assert len(item_lines) == 1 and 'fake terms' in item_lines[0]

    # If rendering raises an error, audited_export MUST NOT leave a ghost export event in SQLite
    before_events = len(client.get(url).json()['events'])
    monkeypatch.setattr(main, 'export_response', lambda *a, **kw: (_ for _ in ()).throw(ValueError('simulated render error')))
    failed = client.post(f"{url}/exports", json={'revision': c['revision'], 'values': {'format': 'xlsx'}})
    assert failed.status_code == 409
    assert len(client.get(url).json()['events']) == before_events


def test_p1_2_and_p2_3_snapshot_pruning_and_cross_day_historical_diff(env):
    client, _ = env
    c = _approved_multicurrency_case(client)
    url = f"/api/cases/{c['id']}"

    # Cross-day diff: simulate an approval snapshot recorded yesterday with valid_until=yesterday
    yesterday = '2026-01-15'
    before_case = {
        'id': c['id'],
        'revision': 2,
        'price_version': 1,
        'rows': [{
            'id': 'r1', 'rfq': 'R-1', 'part': 'P-1', 'description': 'Seal', 'quantity': '2', 'unit': 'EA', 'condition': 'FN',
            'due': '2027-12-31', 'requirements': '', 'priority': '', 'raw_fields': {}, 'sources': [], 'excluded': False,
            'resolution': '', 'revision': 1, 'approval': None,
        }],
        'prices': [{
            'part': 'P-1', 'unit': 'EA', 'condition': 'FN', 'currency': 'USD', 'amount': '10.00',
            'valid_from': '2026-01-01', 'valid_until': yesterday, 'lead_time': '3d', 'source': 'S1', 'kind': 'synthetic',
        }],
        'warnings': [], 'fragments': [], 'events': [],
    }
    domain.approve(before_case, 'Alice', today=yesterday)
    after_case = {**before_case, 'revision': 3, 'rows': [{**before_case['rows'][0], 'quantity': '5'}]}
    d = domain.diff_snapshots(
        before_case,
        after_case,
        from_meta={'kind': 'approve', 'actor': 'Alice', 'created_at': f'{yesterday}T10:00:00+00:00'},
        to_meta={'kind': 'current', 'actor': '', 'created_at': ''},
    )
    row_changes = {ch['field']: ch for ch in d['rows'][0]['changes']}
    assert row_changes['approved']['before'] is True
    assert row_changes['price_amount']['before'] == '10.00'

    # Intermediate snapshot pruning keeps import + approve + at most MAX_INTERMEDIATE_SNAPSHOTS
    with main.connection() as db:
        for rev in range(10, 80):
            fake = {**c, 'revision': rev}
            main.save_snapshot(db, fake, 'edit', actor='tester')
        total_inter = db.execute(
            "SELECT COUNT(*) FROM case_snapshots WHERE case_id=? AND kind NOT IN ('import','approve')",
            (c['id'],),
        ).fetchone()[0]
        kept_key = db.execute(
            "SELECT COUNT(*) FROM case_snapshots WHERE case_id=? AND kind IN ('import','approve')",
            (c['id'],),
        ).fetchone()[0]
    assert total_inter == main.MAX_INTERMEDIATE_SNAPSHOTS
    assert kept_key >= 2


def test_p2_4_and_p2_5_long_offline_home_query_rule_kind_and_archived_write_guard(env):
    client, _ = env
    # 500-char offline home query (> 300 char References limit) must succeed cleanly
    long_parts_q = '液压系统那个密封圈还有多少库存？' + '请帮忙核对描述与库位信息。' * 30
    assert 301 <= len(long_parts_q) <= 600
    r1 = client.post('/api/agent/home', json={'message': long_parts_q})
    assert r1.status_code == 200, r1.text
    assert r1.json()['turn']['local'] is True

    long_rule_q = '请说明航材报价合并与冲突业务规则：' + '同件号不同询价号不可合并。' * 30
    assert 301 <= len(long_rule_q) <= 600
    r2 = client.post('/api/agent/home', json={'message': long_rule_q})
    assert r2.status_code == 200, r2.text
    for ref in r2.json()['turn'].get('references', []):
        for rec in ref.get('result', {}).get('records', []):
            assert rec.get('kind') == 'rule'

    # Archived case blocks mutations (row edit, append material) with 409 while still allowing unarchive
    c = _approved_multicurrency_case(client)
    url = f"/api/cases/{c['id']}"
    c_arch = client.patch(f"{url}/archive", json={'revision': c['revision'], 'values': {'archived': True}}).json()
    assert c_arch['archived'] is True
    # Snapshot kind for archive is 'archive'
    diff_info = client.get(f"{url}/diff").json()
    assert diff_info['snapshots'][-1]['kind'] == 'archive'

    assert client.patch(
        f"{url}/rows/{c_arch['rows'][0]['id']}",
        json={'revision': c_arch['revision'], 'values': {'quantity': '9', 'reason': '已归档修改应拒绝'}},
    ).status_code == 409
    assert client.post(
        f"{url}/materials",
        data={'revision': c_arch['revision']},
        files={'file': ('late.txt', b'RFQ: R-1\nPart: P-1\n')},
    ).status_code == 409

    # Unarchive re-enables editing
    c_unarch = client.patch(f"{url}/archive", json={'revision': c_arch['revision'], 'values': {'archived': False}}).json()
    assert c_unarch['archived'] is False
    assert client.patch(
        f"{url}/rows/{c_unarch['rows'][0]['id']}",
        json={'revision': c_unarch['revision'], 'values': {'quantity': '9', 'reason': '取消归档后允许修改'}},
    ).status_code == 200
