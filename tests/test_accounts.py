import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from apps.api import main, accounts

PASSWORD = 'Synthetic account password 2026'
NEW_PASSWORD = '更新后的合成测试密码短语2026'
MAIL = b'Subject: Synthetic account isolation\nContent-Type: text/plain\n\nRFQ No.\tPart Number\tQuantity\tUnit\tCondition\n000901\tACCT-001\t2\tEA\tFN\n'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('RFQ_AUTH_REQUIRED', '1')
    monkeypatch.setenv('RFQ_COOKIE_SECURE', '0')
    monkeypatch.setenv('RFQ_PUBLIC_ORIGIN', 'http://testserver')
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'DB', tmp_path/'accounts.sqlite3')
    monkeypatch.setattr(main, 'SCOPED', False)  # Account isolation must not depend on the legacy toggle.
    admin = main.ACCOUNTS.create('admin', '管理员', PASSWORD, role='admin', must_change=False)
    user = main.ACCOUNTS.create('alice', '用户甲', PASSWORD, must_change=False)
    return admin, user


def login(client, name='alice', password=PASSWORD):
    result = client.post('/api/auth/login', json={'username':name, 'password':password})
    assert result.status_code == 200, result.text
    state = result.json()
    client.headers.update({'X-CSRF-Token':state['csrf'], 'X-RFQ-Account':state['user']['id']})
    return state


def test_no_business_or_admin_api_before_login_and_no_default_admin(tmp_path, monkeypatch):
    monkeypatch.setenv('RFQ_AUTH_REQUIRED', '1')
    monkeypatch.setattr(main, 'DB', tmp_path/'empty.sqlite3')
    with TestClient(main.app) as guest:
        assert guest.get('/api/auth/session').json() == {'required':True,'user':None,'csrf':None}
        for method,path in [('GET','/api/cases'),('GET','/api/health'),('POST','/api/demo'),('POST','/api/agent/start'),('GET','/api/admin/users'),('GET','/api/admin/audit')]:
            r=guest.request(method,path)
            assert r.status_code==401, (path,r.text)
            assert r.headers['cache-control']=='no-store'


def test_account_owns_cases_on_another_browser_but_admin_cannot_bypass(setup):
    with TestClient(main.app) as owner, TestClient(main.app) as other, TestClient(main.app) as admin:
        login(owner);login(other);login(admin,'admin')
        case=owner.post('/api/import',files={'file':('account.eml',MAIL)}).json()
        assert other.get('/api/cases').json()[0]['id']==case['id']
        assert admin.get('/api/cases').json()==[]
        for method,suffix in [('GET',''),('GET','/materials'),('GET','/agent'),('GET','/matrixone'),('GET','/agent/progress'),('GET','/quote-preview'),('POST','/exports'),('PATCH','/rows/anything'),('POST','/approve')]:
            assert admin.request(method,'/api/cases/'+case['id']+suffix,json={}).status_code==404
        assert owner.get('/api/official').json()==[]
        assert owner.post('/api/official/0').status_code==403
        recorded=other.get('/api/cases/'+case['id']).json()['events'][0]['detail']['account']
        assert recorded=={'id':setup[1]['id'],'username':'alice'}


