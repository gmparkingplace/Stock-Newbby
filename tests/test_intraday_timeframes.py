"""5m..4h intraday aggregation, session continuity and pattern contracts."""
from datetime import date, datetime, timedelta, timezone
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import intraday_timeframes as tfmod
import time_contract
from h4_sessions import annotate
from signals import to_intraday


def source_frame(start='2026-09-07 09:00', periods=240, tz='Asia/Seoul'):
    idx = pd.date_range(start, periods=periods, freq='1min', tz=tz)
    return pd.DataFrame({'Open': 1, 'High': 2, 'Low': .5, 'Close': 1.5,
                         'Adj Close': 1.5, 'Volume': 10}, index=idx)


@pytest.mark.parametrize('tf,expected', [('M5', 48), ('M15', 16), ('M30', 8),
                                         ('H1', 4), ('H2', 2), ('H4', 1)])
def test_minute_aggregation_counts_and_volume(tf, expected):
    out = to_intraday(source_frame(), 'Asia/Seoul', tfmod.minutes(tf))
    assert len(out) == expected
    assert out['volume'].tolist() == [10 * tfmod.minutes(tf)] * expected
    assert out['t'].is_monotonic_increasing


def test_continuous_aggregation_keeps_utc_day_boundary():
    idx = pd.date_range('2026-09-07 23:50', periods=20, freq='1min', tz='UTC')
    df = pd.DataFrame({'Open': 1, 'High': 2, 'Low': .5, 'Close': 1.5,
                       'Adj Close': 1.5, 'Volume': 1}, index=idx)
    out = to_intraday(df, 'UTC', 30)
    assert len(out) == 2
    labels = [datetime.fromtimestamp(t, timezone.utc).date() for t in out['t']]
    assert labels == [date(2026, 9, 7), date(2026, 9, 8)]


def intraday_rows(step_minutes=5, days=4):
    start = datetime.fromisoformat('2026-09-01T09:00:00+09:00')
    rows, i, day = [], 0, 0
    while len(rows) < days * 78:
        current = start + timedelta(days=day)
        day += 1
        if current.weekday() > 4:
            continue
        for k in range(78):
            price = 100 + math.sin(i / 9) * 2 + i * .01
            rows.append(dict(time=int((current + timedelta(minutes=step_minutes * k)).timestamp()),
                             open=price, high=price + .5, low=price - .5,
                             close=price, volume=1000))
            i += 1
    return rows


def test_five_minute_session_annotation_counts_gaps():
    rows = intraday_rows()
    annotate(rows, '005930.KS', minutes=5)
    assert all(r['missingBarsBefore'] == 0 for r in rows)
    del rows[20]
    annotate(rows, '005930.KS', minutes=5)
    assert rows[20]['missingBarsBefore'] == 1
    assert all(r['missingBarsBefore'] == 0 for i, r in enumerate(rows) if i != 20)


def test_fifteen_minute_requires_session_boundary():
    start = datetime.fromisoformat('2026-09-01T09:00:00+09:00')
    rows = [dict(time=int((start + timedelta(minutes=15 * k)).timestamp()),
                 open=1, high=2, low=.5, close=1, volume=1) for k in range(8)]
    annotate(rows, '005930.KS', minutes=15)
    rows.append(dict(time=int((start + timedelta(minutes=112)).timestamp()),
                     open=1, high=2, low=.5, close=1, volume=1))
    with pytest.raises(ValueError, match='시작 시각'):
        annotate(rows, '005930.KS', minutes=15)


@pytest.fixture
def kr_schedule(monkeypatch):
    def days(market, query, source=None):
        d = date.fromisoformat(query)
        return {x.isoformat(): () if x.weekday() > 4 else
                ((time_contract._aware(f'{x}T09:00:00+09:00'),
                  time_contract._aware(f'{x}T15:30:00+09:00')),)
                for x in (d - timedelta(days=3), d, d + timedelta(days=3))}
    monkeypatch.setattr(time_contract, 'calendar_days', days)


