"""Stock H4 session continuity and Yahoo analysis regressions."""
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from h4_sessions import annotate, trim_first_session
from exchange_sessions import _calendar
import flag_patterns
import triangle_patterns
import serve_dashboard as server
import toss_market
import market_cache
from market_store import MarketStore
import pattern_service


def candle(stamp):
    return dict(time=int(datetime.fromisoformat(stamp).timestamp()),
                open=100., high=103., low=99., close=102., volume=1000)


@pytest.mark.parametrize('symbol,stamps', [
    ('VOYG', ['2026-07-02T13:30:00-04:00', '2026-07-06T09:30:00-04:00']),
    ('VOYG', ['2025-07-03T09:30:00-04:00', '2025-07-07T09:30:00-04:00']),
    ('VOYG', ['2026-03-06T13:30:00-05:00', '2026-03-09T09:30:00-04:00']),
    ('005930.KS', ['2026-10-08T13:00:00+09:00', '2026-10-12T09:00:00+09:00']),
])
def test_closures_early_close_and_dst_are_not_gaps(symbol, stamps):
    rows = [candle(t) for t in stamps]
    annotate(rows, symbol)
    assert [r['missingBarsBefore'] for r in rows] == [0, 0]


def test_missing_session_or_bucket_is_counted():
    rows = [candle(t) for t in ['2026-10-05T09:30:00-04:00', '2026-10-07T09:30:00-04:00']]
    annotate(rows, 'VOYG')
    assert rows[1]['missingBarsBefore'] == 3
    with pytest.raises(ValueError, match='시작 시각'):
        annotate([candle('2026-10-05T10:00:00-04:00')], 'VOYG')


def stock_rows():
    schedule = _calendar('US').schedule.loc['2026-05-01':'2026-10-06']
    rows = []
    for _, session in schedule.iterrows():
        start = session['open']
        while start < session['close']:
            rows.append(candle(start.isoformat()))
            start += pd.Timedelta(hours=4)
    annotate(rows, 'VOYG')
    return rows


def test_rolling_yahoo_period_start_omits_partial_first_session():
    index = pd.DatetimeIndex(['2026-04-07T11:30:00-04:00', '2026-04-07T15:30:00-04:00',
                              '2026-04-08T09:30:00-04:00', '2026-04-08T13:30:00-04:00'])
    source = pd.DataFrame({'Close': [1, 2, 3, 4]}, index=index)
    clean, warnings = trim_first_session(source, 'VOYG')
    assert clean['Close'].tolist() == [3, 4]
    assert warnings == [dict(code='partial-first-yahoo-session', sessionDate='2026-04-07', excludedSourceBars=2)]
    assert len(source) == 4
    assert trim_first_session(clean, 'VOYG')[1] == []
    assert trim_first_session(source, 'BTC-USD')[1] == []


@pytest.mark.parametrize('engine', [flag_patterns, triangle_patterns])
def test_stock_patterns_keep_history_across_closures_and_restart_after_gap(engine):
    rows = stock_rows()
    out = engine.analyze(rows, 'VOYG', rows[-1]['time'], timeframe='H4')
    assert out['timeline'][-1]['status'] == 'ready'
    assert not out.get('dataWarnings')
    del rows[-10]
    annotate(rows, 'VOYG')
    gap = engine.analyze(rows, 'VOYG', rows[-1]['time'], timeframe='H4')
    assert gap['segmentCount'] == 2
    assert gap['dataWarnings'][0]['missingBars'] == 1
    assert gap['timeline'][-1]['status'] == 'insufficient-data'


@pytest.mark.parametrize('engine,family', [(flag_patterns, 'flag'), (triangle_patterns, 'triangle')])
def test_stock_h4_detects_same_price_patterns_across_sessions(engine, family):
    from flag_fixture import flag_rows
    from triangle_fixture import triangle_rows
    rows = flag_rows('up') if family == 'flag' else triangle_rows('ascending', 'up')
    daily = engine.analyze(rows, 'VOYG', rows[-1]['time'])
    grid = stock_rows()
    for row, stamp in zip(rows, grid):
        row.update(time=stamp['time'], missingBarsBefore=stamp['missingBarsBefore'])
    intraday = engine.analyze(rows, 'VOYG', rows[-1]['time'], timeframe='H4')
    assert intraday['events']
    assert [e['eventType'] for e in intraday['events']] == [e['eventType'] for e in daily['events']]
    assert [r['status'] for r in intraday['timeline']] == [r['status'] for r in daily['timeline']]


def test_yahoo_stock_h4_attaches_patterns_with_session_metadata(monkeypatch, tmp_path):
    rows = stock_rows()
    source = pd.DataFrame(rows).drop(columns='missingBarsBefore')
    source.index = pd.to_datetime(source.pop('time'), unit='s', utc=True)
    source.rename(columns={k: k.capitalize() for k in ['open', 'high', 'low', 'close', 'volume']}, inplace=True)
    monkeypatch.setattr(server.yf, 'Ticker', lambda symbol: SimpleNamespace(history=lambda **kw: source.copy()))
    monkeypatch.setattr(toss_market, 'enabled', lambda: False)
    monkeypatch.setattr(market_cache, 'enabled', lambda: True)
    svc = market_cache.MarketCache(tmp_path / 'h4.sqlite3')
    monkeypatch.setattr(market_cache, 'services', lambda: svc)
    for name in ['enabled', 'flags_enabled', 'triangles_enabled']:
        monkeypatch.setattr(pattern_service, name, lambda: True)
    try:
        payload = server.market_intraday('VOYG', force=True)
        assert payload['source'] == 'yfinance' and payload['tf'] == 'H4'
        assert all(c['missingBarsBefore'] == 0 for c in payload['candles'])
        for name in ['flagAnalysis', 'triangleAnalysis']:
            assert payload[name]['sourceStatus'] == 'ready'
            assert payload[name]['timeline'][-1]['status'] == 'ready'
        assert payload['patternAnalysis']['sourceStatus'] == 'unsupported'
    finally:
        svc.close()
