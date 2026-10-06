"""Provider routing, minute paging, atomic cache and real H4 aggregation offline."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import serve_dashboard as server
import toss_catalog
import toss_market
from minute_collection import MinuteCollection
from market_store import MarketStore, epoch

NOW = datetime(2026, 10, 6, 16, tzinfo=timezone.utc).timestamp()


def row(stamp, close=10, volume=1):
    return dict(timestamp=stamp, openPrice=10, highPrice=12,
                lowPrice=8, closePrice=close, volume=volume)


class PagingClient:
    def __init__(self, rows, size=4):
        self.rows, self.size, self.calls = rows, size, []

    def get(self, path, **params):
        self.calls.append((path, params))
        assert path == '/api/v1/candles'
        assert params['interval'] == '1m' and params['count'] == 200
        assert params['adjusted'] == 'true'
        before = epoch(params['before']) if params.get('before') else float('inf')
        rows = sorted((r for r in self.rows if epoch(r['timestamp']) <= before),
                      key=lambda r: epoch(r['timestamp']), reverse=True)
        page = deepcopy(rows[:self.size])
        cursor = page[-1]['timestamp'] if len(rows) > self.size else None
        return dict(candles=page, nextBefore=cursor)


def sample_rows():
    return [row(f'2026-10-{day:02d}T{hour:02d}:30:00-04:00', close=10+day/10)
            for day in range(1, 7) for hour in (9, 10, 13, 15)]


@pytest.mark.parametrize('shared', [False, True])
@pytest.mark.parametrize('configured,symbol,expected', [
    (True, 'SATL', 'toss'), (True, '005930.KS', 'toss'), (False, 'SATL', 'yfinance'),
    (True, 'BTC', 'yfinance'), (True, '^GSPC', 'yfinance')])
def test_h4_provider_selection(monkeypatch, shared, configured, symbol, expected):
    monkeypatch.setattr(toss_market, 'enabled', lambda: configured)
    monkeypatch.setattr(toss_catalog, 'resolve', lambda code: code)
    monkeypatch.setattr(server.market_cache, 'enabled', lambda: shared)
    monkeypatch.setattr(server, '_with_meta', lambda payload, meta: {**payload, **meta})
    toss = Mock(return_value={'source': 'toss'})
    yahoo = Mock(return_value=({'source': 'yfinance'}, {}))
    monkeypatch.setattr(server, '_toss_intraday', toss)
    monkeypatch.setattr(server, 'intraday', yahoo)
    svc = Mock()
    svc.lookup.side_effect = lambda provider, code, tf, fn, force, background: {
        **fn(force), 'cacheHit': False, 'cacheAge': 0, 'stale': False}
    monkeypatch.setattr(server.market_cache, 'services', lambda: svc)
    assert server.market_intraday(symbol)['source'] == expected
    assert toss.call_count == (expected == 'toss')
    assert yahoo.call_count == (expected == 'yfinance')
    if shared:
        assert svc.lookup.call_args.args[:3] == (expected, 'BTC-USD' if symbol == 'BTC' else symbol, 'H4')


@pytest.mark.parametrize('shared', [False, True])
def test_toss_failure_never_calls_yahoo(monkeypatch, shared):
    monkeypatch.setattr(toss_market, 'enabled', lambda: True)
    monkeypatch.setattr(toss_catalog, 'resolve', lambda code: code)
    monkeypatch.setattr(server, '_toss_intraday', Mock(side_effect=toss_market.TossError('rate-limited', 429)))
    yahoo = Mock(side_effect=AssertionError('unexpected fallback'))
    monkeypatch.setattr(server, 'intraday', yahoo)
    monkeypatch.setattr(server.market_cache, 'enabled', lambda: shared)
    svc = Mock()
    svc.lookup.side_effect = lambda provider, code, tf, fn, force, background: fn(force)
    monkeypatch.setattr(server.market_cache, 'services', lambda: svc)
    with pytest.raises(toss_market.TossError, match='rate-limited'):
        server.market_intraday('SATL')
    yahoo.assert_not_called()


def test_minute_timestamps_survive_same_day_and_timezone_offsets():
    rows = [row('2026-10-06T09:31:00-04:00'), row('2026-10-06T13:30:00Z'),
            row('2026-10-06T22:30:00+09:00')]
    normalized = toss_market.normalize_candles(rows, 'America/New_York', interval='1m')
    assert len(normalized) == 2
    assert normalized[1]['t'] - normalized[0]['t'] == 60
    with pytest.raises(toss_market.TossError, match='invalid-candle'):
        toss_market.normalize_candles([row('2026-10-06T13:30:01Z')], 'UTC', interval='1m')


def test_full_paging_deduplicates_and_drops_oldest_incomplete_day():
    c = MinuteCollection(PagingClient(sample_rows()), clock=lambda: NOW)
    c.TARGET_BARS = 5
    rows, cached, fetched, rev, history = c.minute('SATL', 'America/New_York')
    assert cached is False and history['exhausted'] is False
    assert len(rows) == len({r['t'] for r in rows})
    days = [datetime.fromtimestamp(r['t'], timezone.utc).day for r in rows]
    assert min(days) > 1 and max(days) == 6
    before = len(c.client.calls)
    again = c.minute('SATL', 'America/New_York')
    assert again[1] is True and again[2] == fetched and again[3] == rev
    assert len(c.client.calls) == before


def test_incremental_refresh_updates_current_minute_without_full_backfill():
    now = [NOW]
    client = PagingClient(sample_rows(), size=8)
    c = MinuteCollection(client, clock=lambda: now[0])
    c.TARGET_BARS = 5
    first = c.minute('SATL', 'America/New_York')
    client.calls.clear()
    now[0] += 31
    client.rows[-1]['closePrice'] = 11
    updated = c.minute('SATL', 'America/New_York')
    assert updated[0][-1]['close'] == 11 and updated[3] != first[3]
    assert len(client.calls) == 1
    assert updated[2] != first[2]


def test_failed_backfill_resumes_and_does_not_publish_partial_history(tmp_path):
    store = MarketStore(tmp_path/'minutes.db')
    try:
        client = PagingClient(sample_rows())
        c = MinuteCollection(client, store=store, clock=lambda: NOW)
        c.TARGET_BARS = 8
        original = client.get
        def limited(path, **params):
            if len(client.calls) == 2:
                raise toss_market.TossError('rate-limited', 429)
            return original(path, **params)
        client.get = limited
        with pytest.raises(toss_market.TossError):
            c.minute('SATL', 'America/New_York')
        key = 'candles|SATL|1m|adjusted|America/New_York|v1'
        assert store.get(key) is None
        stage = store.get(key+'|backfill')
        assert stage['pages'] == 2 and stage['rows']
        client.get = original
        restarted = MinuteCollection(client, store=store, clock=lambda: NOW)
        restarted.TARGET_BARS = 8
        count = len(client.calls)
        result = restarted.minute('SATL', 'America/New_York')
        assert client.calls[count][1]['before'] == stage['cursor']
        assert result[0][-1]['t'] == epoch(sample_rows()[-1]['timestamp'])
        assert store.get(key)['dataRevision'] == result[3]
    finally:
        store.close()


def test_repeated_cursor_fails_without_yahoo_or_infinite_paging():
    client = Mock()
    client.get.return_value = dict(candles=[row('2026-10-06T13:30:00Z')],
                                   nextBefore='2026-10-06T13:30:00Z')
    c = MinuteCollection(client, clock=lambda: NOW)
    with pytest.raises(toss_market.TossError, match='history-cursor-repeated'):
        c.minute('SATL', 'America/New_York')
    assert client.get.call_count == 2


def test_adjustment_during_full_collection_cannot_publish_mixed_prices():
    client = PagingClient(sample_rows(), size=8)
    original = client.get
    def changed(path, **params):
        # The final head refresh is newer than the first head page.
        if client.calls and 'before' not in params:
            client.rows[-2]['closePrice'] = 9
        return original(path, **params)
    client.get = changed
    c = MinuteCollection(client, clock=lambda: NOW)
    c.TARGET_BARS = 5
    with pytest.raises(toss_market.TossError, match='adjusted-history-conflict'):
        c.minute('SATL', 'America/New_York')
    key = 'candles|SATL|1m|adjusted|America/New_York|v1'
    assert c._get(key) is None and c._get(key+'|backfill')['rows'] == []


def test_persistent_restart_keeps_source_time_without_source_call(tmp_path):
    store = MarketStore(tmp_path/'minutes.db')
    try:
        client = PagingClient(sample_rows(), size=8)
        c = MinuteCollection(client, store=store, clock=lambda: NOW)
        c.TARGET_BARS = 5
        first = c.minute('SATL', 'America/New_York')
        restarted = MinuteCollection(Mock(), store=store, clock=lambda: NOW+5)
        result = restarted.minute('SATL', 'America/New_York')
        assert result[1] is True and result[2:4] == first[2:4]
        restarted.client.get.assert_not_called()
    finally:
        store.close()


def test_toss_h4_ohlcv_aggregation_and_unready_signals(monkeypatch):
    rows = toss_market.normalize_candles([
        row('2026-10-05T09:30:00-04:00', close=11, volume=3),
        row('2026-10-05T09:31:00-04:00', close=9, volume=4),
        row('2026-10-05T13:30:00-04:00', close=12, volume=5),
        row('2026-10-06T09:30:00-04:00', close=10, volume=6)
    ], 'America/New_York', interval='1m')
    monkeypatch.setattr(toss_market.CANDLES, 'minute',
                        lambda *a, **kw: (rows, False, '2026-10-06T16:00:00Z', 'rev', {}))
    monkeypatch.setattr(server, '_with_meta', lambda payload, meta: payload)
    f = server._toss_intraday('SATL')
    assert f['source'] == 'toss' and f['sourceInterval'] == '1m'
    assert len(f['candles']) == 3
    assert f['candles'][0] == dict(time=epoch('2026-10-05T13:30:00Z'),
                                  open=10, high=12, low=8, close=9, volume=7)
    assert f['candles'][1]['volume'] == 5 and f['candles'][2]['volume'] == 6
    assert f['barAsOf'] is None
    assert f['lines']['sma60'] == []
    assert all(s['sigF'] == 'none' and s['don_hi'] is None for s in f['state'])
