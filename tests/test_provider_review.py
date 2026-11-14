"""공급처 통신 성공 후 내부 예약 오류가 발생하지 않는지 확인한다."""
from types import SimpleNamespace
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import serve_dashboard as server
import toss_market
import toss_catalog


def test_toss_daily_audit_does_not_fail_successful_collection(monkeypatch):
    rows = [dict(t=str(t.date()), open=100., high=110., low=90., close=105., volume=1000)
            for t in pd.date_range('2026-01-01', periods=140)]
    calls = []
    candles = SimpleNamespace(
        daily=lambda *a, **kw: (rows, False, '2026-11-14T01:21:17+00:00', 'test-revision'),
        needs_audit=lambda *a: True)
    svc = SimpleNamespace(candles=candles)
    monkeypatch.setattr(server, '_provider_choice', lambda tf: 'toss')
    monkeypatch.setattr(server.market_cache, 'enabled', lambda: True)
    monkeypatch.setattr(server.market_cache, 'services', lambda: svc)
    monkeypatch.setattr(toss_market, 'enabled', lambda: True)
    monkeypatch.setattr(toss_market, 'supports', lambda code: True)
    monkeypatch.setattr(toss_catalog, 'resolve', lambda code: code)
    monkeypatch.setattr(toss_market.CLIENT, 'get', lambda *a, **kw: [{'name': '시험 종목'}])
    monkeypatch.setattr(server, 'market_session', lambda code, **kw: {'lastSessionEnd': None})
    monkeypatch.setattr(server, '_with_meta', lambda payload, cache: payload)
    monkeypatch.setattr(server, '_queue_audit', lambda *args: calls.append(args))
    payload = server._market_lookup('SATL')
    assert payload['source'] == 'toss'
    assert payload['candles']
    assert len(calls) == 1
    assert calls[0][2] == 'toss'


def test_disabled_cache_does_not_open_store_for_toss_intraday(monkeypatch):
    import pattern_service
    monkeypatch.setattr(server, '_provider_choice', lambda tf: 'toss')
    monkeypatch.setattr(server.market_cache, 'enabled', lambda: False)
    def forbidden():
        raise AssertionError('비활성 캐시 접근')
    monkeypatch.setattr(server.market_cache, 'services', forbidden)
    monkeypatch.setattr(toss_market, 'enabled', lambda: True)
    monkeypatch.setattr(toss_market, 'supports', lambda code: True)
    monkeypatch.setattr(toss_catalog, 'resolve', lambda code: code)
    calls = []
    def collect(code, tf, force=False):
        calls.append((code, tf, force))
        return {'source': 'toss', 'tf': tf}
    monkeypatch.setattr(server, '_toss_intraday', collect)
    monkeypatch.setattr(pattern_service, 'attach_evidence', lambda payload: payload)
    assert server.market_intraday('AAPL', 'M5', force=True)['tf'] == 'M5'
    assert calls == [('AAPL', 'M5', True)]


def test_audit_uses_collection_lane_not_scheduler(monkeypatch):
    svc = SimpleNamespace(scheduler=SimpleNamespace(),
                          _lane=server.market_cache.MarketCache._lane)
    assert server._audit_lane(svc, 'toss', 'D') == 'toss'
    assert server._audit_lane(svc, 'toss', 'M5') == 'toss:h4'


def test_toss_intraday_yields_on_its_collection_lane(monkeypatch):
    import pattern_service
    calls = []
    scheduler = SimpleNamespace(has_waiting=lambda lane, below: calls.append((lane, below)) or True)
    svc = SimpleNamespace(scheduler=scheduler, _lane=server.market_cache.MarketCache._lane)
    svc.lookup = lambda provider, code, tf, collect, force, **kw: collect(force)
    monkeypatch.setattr(server.market_cache, 'enabled', lambda: True)
    monkeypatch.setattr(server.market_cache, 'services', lambda: svc)
    monkeypatch.setattr(server, '_provider_choice', lambda tf: 'toss')
    monkeypatch.setattr(toss_market, 'enabled', lambda: True)
    monkeypatch.setattr(toss_market, 'supports', lambda code: True)
    monkeypatch.setattr(toss_catalog, 'resolve', lambda code: code)
    def collect(code, tf, force=False, yield_check=None):
        assert yield_check is not None
        assert yield_check() is True
        return dict(source='toss', cacheHit=False, cacheAge=0, stale=False)
    monkeypatch.setattr(server, '_toss_intraday', collect)
    monkeypatch.setattr(server, '_with_meta', lambda payload, meta: payload)
    monkeypatch.setattr(pattern_service, 'attach', lambda payload: payload)
    assert server.market_intraday('AAPL', 'M15')['source'] == 'toss'
    assert calls == [('toss:h4', 2)]


def _vix_frame(values, dates):
    import pandas as pd
    return pd.DataFrame({'Close': values}, index=pd.to_datetime(dates))


def test_market_context_reports_vix_level(monkeypatch):
    frame = _vix_frame([18.0, 19.5, 32.0], ['2026-11-11', '2026-11-12', '2026-11-13'])
    monkeypatch.setattr(server.yf, 'Ticker', lambda code: SimpleNamespace(history=lambda **kw: frame))
    out = server.market_context('AAPL', force=True)
    assert out['available'] is True and out['applicable'] is True
    assert out['value'] == 32.0
    assert out['level'] == 'high'
    assert out['changePercent'] > 60
    assert out['stale'] is False


def test_market_context_failure_does_not_raise(monkeypatch):
    def boom(code):
        raise RuntimeError('provider down')
    monkeypatch.setattr(server.yf, 'Ticker', boom)
    out = server.market_context('MSFT', force=True)
    assert out['available'] is False
    assert out['applicable'] is True


def test_market_context_skips_non_us_market(monkeypatch):
    monkeypatch.setattr(server.yf, 'Ticker', lambda code: (_ for _ in ()).throw(AssertionError('호출 금지')))
    out = server.market_context('005930.KS', force=True)
    assert out['available'] is False
    assert out['applicable'] is False
    assert out['reason'] == 'not-applicable'
