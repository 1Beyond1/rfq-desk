import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from apps.api import main,accounts

@pytest.fixture
def demo_env(tmp_path,monkeypatch):
    monkeypatch.setenv('RFQ_AUTH_REQUIRED','1');monkeypatch.setenv('RFQ_COOKIE_SECURE','0');monkeypatch.setenv('RFQ_PUBLIC_ORIGIN','http://testserver')
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'test.sqlite3')
    shutil.copytree(Path(__file__).resolve().parents[1]/'data/synthetic',tmp_path/'data/synthetic')

def enter(c):
    r=c.post('/api/auth/demo',json={});assert r.status_code==200,r.text
    s=r.json();c.headers.update({'X-RFQ-Account':s['user']['id'],'X-CSRF-Token':s['csrf']});return s

def test_judge_button_creates_isolated_passwordless_non_admin_spaces(demo_env):
    with TestClient(main.app) as a,TestClient(main.app) as b:
        sa=enter(a);sb=enter(b);assert sa['user']['id']!=sb['user']['id'];assert sa['user']['role']=='demo' and not sa['user']['must_change']
        ca=a.post('/api/guided-demo').json();cb=b.post('/api/guided-demo').json()
        assert main.synthetic_remote_allowed(main.case_materials(ca),main.ROOT)
        assert [x['id'] for x in a.get('/api/cases').json()]==[ca['id']]
        assert b.get('/api/cases/'+ca['id']).status_code==404
        assert a.get('/api/cases/'+cb['id']+'/materials').status_code==404
        assert a.get('/api/admin/users').status_code==403
        assert a.post('/api/auth/password',json={'old_password':'some long old phrase','new_password':'some long new phrase'}).status_code==403
        assert a.post('/api/import',files={'file':('private.txt',b'private')}).status_code==403
        again=enter(a);assert again['user']['id']==sa['user']['id']
        assert a.post('/api/auth/logout').status_code==200
        assert a.get('/api/cases').status_code==401

def test_judge_creation_origin_and_model_operation_limits(demo_env):
    with TestClient(main.app) as c:
        assert c.post('/api/auth/demo',json={},headers={'Origin':'https://evil.example'}).status_code==403
        s=enter(c);token=accounts.USER.set(s['user'])
        try:
            for _ in range(accounts.demo_ai_calls()):main.ACCOUNTS.reserve_demo_call()
            with pytest.raises(Exception) as e:main.ACCOUNTS.reserve_demo_call()
            assert e.value.status_code==429
        finally:accounts.USER.reset(token)
        for _ in range(6):assert c.post('/api/guided-demo').status_code==200
        assert c.post('/api/guided-demo').status_code==429
        with main.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM cases').fetchone()[0]==6
