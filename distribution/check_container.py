"""Run inside the deployed A container. Uses local disk/loopback only, with zero model requests."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.request import ProxyHandler, build_opener
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.api.material_policy import known_hashes
from apps.api.model_config import ModelSettings


def main():
    if not hasattr(os, 'getuid') or (os.getuid(), os.getgid()) != (10001, 10001):
        raise SystemExit('Expected the container user/group 10001:10001.')
    if not os.statvfs(ROOT).f_flag & os.ST_RDONLY:
        raise SystemExit('The application filesystem is not read-only.')
    if os.environ.get('RFQ_VISITOR_SCOPE') != '1':
        raise SystemExit('Visitor isolation is not enabled.')
    with tempfile.TemporaryDirectory(prefix='container-check-', dir=ROOT / 'var') as folder:
        folder = Path(folder)
        (folder / 'upload.txt').write_text('Synthetic write check', encoding='utf-8')
        with sqlite3.connect(folder / 'probe.sqlite3') as db:
            db.execute('CREATE TABLE probe (value TEXT)')
            db.execute('INSERT INTO probe VALUES (?)', ('synthetic',))
            assert db.execute('SELECT value FROM probe').fetchone()[0] == 'synthetic'
    opener = build_opener(ProxyHandler({}))
    auth = os.environ.get('RFQ_AUTH_REQUIRED') == '1'
    if auth:
        with opener.open('http://127.0.0.1:8311/api/auth/session', timeout=10) as response:
            state = json.load(response)
        assert state['required'] and state['user'] is None
        try:
            opener.open('http://127.0.0.1:8311/api/cases', timeout=10)
        except HTTPError as error:
            assert error.code == 401
        else:
            raise SystemExit('Unauthenticated work orders must be rejected.')
        with sqlite3.connect(f'file:{ROOT / "var/rfq.sqlite3"}?mode=ro', uri=True) as db:
            if not db.execute("SELECT COUNT(*) FROM auth_users WHERE role='admin' AND active=1").fetchone()[0]:
                raise SystemExit('Initialize a real administrator before rollout.')
        health = {'mode':'login-required','matrixone':{'connected':None}}
    else:
        with opener.open('http://127.0.0.1:8311/api/health', timeout=10) as response:
            health = json.load(response)
    print(json.dumps({'uid': os.getuid(), 'root_read_only': True, 'var_sqlite_and_upload_writable': True,
                      'official_fingerprints': len(known_hashes(ROOT)), 'configured_routes': len(ModelSettings.routes()),
                      'visitor_scope': os.environ.get('RFQ_VISITOR_SCOPE') == '1', 'mode': health['mode'],
                      'account_auth_required': auth,
                      'matrixone_connected': health['matrixone']['connected'],
                      'model_requests_from_this_check': 0}, indent=2))


if __name__ == '__main__':
    main()