@pytest.mark.parametrize('tf,minutes', [('M5', 5), ('M30', 30), ('H1', 60), ('H2', 120)])
def test_intraday_confirmation_uses_bucket_end_and_buffer(kr_schedule, tf, minutes):
    start = int(datetime.fromisoformat('2026-09-07T09:00:00+09:00').timestamp())
    expected = datetime.fromtimestamp(start + minutes * 60, timezone.utc) + timedelta(minutes=30)
    assert time_contract.confirmation_at('005930.KS', 'Asia/Seoul', start, tf) == expected


def test_h4_confirmation_still_clips_to_session_end(kr_schedule):
    start = int(datetime.fromisoformat('2026-09-07T09:00:00+09:00').timestamp())
    result = time_contract.confirmation_at('005930.KS', 'Asia/Seoul', start, 'H4')
    assert result == time_contract._aware('2026-09-07T13:30:00+09:00')


def test_pattern_rules_accept_new_timeframes():
    import horizontal_patterns
    import flag_patterns
    import triangle_patterns
    import structure_patterns
    import pattern_profiles
    for tf in ('M5', 'M15', 'M30', 'H1', 'H2'):
        assert pattern_profiles.rule_version('flag', tf) == f'flag-{tf.lower()}-v2'
        assert horizontal_patterns.rule_version(tf) == f'horizontal-{tf.lower()}-v1'
    rows = intraday_rows()
    annotate(rows, '005930.KS', minutes=5)
    for engine in (flag_patterns, triangle_patterns, structure_patterns, horizontal_patterns):
        out = engine.analyze(rows, '005930.KS', rows[-1]['time'], timeframe='M5')
        assert out['ruleVersion'].endswith('m5-v2') or out['ruleVersion'].endswith('m5-v1')
        assert out['timeline'][-1]['status'] == 'ready'


def test_pattern_service_support_and_validation():
    import pattern_service
    assert pattern_service.supported('005930.KS', 'M5', 'flag')
    assert pattern_service.supported('BTC-USD', 'H1', 'triangle')
    assert not pattern_service.supported('BTC-USD', 'H1', 'horizontal')
    assert not pattern_service.supported('^KS11', 'M5', 'flag')
    assert pattern_service.valid_timeframe('D')
    assert pattern_service.valid_timeframe('M30')
    assert not pattern_service.valid_timeframe('W')
    assert not pattern_service.valid_timeframe('H3')


def test_market_intraday_rejects_unknown_timeframe():
    import serve_dashboard as server
    with pytest.raises(ValueError, match='unsupported-intraday-timeframe'):
        server.market_intraday('005930.KS', 'H3')


def test_pattern_service_publishes_m5_results(tmp_path):
    from datetime import datetime, timezone
    from market_store import MarketStore, revision
    import pattern_service
    rows = intraday_rows()
    annotate(rows, '005930.KS', minutes=5)
    payload = dict(symbol='005930.KS', name='삼성전자', tf='M5', candles=rows,
                   fetchedAt=datetime.now(timezone.utc).isoformat(),
                   dataRevision=revision(rows), confirmed=True,
                   lastConfirmedTime=rows[-1]['time'], nextConfirmationAt=None,
                   confirmedPolicy='market-calendar',
                   marketSession={'state': 'closed'}, source='toss')
    store = MarketStore(tmp_path / 'm5.sqlite3')
    try:
        for family, version in (('horizontal', 'horizontal-m5-v1'),
                                ('flag', 'flag-m5-v2'),
                                ('triangle', 'triangle-m5-v2'),
                                ('structure', 'structure-m5-v2')):
            out = pattern_service.evaluate(payload, store, family=family)
            assert out['sourceStatus'] == 'ready', (family, out)
            assert out['ruleVersion'] == version
            assert out['timeline'][-1]['status'] == 'ready'
            assert out['timeframe'] == 'M5'
    finally:
        store.close()
