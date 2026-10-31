import pytest,time
from apps.api.model_usage import UsageLedger,usage_account
from apps.api.model_config import ModelSettings
def test_usage_and_secret():
    assert usage_account({'prompt_tokens':18,'completion_tokens':5,'total_tokens':121,'completion_tokens_details':{'reasoning_tokens':98}})==121
    assert usage_account(None) is None
    assert usage_account({'total_tokens':True}) is None
    assert 'secret-test' not in repr(ModelSettings('url','secret-test','m',True))
def test_daily_product_limits_reset_by_day_and_do_not_expire(tmp_path,monkeypatch):
    monkeypatch.setenv('RFQ_MODEL_LEDGER',str(tmp_path/'ledger.sqlite'));monkeypatch.delenv('RFQ_MODEL_RUN_ID',raising=False);monkeypatch.setenv('RFQ_MODEL_MAX_CALLS','2')
    l=UsageLedger();assert l.run.startswith('daily-')
    first=l.reserve({},'m',1000);l.finish(first,'ok',{'total_tokens':10})
    with l.connect() as c:c.execute('UPDATE calls SET started=?',(time.time()-2000,))
    l.finish(l.reserve({},'m',1000),'ok',{'total_tokens':10})
    with pytest.raises(ValueError,match='配额'):l.reserve({},'m',1000)
    with l.connect() as c:c.execute("UPDATE calls SET run='daily-yesterday'")
    assert l.reserve({},'m',1000)

def test_persistent_quota_failure_and_stop(tmp_path,monkeypatch):
    monkeypatch.setenv('RFQ_MODEL_LEDGER',str(tmp_path/'ledger.sqlite'));monkeypatch.setenv('RFQ_MODEL_RUN_ID','local-live')
    l=UsageLedger();r=l.reserve({},'m',1000);l.finish(r,'transport_failed')
    assert l.summary()['budget_charge_tokens']==1000 and l.summary()['unknown_usage_calls']==1
    for i in range(7):l.finish(l.reserve({},'m',1000),'ok',{'total_tokens':10})
    with pytest.raises(ValueError,match='配额'):l.reserve({},'m',1000)
    l.stop.touch()
    with pytest.raises(ValueError,match='终止'):l.reserve({},'m',1000)
def test_wall_and_token_budget(tmp_path,monkeypatch):
    monkeypatch.setenv('RFQ_MODEL_LEDGER',str(tmp_path/'ledger.sqlite'));monkeypatch.setenv('RFQ_MODEL_RUN_ID','local-live')
    l=UsageLedger();r=l.reserve({},'m',1000)
    with l.connect() as c:c.execute('UPDATE calls SET started=?',(time.time()-2000,))
    with pytest.raises(ValueError,match='墙钟'):l.reserve({},'m',1000)
    with pytest.raises(ValueError,match='token'):l.reserve({},'m',96000)

def test_finite_allowlist(tmp_path):
    from pathlib import Path
    import shutil
    from apps.api.materials import read_materials
    from apps.api.semantic import synthetic_remote_allowed
    root=Path(__file__).resolve().parents[1]
    folder=tmp_path/'data/synthetic/model-live-20261027'
    shutil.copytree(root/'data/synthetic/model-live-20261027',folder)
    upload=tmp_path/'upload';upload.mkdir()
    shutil.copyfile(folder/'normal.txt',upload/'normal.txt')
    assert synthetic_remote_allowed(read_materials(upload),tmp_path)
    (upload/'normal.txt').write_text('unknown upload')
    assert not synthetic_remote_allowed(read_materials(upload),tmp_path)
    (folder/'normal.txt').write_text('unknown upload')
    assert not synthetic_remote_allowed(read_materials(upload),tmp_path)

