"""Official calendar boundaries and source-fetch eligibility, with no network."""
from datetime import datetime, date, timedelta
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import time_contract as m


def at(s): return datetime.fromisoformat(s)


@pytest.fixture
def schedule(monkeypatch):
    holidays=set()
    def days(market, query):
        d=date.fromisoformat(query)
        prev=d-timedelta(days=1)
        while prev.weekday()>4 or prev.isoformat() in holidays: prev-=timedelta(days=1)
        nxt=d+timedelta(days=1)
        while nxt.weekday()>4 or nxt.isoformat() in holidays: nxt+=timedelta(days=1)
        offset='+09:00' if market=='KR' else '-04:00'
        return {x.isoformat(): () if x.weekday()>4 or x.isoformat() in holidays else
                ((m._aware(f'{x}T09:00:00{offset}'),m._aware(f'{x}T20:00:00{offset}')),)
                for x in [prev,d,nxt]}
    monkeypatch.setattr(m,'calendar_days',days)
    return holidays


def payload(fetched, times=('2026-09-08','2026-09-09')):
    return {'candles':[{'time':t} for t in times], 'fetchedAt':fetched,'source':'toss'}


def test_daily_entire_session_and_post_close_fetch(schedule):
    p=payload('2026-09-09T15:00:00+09:00')
    before=m.judgment_metadata(p,'005930.KS','Asia/Seoul','D',at('2026-09-09T19:00:00+09:00'))
    assert before['snapshotEligible']
    assert before['lastConfirmedTime']=='2026-09-08'
    assert not before['confirmed']
    # Clock passage alone cannot finalize the candle captured during the session.
    late=m.judgment_metadata(p,'005930.KS','Asia/Seoul','D',at('2026-09-09T20:31:00+09:00'))
    assert late['marketSession']['state']=='closed'
    assert late['lastConfirmedTime']=='2026-09-08'
    p['fetchedAt']='2026-09-09T20:30:00+09:00'
    fresh=m.judgment_metadata(p,'005930.KS','Asia/Seoul','D',at('2026-09-09T20:31:00+09:00'))
    assert fresh['lastConfirmedTime']=='2026-09-09' and fresh['confirmed']
    assert 'confirmed' not in p


def test_open_stale_date_not_snapshot(schedule):
    p=payload('2026-09-09T12:00:00+09:00',('2026-09-08',))
    result=m.judgment_metadata(p,'005930.KS','Asia/Seoul','D',at('2026-09-09T12:00:01+09:00'))
    assert result['marketSession']['state']=='open'
    assert not result['snapshotEligible']


def test_wednesday_closed_selects_previous_week(schedule):
    p=payload('2026-09-09T21:00:00+09:00',('2026-09-04','2026-09-11'))
    p['sourceDate']='2026-09-09'
    result=m.judgment_metadata(p,'005930.KS','Asia/Seoul','W',at('2026-09-09T21:00:01+09:00'))
    assert result['lastConfirmedTime']=='2026-09-04'
    assert not result['confirmed']


def test_friday_holiday_confirms_thursday_after_refresh(schedule):
    schedule.add('2026-09-11')
    p=payload('2026-09-10T20:30:00+09:00',('2026-09-04','2026-09-11'))
    p['sourceDate']='2026-09-10'
    result=m.judgment_metadata(p,'005930.KS','Asia/Seoul','W',at('2026-09-10T20:31:00+09:00'))
    assert result['lastConfirmedTime']=='2026-09-11'


def test_h4_ends_at_session_end_with_buffer(schedule):
    t=int(at('2026-09-09T18:00:00+09:00').timestamp())
    assert not m.bar_confirmed('005930.KS','Asia/Seoul',t,'H4',at('2026-09-09T20:29:59+09:00'))
    assert m.bar_confirmed('005930.KS','Asia/Seoul',t,'H4',at('2026-09-09T20:30:00+09:00'))
    t=int(at('2026-09-09T09:00:00+09:00').timestamp())
    assert m.bar_confirmed('005930.KS','Asia/Seoul',t,'H4',at('2026-09-09T13:30:00+09:00'))


