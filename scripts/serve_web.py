"""Local static server; always revalidate the workbench after code changes."""
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from functools import partial
from pathlib import Path
class Handler(SimpleHTTPRequestHandler):
 def end_headers(self):
  self.send_header('Cache-Control','no-store')
  self.send_header('Content-Security-Policy',"script-src 'self'")
  super().end_headers()
if __name__=='__main__':
 root=Path(__file__).resolve().parents[1]/'apps/web'
 print('RFQ Web http://127.0.0.1:5311 (no-store)',flush=True)
 ThreadingHTTPServer(('127.0.0.1',5311),partial(Handler,directory=str(root))).serve_forever()
