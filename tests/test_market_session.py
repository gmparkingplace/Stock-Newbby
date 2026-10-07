from datetime import datetime
import sys
from pathlib import Path
import copy
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import time_contract as m


def day(d, market='KR', hours=None):
    names = ['preMarket', 'regularMarket', 'afterMarket']
    if market == 'US':
        names.insert(0, 'dayMarket')
    sessions = dict.fromkeys(names)
    for name, start, end in hours or []:
        sessions[name] = {'startTime': start, 'endTime': end}
    return {'date': d, **({'integrated': sessions if hours else None} if market == 'KR' else sessions)}


def calendar(today, previous, following):
    return dict(today=today, previousBusinessDay=previous, nextBusinessDay=following)


@pytest.fixture
def provider(monkeypatch):
    m._CALENDAR_CACHE.clear()
    calls = []
    reply = {}
    monkeypatch.setattr(m.toss_market, 'enabled', lambda: True)
    def get(path, **params):
        calls.append((path, params))
        if isinstance(reply.get('error'), Exception):
            raise reply['error']
        return copy.deepcopy(reply['value'])
    monkeypatch.setattr(m.toss_market.CLIENT, 'get', get)
    return reply, calls


def test_kr_after_break_and_next_open(provider):
    reply, calls = provider
    hours = [('regularMarket','2026-09-07T09:00:00+09:00','2026-09-07T15:30:00+09:00'),
             ('afterMarket','2026-09-07T16:00:00+09:00','2026-09-07T20:00:00+09:00')]
    reply['value'] = calendar(day('2026-09-07',hours=hours),day('2026-09-04'),day('2026-09-08',hours=[('regularMarket','2026-09-08T09:00:00+09:00','2026-09-08T20:00:00+09:00')]))
    def state(t): return m.market_session('005930.KS', datetime.fromisoformat('2026-09-07T'+t+'+09:00'))
    assert state('15:29:59')['state'] == 'open'
    assert state('15:30:00')['state'] == 'break'
    assert state('16:00:00')['state'] == 'open'
    closed = state('20:00:00')
    assert closed['state'] == 'closed'
    assert closed['nextTransitionAt'] == '2026-09-08T00:00:00+00:00'
    assert closed['lastSessionEnd'] == '2026-09-07T11:00:00+00:00'
    assert len(calls) == 1
    assert calls[0][1] == {'date':'2026-09-07'}
    reply['value'] = calendar(reply['value']['nextBusinessDay'],reply['value']['today'],day('2026-09-09'))
    assert m.market_session('005930.KS',datetime.fromisoformat('2026-09-08T08:59:59+09:00'))['state']=='closed'
    assert m.market_session('005930.KS',datetime.fromisoformat('2026-09-08T09:00:00+09:00'))['state']=='open'


@pytest.mark.parametrize('month,offset', [('07','-04:00'),('01','-05:00')])
def test_us_cross_midnight_and_local_query(provider, month, offset):
    reply, calls = provider
    previous,today,following=[f'2026-{month}-{d}' for d in ('07','08','09')]
    reply['value'] = calendar(day(today,'US'),day(previous,'US',[
        ('afterMarket',previous+'T20:00:00'+offset,today+'T02:00:00'+offset)]),day(following,'US'))
    # Summer/winter offset determines comparison; query uses New York.
    now = datetime.fromisoformat(today+'T01:00:00'+offset)
    result=m.market_session('AAPL',now)
    assert result['state']=='open'
    assert result['sessionDate']==previous
    assert calls[0][1]['date']==today


def test_early_close_and_friday_holiday(provider):
    reply, _ = provider
    reply['value']=calendar(day('2026-07-03','US'),day('2026-07-02','US',[
        ('regularMarket','2026-07-02T09:30:00-04:00','2026-07-02T13:00:00-04:00')]),day('2026-07-06','US'))
    result=m.market_session('AAPL',datetime.fromisoformat('2026-07-03T12:00:00-04:00'))
    assert result['state']=='closed'
    assert result['lastSessionEnd']=='2026-07-02T17:00:00+00:00'


@pytest.mark.parametrize('bad', ['missing-day','missing-session','naive','reversed'])
def test_bad_calendar_is_unknown(provider,bad):
    reply,_=provider
    value=calendar(day('2026-09-07',hours=[('regularMarket','2026-09-07T09:00:00+09:00','2026-09-07T20:00:00+09:00')]),day('2026-09-04'),day('2026-09-08'))
    if bad=='missing-day': del value['previousBusinessDay']
    elif bad=='missing-session': del value['today']['integrated']['afterMarket']
    elif bad=='naive': value['today']['integrated']['regularMarket']['startTime']='2026-09-07T09:00:00'
    else: value['today']['integrated']['regularMarket']['endTime']='2026-09-07T08:00:00+09:00'
    reply['value']=value
    assert m.market_session('005930.KS',datetime.fromisoformat('2026-09-07T21:00:00+09:00'))['state']=='unknown'


def test_expired_failure_and_unconfigured_never_closed(provider,monkeypatch):
    reply,calls=provider
    reply['value']=calendar(day('2026-09-07'),day('2026-09-04'),day('2026-09-08'))
    clock=[10]
    monkeypatch.setattr(m,'_now',lambda:clock[0])
    now=datetime.fromisoformat('2026-09-07T12:00:00+09:00')
    assert m.market_session('^KS11',now)['state']=='closed'
    clock[0]=71
    reply['error']=m.toss_market.TossError('network-or-timeout')
    assert m.market_session('^KS11',now)['state']=='unknown'
    m._CALENDAR_CACHE.clear()
    monkeypatch.setattr(m.toss_market,'enabled',lambda:False)
    fallback=m.market_session('AAPL',now)
    assert fallback['state']=='closed'  # US Labor Day, using the regular calendar.
    assert fallback['source']=='exchange-calendar' and fallback['scope']=='regular'
    assert m.market_session('BTC-USD',now)['state']=='open'