def test_csrf_cross_origin_and_account_switch_block_writes(setup):
    with TestClient(main.app) as client:
        state=login(client)
        client.headers.pop('X-CSRF-Token')
        assert client.post('/api/demo').status_code==403
        client.headers['X-CSRF-Token']=state['csrf']
        assert client.post('/api/demo',headers={b'x-csrf-token':b'\xff'}).status_code==403
        assert client.post('/api/demo',headers={'Origin':'https://evil.example'}).status_code==403
        assert client.post('/api/demo',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
        client.headers['X-RFQ-Account']='another-account'
        r=client.post('/api/import',files={'file':('bad.eml',MAIL)})
        assert r.status_code==409 and r.headers['X-RFQ-Session-Changed']=='1'
        cors=client.get('/api/cases',headers={'Origin':'http://127.0.0.1:5311'})
        assert cors.status_code==409
        assert cors.headers['access-control-allow-origin']=='http://127.0.0.1:5311'
        assert cors.headers['access-control-expose-headers']=='X-RFQ-Session-Changed'
        client.headers['X-RFQ-Account']=state['user']['id']
        assert client.get('/api/cases').json()==[]


def test_first_login_change_password_and_logout_revoke_sessions(setup):
    main.ACCOUNTS.create('new.user','新用户',PASSWORD)
    with TestClient(main.app) as first,TestClient(main.app) as second,TestClient(main.app) as replay:
        login(first,'new.user');login(second,'new.user')
        old_cookie=second.cookies.get(accounts.COOKIE)
        assert first.get('/api/cases').status_code==403
        assert first.post('/api/auth/password',json={'old_password':'incorrect password long','new_password':NEW_PASSWORD}).status_code==422
        assert first.post('/api/auth/password',json={'old_password':PASSWORD,'new_password':NEW_PASSWORD}).status_code==200
        assert first.get('/api/cases').status_code==401
        assert second.get('/api/cases').status_code==401
        login(first,'new.user',NEW_PASSWORD)
        assert first.get('/api/cases').status_code==200
        cookie=first.cookies.get(accounts.COOKIE)
        assert first.post('/api/auth/logout').status_code==200
        replay.cookies.set(accounts.COOKIE,cookie)
        assert replay.get('/api/auth/session').json()['user'] is None
        replay.cookies.set(accounts.COOKIE,old_cookie)
        assert replay.get('/api/auth/session').json()['user'] is None


def test_admin_create_disable_enable_and_regular_user_denied(setup):
    with TestClient(main.app) as admin,TestClient(main.app) as user,TestClient(main.app) as employee:
        login(admin,'admin');login(user)
        for path in ('/api/admin/users','/api/admin/audit'):
            assert user.get(path).status_code==403
        assert user.post('/api/admin/users',json={'username':'fake.user','name':'假','password':PASSWORD}).status_code==403
        r=admin.post('/api/admin/users',json={'username':'employee','name':'新同事','password':PASSWORD,'role':'admin'})
        assert r.status_code==200
        created=r.json();assert created['role']=='user' and created['must_change']==1
        login(employee,'employee')
        assert admin.patch('/api/admin/users/'+created['id'],json={'active':False}).status_code==200
        assert employee.get('/api/auth/session').json()['user'] is None
        assert employee.post('/api/auth/login',json={'username':'employee','password':PASSWORD}).status_code==401
        assert admin.patch('/api/admin/users/'+created['id'],json={'active':True}).status_code==200
        assert admin.patch('/api/admin/users/'+setup[0]['id'],json={'active':False}).status_code==422
        assert 'password' not in json.dumps(admin.get('/api/admin/users').json())
        events=admin.get('/api/admin/audit').json()
        assert any(e['action']=='account_disable' and e['actor']=='admin' and e['subject']=='employee' for e in events)


def test_secure_cookie_hashes_and_expiry(setup,monkeypatch):
    monkeypatch.setenv('RFQ_COOKIE_SECURE','1')
    with TestClient(main.app,base_url='https://testserver') as client:
        response=client.post('/api/auth/login',json={'username':'alice','password':PASSWORD})
        assert response.status_code==200
        cookie=response.headers['set-cookie'].lower()
        assert all(x in cookie for x in ('httponly','secure','samesite=strict','path=/'))
        raw=client.cookies.get(accounts.COOKIE)
        with main.connection() as c:
            main.ACCOUNTS.schema(c)
            stored=c.execute('SELECT password FROM auth_users WHERE username="alice"').fetchone()[0]
            token=c.execute('SELECT token FROM auth_sessions').fetchone()[0]
            assert stored.startswith('scrypt$') and PASSWORD not in stored and token!=raw
            c.execute('UPDATE auth_sessions SET seen=?',(int(time.time())-accounts.IDLE_TTL-1,))
        assert client.get('/api/auth/session').json()['user'] is None
        client.cookies.set(accounts.COOKIE,'forged-cookie')
        assert client.get('/api/auth/session').json()['user'] is None


def test_failed_login_rate_limit_and_origin_before_hash(setup):
    with TestClient(main.app) as client:
        assert client.post('/api/auth/login',json={'username':'alice','password':PASSWORD},headers={'Origin':'https://evil.example'}).status_code==403
        for _ in range(10):
            assert client.post('/api/auth/login',json={'username':'unknown','password':'bad password phrase'}).status_code==401
        assert client.post('/api/auth/login',json={'username':'unknown','password':PASSWORD}).status_code==429


def test_existing_owner_and_content_unchanged_when_enabling_auth(setup):
    with main.connection() as c:
        original={'id':'legacy','events':[]}
        c.execute('INSERT INTO cases VALUES(?,?)',('legacy',json.dumps(original)))
        c.execute('INSERT INTO case_owners VALUES(?,?)',('legacy','old-visitor-token'))
    with TestClient(main.app) as admin:
        login(admin,'admin')
        assert admin.get('/api/cases').json()==[]
        assert admin.get('/api/cases/legacy').status_code==404
    with main.connection() as c:
        assert c.execute('SELECT visitor FROM case_owners WHERE case_id="legacy"').fetchone()[0]=='old-visitor-token'
        assert json.loads(c.execute('SELECT body FROM cases WHERE id="legacy"').fetchone()[0])==original


def test_guided_example_prices_approval_export_and_invalidation(setup):
    import shutil
    from pathlib import Path
    fixtures=Path(__file__).resolve().parents[1]/'data/synthetic'
    shutil.copytree(fixtures,main.ROOT/'data/synthetic')
    with TestClient(main.app) as user:
        login(user)
        case=user.post('/api/guided-demo').json()
        assert len(case['rows'])==2 and case['rows'][0]['part']==case['rows'][1]['part']
        assert case['rows'][0]['rfq']!=case['rows'][1]['rfq']
        base='/api/cases/'+case['id']
        response=user.post(base+'/demo-prices',json={'revision':case['revision'],'values':{}})
        assert response.status_code==200,response.text
        case=response.json();assert all(r['price'] for r in case['rows'])
        response=user.post(base+'/approve',json={'revision':case['revision'],'values':{'actor':'合成测试'}})
        assert response.status_code==200,response.text
        case=response.json()
        assert all(r['approval']['actor']=='用户甲 (alice)' for r in case['rows'])
        response=user.post(base+'/exports',json={'revision':case['revision'],'values':{'format':'csv'}})
        import csv
        import io
        from decimal import Decimal
        assert response.status_code==200
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        assert [r['询价号'] for r in rows]==['000301','000302']
        assert sum(Decimal(r['总价']) for r in rows)==Decimal('61.75')
        row=case['rows'][0]
        response=user.patch(base+'/rows/'+row['id'],json={'revision':case['revision'],'values':{'quantity':'4','reason':'合成数量修订'}})
        assert response.status_code==200,response.text
        changed=response.json();assert not changed['rows'][0]['approved']
        assert user.post(base+'/exports',json={'revision':changed['revision'],'values':{'format':'csv'}}).status_code==409
