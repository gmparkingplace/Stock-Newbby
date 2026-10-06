#!/usr/bin/env python3
"""Portable entry point: python run.py [--offline | --live] [--port 8734]."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import subprocess

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / 'results' / 'dashboard'


def open_default_browser(url):
    """Use the OS default browser without mixing its output with server errors."""
    log_path = ROOT / 'logs' / 'browser.log'
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('ab') as log:
            log.write(('\n--- Browser launch: ' + url + ' ---\n').encode())
            log.flush()
            child = subprocess.Popen(
                [sys.executable, '-c',
                 'import sys,webbrowser; sys.exit(0 if webbrowser.open(sys.argv[1]) else 1)', url],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
        print(f'기본 브라우저 열기 · 브라우저 로그: {log_path}', flush=True)
        if child.wait() != 0:
            print(f'브라우저 자동 열기 실패. 원하는 브라우저에서 {url} 를 열어 주세요.\n상세 로그: {log_path}', flush=True)
    except OSError as exc:
        print(f'브라우저 자동 열기 실패: {exc}\n원하는 브라우저에서 {url} 를 열어 주세요.', flush=True)


def main():
    parser = argparse.ArgumentParser(description='초보자 차트 보조기 — 통합 실행')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--offline', action='store_true', help='저장된 자료만 사용')
    mode.add_argument('--live', action='store_true', help='최신조회 서버 사용 (Python 의존성 필요)')
    parser.add_argument('--port', type=int, default=8734)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    local_python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not args.offline and local_python.is_file() and Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
        os.execv(str(local_python), [str(local_python), str(Path(__file__).resolve()), *sys.argv[1:]])
    missing = [name for name in ('pandas', 'numpy', 'yfinance') if importlib.util.find_spec(name) is None]
    if args.live and missing:
        parser.exit(2, '최신조회 의존성 누락: ' + ', '.join(missing) + '\npython setup.py 로 설치하거나 --offline으로 실행하세요.\n')
    live = not args.offline and not missing
    sys.path.insert(0, str(ROOT / 'scripts'))
    from local_http import LocalOnlyHTTPMixin
    if live:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from serve_dashboard import H as BaseHandler
    else:
        class BaseHandler(LocalOnlyHTTPMixin, SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(DASHBOARD), **kw)
            def log_message(self, *a):
                pass

    sys.path.insert(0, str(ROOT / 'scripts'))
    from chart_control import handle as control_handle

    class Handler(BaseHandler):
        def do_POST(self):
            if not control_handle(self):
                post = getattr(super(), 'do_POST', None)
                if post: post()
                else: self.send_error(404)

        def do_GET(self):
            if control_handle(self): return
            endpoint = self.path.split('?', 1)[0]
            if endpoint == '/api/package':
                try: version = json.loads((ROOT / 'package.json').read_text())['version']
                except Exception: version = 'unknown'
                body = json.dumps({'app': 'chart-assistant', 'version': version,
                                   'mode': 'live' if live else 'offline'}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not live and endpoint.startswith('/api/'):
                body = b'{"error":"offline mode","kind":"offline"}'
                self.send_response(503)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError as exc:
        parser.exit(2, f'서버를 열지 못했습니다: {exc}\n다른 포트로 실행하세요: python run.py --port 8735\n')
    url = f'http://127.0.0.1:{server.server_port}/chart-first.html'
    print('최신조회 모드' if live else '저장 자료 모드 (최신조회 꺼짐)', flush=True)
    if missing and not args.offline:
        print('최신조회 설치: python setup.py → 설치 후 다시 실행', flush=True)
    print(url + '\n종료: Ctrl+C', flush=True)
    if not args.no_browser:
        threading.Thread(target=open_default_browser, args=(url,), daemon=True).start()
    if live:
        from monitor_service import start_runtime
        start_runtime()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if live:
            import monitor_service
            if monitor_service._INSTANCE is not None:monitor_service._INSTANCE.close()
        server.server_close()


if __name__ == '__main__':
    main()
