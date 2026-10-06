"""Exercise real HTTP requests before API dispatch; no provider or authentication."""
import http.client
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from local_http import LocalOnlyHTTPMixin


@pytest.fixture
def local_server(tmp_path):
    dashboard = tmp_path / 'dashboard'
    dashboard.mkdir()
    (dashboard / 'index.html').write_text('chart')
    (dashboard / '.local.json').write_text('private')
    (dashboard / 'folder').mkdir()
    (tmp_path / 'private.txt').write_text('private')
    (dashboard / 'linked.txt').symlink_to(tmp_path / 'private.txt')
    requests = []

    class Handler(LocalOnlyHTTPMixin, SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(dashboard), **kwargs)

        def do_GET(self):
            if self.path == '/api/test':
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'local')
                return
            super().do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def get(port, path='/api/test', headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request('GET', path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.mark.parametrize('headers', [
    {'Host': 'attacker.example'},
    {'Host': '127.0.0.1:1'},
    {'Origin': 'https://attacker.example'},
    {'Origin': 'null'},
    {'Referer': 'https://attacker.example/page'},
    {'Referer': 'http://['},
    {'Sec-Fetch-Site': 'cross-site'},
])
def test_external_page_cannot_dispatch_api(local_server, headers):
    port, dispatched = local_server
    assert get(port, headers=headers)[0] == 403
    assert dispatched == []


def test_cli_and_local_browser_requests_work(local_server):
    port, dispatched = local_server
    assert get(port)[0] == 200
    status, headers, body = get(port, headers={
        'Host': f'localhost:{port}', 'Origin': f'http://localhost:{port}',
        'Referer': f'http://localhost:{port}/chart-first.html',
        'Sec-Fetch-Site': 'same-origin'})
    assert status == 200 and body == b'local' and len(dispatched) == 2
    assert 'Access-Control-Allow-Origin' not in headers
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['X-Frame-Options'] == 'DENY'


@pytest.mark.parametrize('path', ['/.local.json', '/%2elocal.json', '/folder/',
                                  '/linked.txt', '/../private.txt'])
def test_private_files_listing_and_symlink_escape_blocked(local_server, path):
    port, _ = local_server
    status, _, body = get(port, path=path)
    assert status == 404 and b'private' not in body
    assert get(port, path='/')[0] == 200


def test_duplicate_host_and_absolute_proxy_target_blocked(local_server):
    port, dispatched = local_server
    connection = http.client.HTTPConnection('127.0.0.1', port)
    connection.putrequest('GET', '/api/test')
    connection.putheader('Host', 'attacker.example')
    connection.endheaders()
    response = connection.getresponse()
    assert response.status == 403
    response.read()
    connection.close()
    assert get(port, path='http://attacker.example/api/test',
               headers={'Host': f'127.0.0.1:{port}'})[0] == 400
    assert dispatched == []