def test_coin_week_label_does_not_close_friday():
    assert not m.bar_confirmed('BTC-USD','UTC','2026-09-11','W',at('2026-09-11T23:59:00+00:00'))
    assert m.bar_confirmed('BTC-USD','UTC','2026-09-11','W',at('2026-09-12T00:30:00+00:00'))


def test_unknown_calendar_and_error_block_confirmation(schedule,monkeypatch):
    p=payload('2026-09-09T21:00:00+09:00')
    p['lastError']='failed'
    assert m.judgment_metadata(p,'005930.KS','Asia/Seoul','D',at('2026-09-09T21:01:00+09:00'))['lastConfirmedTime'] is None
    def fail(*a): raise ValueError('missing')
    monkeypatch.setattr(m,'calendar_days',fail)
    p.pop('lastError')
    result=m.judgment_metadata(p,'005930.KS','Asia/Seoul','D',at('2026-09-09T21:01:00+09:00'))
    assert result['marketSession']['state']=='unknown'
    assert result['lastConfirmedTime'] is None

def test_monthly_label_must_be_month_end(schedule):
    assert not m.bar_confirmed('005930.KS', 'Asia/Seoul', '2026-09-15', 'M',
                               at('2026-10-02T00:00:00+09:00'))
    assert not m.bar_confirmed('BTC-USD', 'UTC', '2026-09-15', 'M',
                               at('2026-10-02T00:00:00+00:00'))


def test_monthly_confirms_after_last_session_plus_buffer(schedule):
    # 2026-09-30(수) 세션 09:00~20:00+09:00 → 임계 20:30.
    assert not m.bar_confirmed('005930.KS', 'Asia/Seoul', '2026-09-30', 'M',
                               at('2026-09-30T20:29:00+09:00'))
    assert m.bar_confirmed('005930.KS', 'Asia/Seoul', '2026-09-30', 'M',
                           at('2026-09-30T20:30:00+09:00'))


def test_month_end_holiday_uses_last_trading_session(schedule):
    # 월말(09-30) 휴장 → 09-29 세션 종료+30분이 임계다.
    schedule.add('2026-09-30')
    assert not m.bar_confirmed('005930.KS', 'Asia/Seoul', '2026-09-30', 'M',
                               at('2026-09-29T20:29:00+09:00'))
    assert m.bar_confirmed('005930.KS', 'Asia/Seoul', '2026-09-30', 'M',
                           at('2026-09-29T20:30:00+09:00'))


def test_coin_month_ends_next_month_first_utc():
    assert not m.bar_confirmed('BTC-USD', 'UTC', '2026-09-30', 'M',
                               at('2026-10-01T00:29:00+00:00'))
    assert m.bar_confirmed('BTC-USD', 'UTC', '2026-09-30', 'M',
                           at('2026-10-01T00:30:00+00:00'))


def test_monthly_judgment_selects_confirmed_month(schedule):
    # 진행 중 9월은 잠정, 판단 기준은 확정된 8월이다. 원천 재조회가 확정 조건이다.
    p = payload('2026-09-30T20:00:00+09:00', ('2026-08-31', '2026-09-30'))
    p['sourceDate'] = '2026-09-30'
    early = m.judgment_metadata(p, '005930.KS', 'Asia/Seoul', 'M',
                                at('2026-09-30T20:31:00+09:00'))
    assert early['lastConfirmedTime'] == '2026-08-31'
    assert not early['confirmed']
    assert early['nextConfirmationAt'] is not None
    p['fetchedAt'] = '2026-09-30T20:30:00+09:00'
    fresh = m.judgment_metadata(p, '005930.KS', 'Asia/Seoul', 'M',
                                at('2026-09-30T20:31:00+09:00'))
    assert fresh['lastConfirmedTime'] == '2026-09-30' and fresh['confirmed']
