from fastapi.testclient import TestClient
from apps.api import main

MAIL=b'Subject: Synthetic scope\nContent-Type: text/plain\n\nRFQ No.\tPart Number\tQuantity\tUnit\tCondition\n009401\tSCOPE-001\t2\tEA\tFN\n'

def test_each_browser_sees_only_its_own_work_orders(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'test.sqlite');monkeypatch.setattr(main,'SCOPED',True)
    with TestClient(main.app) as mine, TestClient(main.app) as theirs:
        case=mine.post('/api/import',files={'file':('scope.eml',MAIL)}).json()
        assert [c['id'] for c in mine.get('/api/cases').json()]==[case['id']]
        assert mine.get(f"/api/cases/{case['id']}").status_code==200
        # Another browser cannot list, read, change or export it, and cannot tell it exists.
        assert theirs.get('/api/cases').json()==[]
        for method,path in [('get',''),('get','/materials'),('get','/matrixone'),('get','/agent'),('get','/export'),('post','/approve')]:
            r=getattr(theirs,method)(f"/api/cases/{case['id']}{path}",**({'json':{'revision':case['revision'],'values':{'actor':'x'}}} if method=='post' else {}))
            assert r.status_code==404,(path,r.status_code)
        # A forged cookie that is not the owner's is just another visitor.
        theirs.cookies.set('rfq_visitor','A'*43)
        assert theirs.get(f"/api/cases/{case['id']}").status_code==404
        assert mine.get(f"/api/cases/{case['id']}").status_code==200

def test_scope_is_off_for_local_review(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'ROOT',tmp_path);monkeypatch.setattr(main,'DB',tmp_path/'test.sqlite')
    with TestClient(main.app) as one, TestClient(main.app) as other:
        case=one.post('/api/import',files={'file':('scope.eml',MAIL)}).json()
        assert other.get(f"/api/cases/{case['id']}").status_code==200
        assert 'rfq_visitor' not in one.cookies
