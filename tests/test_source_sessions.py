"""공급처별 세션·확정 계약을 가짜 달력과 클라이언트로 검사한다."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import exchange_sessions
import time_contract as timing
from h4_sessions import annotate


def at(value):
    return datetime.fromisoformat(value)


def window(query):
    day = date.fromisoformat(query)
    previous, following = day - timedelta(days=1), day + timedelta(days=1)
    while previous.weekday() > 4:
        previous -= timedelta(days=1)
    while following.weekday() > 4:
        following += timedelta(days=1)
    return previous, day, following


@pytest.fixture
def calendars(monkeypatch):
    timing._CALENDAR_CACHE.clear()
    calls = {'regular': [], 'toss': []}
    configured = [True]
    failure = [None]

    def regular(market, query):
        calls['regular'].append((market, query))
        offset = '+09:00' if market == 'KR' else '-04:00'
        start, end = ('09:00', '15:30') if market == 'KR' else ('09:30', '16:00')
        return {str(day): () if day.weekday() > 4 else
                ((timing._aware(f'{day}T{start}:00{offset}'),
                  timing._aware(f'{day}T{end}:00{offset}')),)
                for day in window(query)}

    def get(path, **params):
        assert path.startswith('/api/v1/market-calendar/')
        calls['toss'].append((path, params))
        if failure[0]:
            raise failure[0]
        market, query = path.rsplit('/', 1)[-1], params['date']
        offset = '+09:00' if market == 'KR' else '-04:00'
        def day_payload(day):
            sessions = dict(preMarket=None, regularMarket=None, afterMarket=None)
            if market == 'US':
                sessions['dayMarket'] = None
            if day.weekday() < 5:
                sessions['regularMarket'] = dict(startTime=f'{day}T08:00:00{offset}',
                                                endTime=f'{day}T20:00:00{offset}')
            return {'date': str(day), **({'integrated': sessions} if market == 'KR' else sessions)}
        previous, current, following = window(query)
        return dict(today=day_payload(current), previousBusinessDay=day_payload(previous),
                    nextBusinessDay=day_payload(following))

    monkeypatch.setattr(exchange_sessions, 'calendar_days', regular)
    monkeypatch.setattr(timing.toss_market, 'enabled', lambda: configured[0])
    monkeypatch.setattr(timing.toss_market.CLIENT, 'get', get)
    yield calls, configured, failure
    timing._CALENDAR_CACHE.clear()


@pytest.mark.parametrize('source', ['yfinance', 'yahoo', 'exchange-calendar'])
@pytest.mark.parametrize('symbol,stamp', [('005930.KS', '2026-09-09T17:00:00+09:00'),
                                         ('AAPL', '2026-09-09T17:00:00-04:00')])
def test_yahoo_regular_session_does_not_consult_toss(calendars, source, symbol, stamp):
    calls, _, _ = calendars
    session = timing.market_session(symbol, at(stamp), source=source)
    assert session['state'] == 'closed'
    assert session['source'] == 'exchange-calendar' and session['scope'] == 'regular'
    assert len(calls['regular']) == 1 and not calls['toss']


@pytest.mark.parametrize('order', [('toss', 'yfinance'), ('yfinance', 'toss')])
def test_cache_is_separate_for_same_market_date(calendars, order):
    calls, _, _ = calendars
    now = at('2026-09-09T17:00:00+09:00')
    for _ in range(2):
        results = {source: timing.market_session('005930.KS', now, source) for source in order}
        assert results['toss']['state'] == 'open'
        assert results['toss']['scope'] == 'integrated'
        assert results['yfinance']['state'] == 'closed'
    assert len(calls['regular']) == len(calls['toss']) == 1


def test_omitted_source_preserves_legacy_configuration_selection(calendars):
    _, configured, _ = calendars
    now = at('2026-09-09T17:00:00+09:00')
    assert timing.market_session('005930.KS', now)['source'] == 'toss'
    configured[0] = False
    assert timing.market_session('005930.KS', now)['source'] == 'exchange-calendar'


def test_explicit_toss_unconfigured_never_uses_regular_or_old_cache(calendars):
    calls, configured, _ = calendars
    now = at('2026-09-09T17:00:00+09:00')
    assert timing.market_session('005930.KS', now, 'toss')['state'] == 'open'
    configured[0] = False
    result = timing.market_session('005930.KS', now, 'toss')
    assert result['state'] == 'unknown' and result['source'] == 'toss'
    assert not calls['regular'] and len(calls['toss']) == 1
    assert not timing.bar_confirmed('005930.KS', 'Asia/Seoul', '2026-09-09', 'D',
                                    at('2026-09-10T08:00:00+09:00'), source='toss')


def test_failed_toss_never_falls_back_and_yahoo_still_works(calendars):
    calls, _, failure = calendars
    failure[0] = timing.toss_market.TossError('network-or-timeout')
    now = at('2026-09-09T17:00:00+09:00')
    result = timing.market_session('005930.KS', now, source='toss')
    assert result['state'] == 'unknown' and not calls['regular']
    yahoo = timing.market_session('005930.KS', now, source='yfinance')
    assert yahoo['state'] == 'closed'
    assert len(calls['toss']) == 1


@pytest.mark.parametrize('tf,label', [('D', '2026-09-09'), ('W', '2026-09-11'),
                                    ('M', '2026-09-30')])
def test_confirmation_threshold_is_source_specific(calendars, tf, label):
    assert timing.confirmation_at('005930.KS', 'Asia/Seoul', label, tf, 'yfinance') == timing._aware(label + 'T16:00:00+09:00')
    assert timing.confirmation_at('005930.KS', 'Asia/Seoul', label, tf, 'toss') == timing._aware(label + 'T20:30:00+09:00')
    assert not timing.bar_confirmed('005930.KS', 'Asia/Seoul', label, tf,
                                    at(label + 'T15:59:59+09:00'), source='yfinance')
    assert timing.bar_confirmed('005930.KS', 'Asia/Seoul', label, tf,
                                at(label + 'T16:00:00+09:00'), source='yfinance')


@pytest.mark.parametrize('tf,start,regular_end,toss_end', [
    ('H4', '2026-09-09T13:00:00+09:00', '16:00', '17:30'),
    ('M5', '2026-09-09T15:29:00+09:00', '16:00', '16:04'),
])
def test_intraday_clips_to_the_selected_session(calendars, tf, start, regular_end, toss_end):
    stamp = int(at(start).timestamp())
    assert timing.confirmation_at('005930.KS', 'Asia/Seoul', stamp, tf, 'yfinance') == timing._aware('2026-09-09T' + regular_end + ':00+09:00')
    assert timing.confirmation_at('005930.KS', 'Asia/Seoul', stamp, tf, 'toss') == timing._aware('2026-09-09T' + toss_end + ':00+09:00')


def test_metadata_preserves_source_times_and_requires_post_close_fetch(calendars):
    payload = dict(source='yfinance', fetchedAt='2026-09-09T15:59:59+09:00',
                   marketAsOf='2026-09-09', barAsOf=None,
                   candles=[dict(time='2026-09-08'), dict(time='2026-09-09')])
    original = deepcopy(payload)
    now = at('2026-09-09T17:00:00+09:00')
    before = timing.judgment_metadata(payload, '005930.KS', 'Asia/Seoul', 'D', now)
    assert before['lastConfirmedTime'] == '2026-09-08' and not before['confirmed']
    assert before['marketSession']['state'] == 'closed' and not before['snapshotEligible']
    assert payload == original
    fresh = {**payload, 'fetchedAt': '2026-09-09T16:00:00+09:00'}
    after = timing.judgment_metadata(fresh, '005930.KS', 'Asia/Seoul', 'D', now)
    assert after['confirmed'] and after['lastConfirmedTime'] == '2026-09-09'
    for key in ('fetchedAt', 'marketAsOf', 'barAsOf', 'source'):
        assert after[key] == fresh[key]
    toss = timing.judgment_metadata({**fresh, 'source': 'toss'}, '005930.KS', 'Asia/Seoul', 'D', now)
    assert not toss['confirmed'] and toss['marketSession']['state'] == 'open'
    assert toss['nextConfirmationAt'] == '2026-09-09T11:30:00+00:00'


def test_metadata_rejects_reused_session_from_another_source(calendars):
    now = at('2026-09-09T17:00:00+09:00')
    integrated = timing.market_session('005930.KS', now, 'toss')
    payload = dict(source='yfinance', fetchedAt=now.isoformat(), candles=[dict(time='2026-09-09')])
    result = timing.judgment_metadata(payload, '005930.KS', 'Asia/Seoul', 'D', now, integrated)
    assert result['marketSession']['scope'] == 'regular'
    assert result['marketSession']['state'] == 'closed' and result['confirmed']


def test_unknown_explicit_source_is_not_guessed(calendars):
    calls, _, _ = calendars
    now = at('2026-09-09T17:00:00+09:00')
    result = timing.market_session('005930.KS', now, 'auto')
    assert result['state'] == 'unknown' and result['scope'] == 'unknown'
    assert not timing.bar_confirmed('005930.KS', 'Asia/Seoul', '2026-09-09', 'D', now, 'auto')
    assert not calls['regular'] and not calls['toss']


@pytest.mark.parametrize('source', [None, 'toss', 'yfinance'])
def test_coin_utc_contract_never_reads_stock_calendars(calendars, source):
    calls, configured, _ = calendars
    configured[0] = False
    now = at('2026-09-10T00:30:00+00:00')
    result = timing.market_session('BTC-USD', now, source)
    assert result['state'] == 'open' and result['source'] == result['scope'] == 'continuous'
    assert timing.confirmation_at('BTC-USD', 'UTC', '2026-09-09', 'D', source) == now
    assert not calls['regular'] and not calls['toss']


def test_intraday_annotation_uses_explicit_source_grid(calendars):
    calls, _, _ = calendars
    regular = [dict(time=int(at('2026-09-09T' + hour + ':00+09:00').timestamp()))
               for hour in ('09:00', '13:00')]
    integrated = [dict(time=int(at('2026-09-09T' + hour + ':00+09:00').timestamp()))
                  for hour in ('08:00', '12:00', '16:00')]
    annotate(regular, '005930.KS', source='yfinance')
    annotate(integrated, '005930.KS', source='toss')
    assert all(row['missingBarsBefore'] == 0 for row in regular + integrated)
    assert len(calls['regular']) == len(calls['toss']) == 1
    with pytest.raises(ValueError, match='시작 시각'):
        annotate(deepcopy(integrated), '005930.KS', source='yfinance')
    with pytest.raises(ValueError, match='unsupported-session-source'):
        annotate(deepcopy(regular), '005930.KS', source='unknown')
