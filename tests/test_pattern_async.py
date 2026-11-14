"""개인 설정·공급처·개인 DB 없이 비동기 패턴 계약을 검사한다."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pattern_async as async_patterns
import pattern_service


def payload(**changes):
    return dict(symbol='AAPL', tf='D', source='yfinance', dataRevision='r1', snapshotId='s1',
                fetchedAt='2026-11-14T00:00:00+00:00', snapshotEligible=True,
                lastConfirmedTime='2026-11-13', marketSession={'state': 'closed'},
                candles=[dict(time='2026-11-13', open=10, high=12, low=9, close=11, volume=50)],
                **changes)


def context(data):
    return dict(features=(('patternAnalysis', 'horizontal'),), shared=True,
                store=None, levels={'version': 1})


def ready(data):
    return dict(data, patternAnalysis=dict(enabled=True, sourceStatus='ready',
                                          timeline=[data['dataRevision']], candles=deepcopy(data['candles'])))


def test_submit_is_nonblocking_deduplicated_and_snapshot_isolated():
    entered, release = Event(), Event()
    seen = []
    def calculate(data):
        entered.set()
        assert release.wait(3)
        seen.append(deepcopy(data))
        data['candles'][0]['close'] = 123
        return ready(data)
    jobs = async_patterns.AsyncPatterns(calculate, context_fn=context)
    data = payload()
    original = deepcopy(data)
    try:
        one = jobs.attach(data)
        assert entered.wait(2)
        two = jobs.attach(deepcopy(data))
        ident = one['patternJob']['id']
        assert two['patternJob']['id'] == ident
        assert data == original
        assert one['patternAnalysis']['sourceStatus'] == 'computing'
        assert one['patternAnalysis']['sourceFetchedAt'] == data['fetchedAt']
        assert one['patternJob'] == dict(id=ident, state='pending', retryAfterMs=300)
        assert 'fields' not in jobs.get(ident)
        assert jobs.get(ident)['identity'] == dict(symbol='AAPL', timeframe='D', source='yfinance',
            dataRevision='r1', snapshotId='s1', fetchedAt=data['fetchedAt'])
        data['candles'][0]['close'] = 19
        release.set()
        jobs.queue.join()
        result = jobs.get(ident)
        assert len(seen) == 1 and seen[0] == original
        assert original['candles'][0]['close'] == 11
        assert result['state'] == 'ready' and result['fields']['patternAnalysis']['timeline'] == ['r1']
        result['fields']['patternAnalysis']['timeline'].append('changed')
        assert jobs.get(ident)['fields']['patternAnalysis']['timeline'] == ['r1']
        again = jobs.attach(original)
        assert again['patternJob']['state'] == 'ready'
        assert again['patternAnalysis']['sourceStatus'] == 'ready'
    finally:
        release.set()
        jobs.shutdown()


@pytest.mark.parametrize('change', [
    {'dataRevision': 'r2'}, {'snapshotId': 's2'}, {'fetchedAt': '2026-11-14T00:01:00Z'},
    {'source': 'toss'}, {'stale': True}, {'snapshotEligible': False},
    {'lastConfirmedTime': None}, {'lastError': 'failure'},
    {'candles': [dict(time='2026-11-13', open=10, high=12, low=9, close=10, volume=50)]},
])
def test_immutable_input_change_uses_new_ticket(change):
    jobs = async_patterns.AsyncPatterns(ready, context_fn=context)
    try:
        one = jobs.attach(payload())
        two = jobs.attach(dict(payload(), **change))
        assert one['patternJob']['id'] != two['patternJob']['id']
        jobs.queue.join()
    finally:
        jobs.shutdown()


def test_levels_features_and_source_freshness_are_part_of_identity():
    settings = context(None)
    now = [datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc).timestamp()]
    jobs = async_patterns.AsyncPatterns(ready, context_fn=lambda _: deepcopy(settings), clock=lambda: now[0])
    try:
        one = jobs.attach(payload())['patternJob']['id']
        settings['levels']['version'] = 2
        two = jobs.attach(payload())['patternJob']['id']
        settings['features'] = (('patternAnalysis', 'horizontal'), ('structureAnalysis', 'structure'))
        three = jobs.attach(payload())['patternJob']['id']
        now[0] += 91
        four = jobs.attach(payload())['patternJob']['id']
        assert len({one, two, three, four}) == 4
        jobs.queue.join()
    finally:
        jobs.shutdown()


def test_queue_full_is_explicit_and_never_evicts_pending():
    entered, release = Event(), Event()
    calls = []
    def calculate(data):
        calls.append(data['dataRevision'])
        entered.set()
        assert release.wait(3)
        return ready(data)
    jobs = async_patterns.AsyncPatterns(calculate, context_fn=context, max_queue=1, max_jobs=2)
    try:
        one = jobs.attach(payload())
        assert entered.wait(2)
        two = jobs.attach(dict(payload(), dataRevision='r2'))
        busy = jobs.attach(dict(payload(), dataRevision='r3'))
        assert busy['patternJob']['state'] == 'error'
        assert busy['patternJob']['error']['kind'] == 'busy'
        assert busy['patternAnalysis']['sourceStatus'] == 'error'
        assert 'timeline' not in busy['patternAnalysis']
        assert jobs.get(busy['patternJob']['id']) is None
        assert jobs.get(one['patternJob']['id'])['state'] == 'pending'
        assert jobs.get(two['patternJob']['id'])['state'] == 'pending'
        assert len(jobs.jobs) == 2
        release.set()
        jobs.queue.join()
        assert calls == ['r1', 'r2']
    finally:
        release.set()
        jobs.shutdown()


def test_ttl_and_lru_only_evict_finished_tickets():
    now = [0]
    jobs = async_patterns.AsyncPatterns(ready, context_fn=context, clock=lambda: now[0], max_jobs=2, ttl=10)
    try:
        one = jobs.attach(payload())['patternJob']['id']
        two = jobs.attach(dict(payload(), dataRevision='r2'))['patternJob']['id']
        jobs.queue.join()
        jobs.get(one)  # one을 최근 사용 항목으로 옮긴다.
        three = jobs.attach(dict(payload(), dataRevision='r3'))['patternJob']['id']
        jobs.queue.join()
        assert jobs.get(two) is None
        assert jobs.get(one)['state'] == jobs.get(three)['state'] == 'ready'
        now[0] = 10
        assert jobs.get(one) is None and jobs.get(three) is None
    finally:
        jobs.shutdown()


@pytest.mark.parametrize('failure', ['raise', 'field'])
def test_failure_has_no_fields_or_old_timeline(failure):
    def calculate(data):
        if failure == 'raise':
            raise RuntimeError('개인 정보가 포함될 수 있는 메시지')
        return dict(data, patternAnalysis=dict(sourceStatus='error', timeline=['old']))
    jobs = async_patterns.AsyncPatterns(calculate, context_fn=context)
    try:
        ident = jobs.attach(payload())['patternJob']['id']
        jobs.queue.join()
        result = jobs.get(ident)
        assert result['state'] == 'error' and 'fields' not in result
        assert result['error'] == {'kind': 'calculation-error'}
        output = jobs.attach(payload())
        assert output['patternAnalysis']['sourceStatus'] == 'error'
        assert 'timeline' not in output['patternAnalysis']
    finally:
        jobs.shutdown()


def test_shutdown_marks_queued_jobs_and_rejects_new_work():
    entered, release = Event(), Event()
    def calculate(data):
        entered.set()
        assert release.wait(3)
        return ready(data)
    jobs = async_patterns.AsyncPatterns(calculate, context_fn=context)
    try:
        one = jobs.attach(payload())['patternJob']['id']
        assert entered.wait(2)
        two = jobs.attach(dict(payload(), dataRevision='r2'))['patternJob']['id']
        jobs.shutdown(wait=False)
        assert jobs.get(two)['error']['kind'] == 'closed'
        assert jobs.attach(dict(payload(), dataRevision='r3'))['patternJob']['error']['kind'] == 'closed'
        release.set()
        jobs.shutdown()
        assert jobs.get(one)['state'] == 'ready'
    finally:
        release.set()
        jobs.shutdown()


class Handler:
    def __init__(self, path, command='GET', **headers):
        self.path, self.command = path, command
        self.headers = dict(Host='127.0.0.1:8735', **headers)
        self.server = SimpleNamespace(server_port=8735)
        self.wfile = BytesIO()
        self.reply_headers = {}
    def send_response(self, status):
        self.status = status
    def send_header(self, key, value):
        self.reply_headers[key] = value
    def end_headers(self):
        pass


def test_http_job_reads_use_existing_origin_guard_and_never_collect(monkeypatch):
    jobs = async_patterns.AsyncPatterns(ready, context_fn=context)
    monkeypatch.setattr(async_patterns, 'JOBS', jobs)
    monkeypatch.setattr(async_patterns.market_cache, 'services', lambda: pytest.fail('자료 수집 금지'))
    try:
        ident = jobs.attach(payload())['patternJob']['id']
        jobs.queue.join()
        handler = Handler('/api/pattern-jobs?id=' + ident)
        assert async_patterns.handle(handler)
        assert handler.status == 200 and json.loads(handler.wfile.getvalue())['state'] == 'ready'
        assert handler.reply_headers['Cache-Control'] == 'no-store'
        assert 'Access-Control-Allow-Origin' not in handler.reply_headers
        for path, expected in [('/api/pattern-jobs', 400), ('/api/pattern-jobs?id=', 400),
            ('/api/pattern-jobs?id=bad', 400), ('/api/pattern-jobs?id=' + 'f' * 32, 404),
            ('/api/pattern-jobs?id=' + ident + '&id=' + ident, 400)]:
            handler = Handler(path)
            assert async_patterns.handle(handler) and handler.status == expected
        for headers in ({'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            handler = Handler('/api/pattern-jobs?id=' + ident, **headers)
            assert async_patterns.handle(handler) and handler.status == 403
        handler = Handler('/api/pattern-jobs?id=' + ident, command='POST')
        assert async_patterns.handle(handler) and handler.status == 405
    finally:
        jobs.shutdown()


def test_disabled_unsupported_never_starts_worker(monkeypatch):
    for gate in ('enabled', 'flags_enabled', 'triangles_enabled', 'structures_enabled', 'structure_evidence_v2_enabled'):
        monkeypatch.setattr(pattern_service, gate, lambda: False)
    monkeypatch.setattr(async_patterns.market_cache, 'enabled', lambda: False)
    monkeypatch.setattr(async_patterns.market_cache, 'services', lambda: pytest.fail('저장소 불필요'))
    jobs = async_patterns.AsyncPatterns(lambda _: pytest.fail('계산 불필요'))
    try:
        data = payload()
        assert jobs.attach(data) is data
        monkeypatch.setattr(pattern_service, 'enabled', lambda: True)
        output = jobs.attach(data)
        assert output['patternAnalysis']['sourceStatus'] == 'shared-cache-disabled'
        monkeypatch.setattr(pattern_service, 'enabled', lambda: False)
        monkeypatch.setattr(pattern_service, 'structure_evidence_v2_enabled', lambda: True)
        output = jobs.attach(dict(data, symbol='BTC-USD'))
        assert output['structureEvidenceV2']['sourceStatus'] == 'unsupported'
        assert jobs.worker is None and not jobs.jobs
    finally:
        jobs.shutdown()


def test_evidence_runs_async_without_shared_store(monkeypatch):
    for _, _, gate in async_patterns.FAMILIES:
        monkeypatch.setattr(pattern_service, gate, lambda: False)
    monkeypatch.setattr(pattern_service, 'structure_evidence_v2_enabled', lambda: True)
    monkeypatch.setattr(async_patterns.market_cache, 'enabled', lambda: False)
    monkeypatch.setattr(async_patterns.market_cache, 'services', lambda: pytest.fail('저장소 불필요'))
    monkeypatch.setattr(pattern_service, 'evaluate_structure_evidence', lambda p: dict(sourceStatus='ready', symbol=p['symbol']))
    jobs = async_patterns.AsyncPatterns()
    try:
        output = jobs.attach(payload())
        assert output['structureEvidenceV2']['sourceStatus'] == 'computing'
        jobs.queue.join()
        assert jobs.get(output['patternJob']['id'])['fields']['structureEvidenceV2']['symbol'] == 'AAPL'
    finally:
        jobs.shutdown()


def test_frozen_levels_reuse_existing_compute_cache(tmp_path, monkeypatch):
    from market_store import MarketStore
    from test_horizontal_patterns import bars, payload as source_payload
    store = MarketStore(tmp_path / 'patterns.sqlite3')
    for _, _, gate in async_patterns.FAMILIES:
        monkeypatch.setattr(pattern_service, gate, lambda: False)
    monkeypatch.setattr(pattern_service, 'enabled', lambda: True)
    monkeypatch.setattr(async_patterns.market_cache, 'enabled', lambda: True)
    monkeypatch.setattr(async_patterns.market_cache, 'services', lambda: SimpleNamespace(store=store))
    seen = []
    analyze = pattern_service.analyze
    def spy(*a, **kw):
        seen.append(deepcopy(a[4]))
        return analyze(*a, **kw)
    monkeypatch.setattr(pattern_service, 'analyze', spy)
    try:
        data = source_payload(bars(80))
        # 콜백이 실행되기 전 저장 설정을 바꾸더라도 제출 당시 설정을 써야 한다.
        captured = async_patterns._context(data)
        store.put(pattern_service.settings_key(data['symbol']),
                  {'levels': {'support': 25}, 'dataRevision': 'settings-2'})
        async_patterns._attach_frozen(deepcopy(data), captured)
        async_patterns._attach_frozen(deepcopy(data), captured)
        assert len(seen) == 1
        assert seen[0] == captured['levels']
        later = async_patterns._context(data)
        assert later['levels'] != captured['levels']
    finally:
        store.close()


def test_http_defer_optional_keeps_direct_sync_calls(monkeypatch):
    import serve_dashboard as server
    monkeypatch.setattr(server.market_cache, 'enabled', lambda: False)
    monkeypatch.setattr(server, '_market_lookup', lambda code, force=False: payload())
    monkeypatch.setattr(server, 'intraday', lambda code, tf: dict(payload(), tf=tf))
    monkeypatch.setattr(server, '_with_meta', lambda data, meta: data)
    monkeypatch.setattr(server, '_provider_choice', lambda tf: 'yfinance')
    monkeypatch.setattr(pattern_service, 'attach_evidence', lambda data: dict(data, sync=True))
    monkeypatch.setattr(async_patterns, 'attach', lambda data: dict(data, deferred=True))
    assert server.market_lookup('AAPL')['sync']
    assert server.market_lookup('AAPL', defer_patterns=True)['deferred']
    assert server.market_intraday('AAPL')['sync']
    assert server.market_intraday('AAPL', defer_patterns=True)['deferred']
    output = []
    handler = SimpleNamespace(path='/api/lookup?code=AAPL',
        api=lambda fn, *a: output.append(fn(False)))
    monkeypatch.setattr(server, 'market_lookup', lambda code, **kw: kw)
    import analysis_jobs, monitor_service
    monkeypatch.setattr(analysis_jobs, 'handle', lambda _: False)
    monkeypatch.setattr(monitor_service, 'handle', lambda _: False)
    monkeypatch.setattr(pattern_service, 'handle', lambda _: False)
    server.H.do_GET(handler)
    assert output[-1]['defer_patterns'] is True
    handler.path = '/api/intraday?code=AAPL&tf=M5'
    monkeypatch.setattr(server, 'market_intraday', lambda code, tf, **kw: dict(kw, tf=tf))
    server.H.do_GET(handler)
    assert output[-1]['defer_patterns'] is True and output[-1]['tf'] == 'M5'
