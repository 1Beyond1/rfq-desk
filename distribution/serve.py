"""One foreground process serves the unchanged UI and local API from this copy."""
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import os
import socket
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.chdir(ROOT)
os.environ['RFQ_DB']=str(Path(os.environ.get('RFQ_DB') or ROOT/'var/rfq.sqlite3').expanduser().resolve())
model_enabled='--model' in sys.argv
os.environ['RFQ_ENABLE_MODEL_REQUESTS']='1' if model_enabled else '0'
os.environ['RFQ_ENABLE_PLATFORM_SNAPSHOT_REQUESTS']='0'
if not model_enabled:
    for name in ('RFQ_MODEL_URL','RFQ_MODEL_KEY','RFQ_MODEL_NAME'):os.environ[name]=''
else:
    from urllib.parse import urlsplit
    from apps.api.model_config import ModelSettings
    from apps.api.material_policy import known_hashes
    primary=ModelSettings.from_env()
    if not primary.configured:
        raise SystemExit('Model mode requires an HTTPS endpoint, model name and key in the process environment.')
    try:
        for route in ModelSettings.routes():
            endpoint=urlsplit(route.endpoint)
            if endpoint.scheme!='https' or not endpoint.hostname or endpoint.username or endpoint.password:
                raise ValueError('Each model route requires an HTTPS endpoint without URL credentials.')
        known_hashes(ROOT)
    except ValueError as e:raise SystemExit(str(e))
for name in ('RFQ_MOI_API_KEY','RFQ_MOI_WORKSPACE_ID','RFQ_MOI_VOLUME_ID'):os.environ[name]=''
# A container listens on all of its own interfaces; the host decides what reaches them.
HOST=os.environ.get('RFQ_BIND_HOST','127.0.0.1')

if __name__=='__main__':
    # Do not attach to an unrelated service or attempt to terminate a port owner.
    for port in (8311,5311):
        probe=socket.socket()
        try:probe.bind((HOST,port))
        except OSError:raise SystemExit(f'Port {port} unavailable. Stop only your own service, then retry.')
        finally:probe.close()
    import uvicorn
    from apps.api import main
    from scripts.serve_web import Handler
    assert Path(main.__file__).resolve().is_relative_to(ROOT)
    server=ThreadingHTTPServer((HOST,5311),partial(Handler,directory=str(ROOT/'apps/web')))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    (ROOT/'var').mkdir(exist_ok=True)
    info={'pid':os.getpid(),'root':str(ROOT),'api_source':str(Path(main.__file__).resolve()),
          'database':str(main.DB),'uploads':str(ROOT/'var/uploads'),'web':'http://127.0.0.1:5311/',
          'model_requests_enabled':model_enabled,'platform_requests_enabled':False}
    (ROOT/'var/process.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    print('RFQ Desk local review: http://127.0.0.1:5311/ ; Ctrl+C stops both services.',flush=True)
    thread.start()
    # Only an explicitly configured proxy may supply the visitor address.
    # In Docker the host reverse proxy reaches us through a bridge gateway.
    # Keeping the default loopback-only prevents arbitrary forwarded-IP trust.
    try:uvicorn.run(main.app,host=HOST,port=8311,access_log=False,
                    proxy_headers=True,forwarded_allow_ips=os.getenv('RFQ_PROXY_IPS','127.0.0.1'))
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
