"""Keyless session/confirmation and malformed Yahoo history regressions."""
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import time_contract as timing
import serve_dashboard as server
import toss_market
import market_cache
from pattern_math import validated
from yahoo_quality import latest_valid_segment


@pytest.fixture
def keyless(monkeypatch):
    timing._CALENDAR_CACHE.clear()
    monkeypatch.setattr(toss_market, 'enabled', lambda: False)
    def forbidden(*a, **kw):
        raise AssertionError('keyless lookup reached Toss')
    monkeypatch.setattr(toss_market.CLIENT, 'get', forbidden)
    yield
    timing._CALENDAR_CACHE.clear()


@pytest.mark.parametrize('symbol,stamp,state,session_date', [
    ('005930.KS', '2026-10-07T09:00:00+09:00', 'open', '2026-10-07'),
    ('005930.KS', '2026-10-07T15:30:00+09:00', 'closed', '2026-10-07'),
    ('005930.KS', '2026-10-09T12:00:00+09:00', 'closed', '2026-10-08'),
    ('AAPL', '2026-07-03T12:00:00-04:00', 'closed', '2026-07-02'),
    ('AAPL', '2025-07-03T13:00:00-04:00', 'closed', '2025-07-03'),
    ('AAPL', '2026-01-08T09:30:00-05:00', 'open', '2026-01-08'),
    ('AAPL', '2026-07-08T09:30:00-04:00', 'open', '2026-07-08'),
])
def test_keyless_sessions(keyless, symbol, stamp, state, session_date):
    session = timing.market_session(symbol, datetime.fromisoformat(stamp))
    assert session['state'] == state and session['sessionDate'] == session_date
    assert session['source'] == 'exchange-calendar' and session['scope'] == 'regular'


def test_keyless_daily_confirmation_requires_post_close_fetch(keyless):
    p = dict(source='yfinance', fetchedAt='2026-10-07T15:20:00+09:00',
             candles=[dict(time=t) for t in ['2026-10-06', '2026-10-07']])
    now = datetime.fromisoformat('2026-10-07T16:01:00+09:00')
    before = timing.judgment_metadata(p, '005930.KS', 'Asia/Seoul', 'D', now)
    assert before['lastConfirmedTime'] == '2026-10-06' and not before['confirmed']
    p['fetchedAt'] = '2026-10-07T16:00:00+09:00'
    after = timing.judgment_metadata(p, '005930.KS', 'Asia/Seoul', 'D', now)
    assert after['confirmed'] and after['lastConfirmedTime'] == '2026-10-07'


def test_keyless_calendar_failure_stays_unknown(keyless, monkeypatch):
    import exchange_sessions
    def fail(*a):
        raise ValueError('exchange-calendar-unavailable')
    monkeypatch.setattr(exchange_sessions, 'calendar_days', fail)
    assert timing.market_session('AAPL')['state'] == 'unknown'


def data(count=140):
    return pd.DataFrame(dict(t=pd.date_range('2026-01-01', periods=count).strftime('%Y-%m-%d'),
                             open=100., high=110., low=90., close=105., volume=1000))


def test_bad_old_candle_restarts_indicators_without_fabrication():
    source = data()
    source.loc[10, 'low'] = 106.  # Close below the source low.
    clean, warnings = latest_valid_segment(source)
    pd.testing.assert_frame_equal(clean, source.iloc[11:].reset_index(drop=True))
    assert source.loc[10, 'low'] == 106.
    assert warnings[0]['invalidTimes'] == ['2026-01-11']
    assert warnings[0]['excludedHistoryBars'] == 11
    candles = clean.rename(columns={'t': 'time'}).to_dict('records')
    validated(candles, candles[-1]['time'])


@pytest.mark.parametrize('index,field,value', [(139, 'low', 106.), (100, 'high', 1.), (10, 'volume', float('nan'))])
def test_recent_errors_fail_or_disclose_gap(index, field, value):
    source = data()
    source.loc[index, field] = value
    if index >= 100:
        with pytest.raises(ValueError, match='정상 자료 부족'):
            latest_valid_segment(source)
    else:
        clean, warnings = latest_valid_segment(source)
        assert clean.iloc[0]['t'] == '2026-01-12' and warnings[0]['count'] == 1


def test_yahoo_lookup_uses_clean_segment_for_all_timeframes(keyless, monkeypatch):
    source = data().rename(columns={k: k.capitalize() for k in ['open', 'high', 'low', 'close', 'volume']})
    source['Adj Close'] = source['Close']
    source.index = pd.DatetimeIndex(source.pop('t')).tz_localize('Asia/Seoul')
    source.iloc[10, source.columns.get_loc('Low')] = 106.
    monkeypatch.setattr(server.yf, 'Ticker', lambda symbol: SimpleNamespace(history=lambda **kw: source.copy()))
    monkeypatch.setattr(market_cache, 'enabled', lambda: False)
    payload = server.market_lookup('005930.KS', force=True)
    assert payload['source'] == 'yfinance'
    assert payload['candles'][0]['time'] == '2026-01-12'
    assert len(payload['lines']['sma60']) == len(payload['candles']) - 59
    for name in ['weekly', 'monthly']:
        assert payload[name]['dataWarnings'] == payload['dataWarnings']
    assert payload['marketSession']['source'] == 'exchange-calendar'