def test_competitive_unknown_stops_without_retry(tmp_path,monkeypatch):
    monkeypatch.setenv('RFQ_MODEL_LEDGER',str(tmp_path/'competitive.sqlite'))
    monkeypatch.setenv('RFQ_MODEL_RUN_ID','competitive-validation-20261028-1')
    monkeypatch.setenv('RFQ_MODEL_MAX_CALLS','40');monkeypatch.setenv('RFQ_MODEL_TASK_MAX_TOKENS','500000')
    l=UsageLedger();r=l.reserve({},'m',6000);l.finish(r,'transport_failed')
    with pytest.raises(ValueError,match='未知'):l.reserve({},'m',6000)
    assert l.summary()['request_count']==1 and l.summary()['unknown_usage_calls']==1

def test_goal_second_batch_requires_audit_and_preserves_first(tmp_path,monkeypatch):
    import sqlite3,time
    monkeypatch.setenv('RFQ_MODEL_LEDGER',str(tmp_path/'goal.sqlite'))
    monkeypatch.setenv('RFQ_MODEL_RUN_ID','goal-readiness-20261029-1')
    monkeypatch.setenv('RFQ_MODEL_MAX_CALLS','40');monkeypatch.setenv('RFQ_MODEL_TASK_MAX_TOKENS','500000')
    l=UsageLedger()
    for _ in range(40):l.finish(l.reserve({},'m',1000),'ok',{'total_tokens':1})
    with pytest.raises(ValueError):l.reserve({},'m',1000)
    monkeypatch.setenv('RFQ_MODEL_BATCH','02');monkeypatch.setenv('RFQ_MODEL_MAX_CALLS','60');l=UsageLedger()
    with pytest.raises(ValueError,match='审计'):l.reserve({},'m',1000)
    with l.connect() as c:c.execute('INSERT INTO batch_audits VALUES (?,?,?,?,?,?)',(l.run,'02',40,time.time(),None,'explicit test authorization'))
    r=l.reserve({},'m',1000);l.finish(r,'ok',{'total_tokens':2})
    assert l.summary()['request_count']==41 and l.summary()['accounted_tokens_known_sum']==42
    with l.connect() as c:assert c.execute('select first_started from batch_audits').fetchone()[0] is not None

def test_goal_second_window_requires_its_own_audit(tmp_path,monkeypatch):
    monkeypatch.setenv('RFQ_MODEL_LEDGER',str(tmp_path/'goal.sqlite'))
    monkeypatch.setenv('RFQ_MODEL_RUN_ID','goal-readiness-20261029-1')
    monkeypatch.setenv('RFQ_MODEL_MAX_CALLS','40');monkeypatch.setenv('RFQ_MODEL_TASK_MAX_TOKENS','500000')
    l=UsageLedger()
    for _ in range(40):l.finish(l.reserve({},'m',1000),'ok',{'total_tokens':1})
    with l.connect() as c:c.execute('INSERT INTO batch_audits VALUES (?,?,?,?,?,?)',(l.run,'02',40,time.time(),None,'test batch'))
    monkeypatch.setenv('RFQ_MODEL_BATCH','02');monkeypatch.setenv('RFQ_MODEL_MAX_CALLS','60');l=UsageLedger()
    for _ in range(3):l.finish(l.reserve({},'m',1000),'ok',{'total_tokens':1})
    with l.connect() as c:batch_start=c.execute('select first_started from batch_audits').fetchone()[0]
    monkeypatch.setenv('RFQ_MODEL_WINDOW','02');l=UsageLedger()
    with pytest.raises(ValueError,match='窗口.*审计'):l.reserve({},'m',1000)
    with l.connect() as c:c.execute('INSERT INTO window_audits VALUES (?,?,?,?,?,?)',(l.run,'02',43,time.time(),None,'test window'))
    l.finish(l.reserve({},'m',1000),'ok',{'total_tokens':1})
    with l.connect() as c:
        assert c.execute('select first_started from batch_audits').fetchone()[0]==batch_start
        assert c.execute('select first_started from window_audits').fetchone()[0] is not None
    assert l.summary()['request_count']==44
