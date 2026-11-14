"""The demo video must play in Safari/iOS, which only plays media from servers that answer byte ranges."""
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

from scripts.serve_web import Handler


def serve(tmp_path):
    (tmp_path / 'clip.mp4').write_bytes(bytes(range(256)) * 4)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}/clip.mp4?v=1'


def get(url, rng=None):
    req = urllib.request.Request(url, headers={'Range': rng} if rng else {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b''


def test_byte_ranges_are_partial_content(tmp_path):
    server, url = serve(tmp_path)
    body = bytes(range(256)) * 4
    try:
        assert get(url)[0] == 200 and get(url)[2] == body
        status, headers, data = get(url, 'bytes=0-1')
        assert status == 206 and data == body[:2] and headers['Content-Range'] == 'bytes 0-1/1024'
        status, headers, data = get(url, 'bytes=1000-')
        assert status == 206 and data == body[1000:] and headers['Content-Length'] == '24'
        status, _, data = get(url, 'bytes=-10')
        assert status == 206 and data == body[-10:]
        assert get(url, 'bytes=5000-')[0] == 416
    finally:
        server.shutdown()
