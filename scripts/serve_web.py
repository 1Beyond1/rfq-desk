"""Local static server; always revalidate the workbench after code changes.
Single byte ranges are served as 206 so the demo video plays and seeks in Safari/iOS."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from pathlib import Path
import os
import re

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; media-src 'self'; frame-src 'self' blob:; object-src 'none'; "
    "connect-src 'self' http://127.0.0.1:8311 http://localhost:8311; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
RANGE_RE = re.compile(r'bytes=(\d{0,18})-(\d{0,18})')


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(SimpleHTTPRequestHandler):
    timeout = 15

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', CSP)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, 'Not Found')
        return None

    def send_head(self):
        self._remain = None
        m = RANGE_RE.fullmatch(self.headers.get('Range', '').strip())
        path = self.translate_path(self.path)
        if not m or m.groups() == ('', '') or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        a, b = m.groups()
        if size == 0:
            self.send_response(416)
            self.send_header('Content-Range', 'bytes */0')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        if a == '':
            suffix = int(b)
            if suffix == 0:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return None
            start, end = max(0, size - suffix), size - 1
        else:
            start = int(a)
            end = min(int(b), size - 1) if b else size - 1
        if start > end or start >= size:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        f = open(path, 'rb')
        try:
            f.seek(start)
            self.send_response(206)
            self.send_header('Content-Type', self.guess_type(path))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header('Content-Length', str(end - start + 1))
            self.end_headers()
            self._remain = end - start + 1
            return f
        except Exception:
            f.close()
            raise

    def copyfile(self, source, outputfile):
        n = getattr(self, '_remain', None)
        if n is None:
            return super().copyfile(source, outputfile)
        while n > 0:
            chunk = source.read(min(65536, n))
            if not chunk:
                break
            outputfile.write(chunk)
            n -= len(chunk)


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1] / 'apps/web'
    print('RFQ Web http://127.0.0.1:5311 (no-store)', flush=True)
    WebServer(('127.0.0.1', 5311), partial(Handler, directory=str(root))).serve_forever()
