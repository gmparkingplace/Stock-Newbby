"""Production response path; offline handlers, no server or authentication."""
import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import serve_dashboard as server
from request_metrics import RequestMetrics
from toss_market import TossError


def handler(monkeypatch):
    metrics = RequestMetrics()
    monkeypatch.setattr(server, 'API_METRICS', metrics)
    instance = object.__new__(server.H)
    instance.wfile = io.BytesIO()
    instance.headers_written = {}
    instance.send_response = lambda status: setattr(instance, 'status', status)
    instance.send_header = lambda k, v: instance.headers_written.update({k: v})
    instance.end_headers = lambda: None
    return instance, metrics


@pytest.mark.parametrize('error,status,upstream', [
    (TossError('rate-limited', 429, retry_after=180), 429, 429),
    (TossError('authentication-failed', 401), 502, 401),
    (TossError('network-or-timeout'), 504, None),
    (ValueError('종목 코드 없음'), 400, None),
])
def test_error_status_and_metrics(monkeypatch, error, status, upstream):
    instance, metrics = handler(monkeypatch)
    def fail(force):
        raise error
    instance.api(fail, 'unused', 'lookup')
    body = json.loads(instance.wfile.getvalue())
    assert instance.status == status
    assert body['upstreamStatus'] == upstream
    if status == 429:
        assert instance.headers_written['Retry-After'] == '180'
        assert body['retryAt'] == error.retry_at
    row = metrics.snapshot()['lookup']
    assert row['failures'] == 1 and row['inFlight'] == 0


def test_diagnostics_read_does_not_authenticate(monkeypatch):
    import toss_market
    instance, metrics = handler(monkeypatch)
    instance.path = '/api/diagnostics'
    monkeypatch.setattr(toss_market.CLIENT, 'token', lambda: pytest.fail('must not authenticate'))
    instance.do_GET()
    assert instance.status == 200
    body = json.loads(instance.wfile.getvalue())
    assert body['scope'] == 'current-process' and 'toss' in body and 'api' in body
    # Phase timings are bounded counters: no symbols, payloads or credentials.
    assert 'perf' in body and isinstance(body['perf'], dict)
    text = instance.wfile.getvalue().decode()
    assert '캔들' not in text and 'candles' not in text


def test_success_cache_hit_count(monkeypatch):
    instance, metrics = handler(monkeypatch)
    instance.api(lambda force: {'cacheHit': True}, 'unused', 'lookup')
    row = metrics.snapshot()['lookup']
    assert row['cacheHits'] == 1 and row['failures'] == 0 and row['statuses'] == {'200': 1}


@pytest.mark.parametrize('path,policy', [
    ('/chart-first.html', 'no-store'),
    ('/chart-api.js?v=1', 'no-cache'),
    ('/lib/lightweight-charts.js', 'no-cache'),
    ('/favicon.ico', None),
])
def test_current_ui_cache_policy(monkeypatch, path, policy):
    instance, _ = handler(monkeypatch)
    instance.path = path
    monkeypatch.setattr(server.SimpleHTTPRequestHandler, 'end_headers', lambda self: None)
    server.H.end_headers(instance)
    assert instance.headers_written.get('Cache-Control') == policy


def test_queue_busy_is_local_503_and_retains_source_time(monkeypatch):
    from request_scheduler import QueueBusy
    instance, metrics = handler(monkeypatch)
    def waiting(force):
        e=QueueBusy();e.last_success_at='2026-09-01T20:00:00+00:00';raise e
    instance.api(waiting,'AAPL','lookup')
    body=json.loads(instance.wfile.getvalue())
    assert instance.status==503 and body['kind']=='queue-busy'
    assert body['upstreamStatus'] is None and body['stale'] is True
    assert body['lastSuccessAt']=='2026-09-01T20:00:00+00:00'
    assert instance.headers_written['Retry-After']=='2'


def test_error_response_does_not_raise_when_browser_already_disconnected(monkeypatch):
    from request_scheduler import QueueBusy
    instance, metrics = handler(monkeypatch)
    class Closed(io.BytesIO):
        def write(self, *args, **kwargs):
            raise BrokenPipeError(32, 'Broken pipe')
    instance.wfile = Closed()
    def waiting(force):
        raise QueueBusy()
    instance.api(waiting,'AAPL','lookup')  # must not escape to socketserver
    row=metrics.snapshot()['lookup']
    assert row['statuses']=={'499':1} and row['lastErrorKind']=='client-disconnected'
    assert instance.close_connection is True


def test_client_disconnect_is_not_printed_as_a_server_error(capsys):
    from local_http import LocalThreadingHTTPServer
    server=object.__new__(LocalThreadingHTTPServer)
    try:
        raise BrokenPipeError(32,'Broken pipe')
    except BrokenPipeError:
        server.handle_error(object(),('127.0.0.1',1))
    assert capsys.readouterr().err==''


def test_market_success_and_errors_do_not_allow_cross_origin_reads(monkeypatch):
    instance, _ = handler(monkeypatch)
    instance.api(lambda force: {'cacheHit': True}, 'unused', 'lookup')
    assert 'Access-Control-Allow-Origin' not in instance.headers_written
    instance, _ = handler(monkeypatch)
    def fail(force):
        raise ValueError('fixture failure')
    instance.api(fail, 'unused', 'lookup')
    assert 'Access-Control-Allow-Origin' not in instance.headers_written


def test_perf_probe_records_phases_without_content(monkeypatch):
    import perf_probe
    perf_probe.reset()
    metric = perf_probe.span('market', 'cache-read')
    with metric:
        pass
    with pytest.raises(RuntimeError):
        with perf_probe.span('patterns', 'flag.compute'):
            raise RuntimeError('DO_NOT_STORE_THIS')
    rows = perf_probe.snapshot()
    assert rows['market.cache-read']['count'] == 1
    assert rows['patterns.flag.compute']['failures'] == 1
    assert 'DO_NOT_STORE_THIS' not in json.dumps(rows)
    perf_probe.reset()
