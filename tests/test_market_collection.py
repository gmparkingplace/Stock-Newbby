"""P1 offline concurrency/storage/REST-count contracts. No credentials or sockets."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import sys
from threading import Event, Lock
from time import monotonic
from unittest.mock import Mock

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from candle_collection import CandleCollection
from market_cache import MarketCache
from market_store import MarketStore, epoch, revision
from provider_budget import ProviderBudget
from request_scheduler import RequestScheduler, QueueBusy
from toss_market import TossClient, TossError

NOW = datetime(2026,9,1,20,tzinfo=timezone.utc).timestamp()


def payload(stamp=NOW):
    return {'symbol':'AAPL','fetchedAt':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
            'candles':[dict(time='2026-09-01',open=100,high=110,low=90,close=105,volume=100)],
            'weekly':{'candles':[]},'monthly':{'candles':[]}}


def test_same_job_merged_and_one_collection_per_provider():
    scheduler=RequestScheduler(wait_seconds=2)
    entered,release=Event(),Event()
    calls=[]
    def collect():
        calls.append(1);entered.set();assert release.wait(1);return {'x':[1]}
    try:
        with ThreadPoolExecutor(4) as pool:
            first=pool.submit(scheduler.execute,'AAPL','toss',collect)
            assert entered.wait(1)
            second=pool.submit(scheduler.execute,'AAPL','toss',collect)
            third=pool.submit(scheduler.execute,'MSFT','toss',lambda: calls.append(2) or {'x':[2]})
            # A second provider remains independent.
            other=pool.submit(scheduler.execute,'BTC','yfinance',lambda:{'x':[3]})
            assert other.result(timeout=1)['x']==[3]
            assert calls==[1]
            release.set()
            a,b=first.result(),second.result()
            a['x'].append(9);assert b=={'x':[1]}
            assert third.result()['x']==[2]
            assert calls==[1,2]
            assert scheduler.snapshot()['merged']==1
    finally:
        release.set();scheduler.close()


def test_waiter_timeout_does_not_cancel_shared_collection():
    scheduler=RequestScheduler(wait_seconds=.03)
    entered,release=Event(),Event()
    def collect():
        entered.set();assert release.wait(1);return 5
    try:
        with pytest.raises(QueueBusy):scheduler.execute('one','toss',collect)
        assert entered.is_set()
        release.set()
        # Synchronize completion through the existing future rather than polling.
        with scheduler.cv: future=scheduler.flights.get('one')
        if future: assert future.result(timeout=1)==5
    finally:
        release.set();scheduler.close()


def test_cache_restart_original_time_revision_and_force_budget(tmp_path):
    now=[NOW];path=tmp_path/'cache.db'
    c=MarketCache(path,clock=lambda:now[0]);calls=[]
    def fetch(force):calls.append(force);return payload(now[0])
    first=c.lookup('toss','AAPL','D',fetch)
    now[0]+=5
    second=c.lookup('toss','AAPL','D',fetch,force=True)
    assert len(calls)==1 and second['fetchedAt']==first['fetchedAt']
    assert second['snapshotId']==first['snapshotId']
    assert first['weekly']['dataRevision']==first['monthly']['dataRevision']==first['dataRevision']
    c.close()
    c=MarketCache(path,clock=lambda:now[0])
    try:
        cached=c.lookup('toss','AAPL','D',fetch)
        assert cached['cacheHit'] and cached['cacheAge']==5
        assert cached['fetchedAt']==first['fetchedAt'] and len(calls)==1
        now[0]+=26
        fresh=c.lookup('toss','AAPL','D',fetch)
        assert len(calls)==2 and fresh['fetchedAt']!=first['fetchedAt']
        assert fresh['dataRevision']==first['dataRevision']
    finally:c.close()


def test_error_preserves_last_success_without_serving_it_as_fresh(tmp_path):
    now=[NOW];c=MarketCache(tmp_path/'cache.db',clock=lambda:now[0])
    try:
        good=c.lookup('toss','AAPL','D',lambda f:payload())
        now[0]+=31
        def fail(force):raise TossError('rate-limited',429,retry_after=180)
        with pytest.raises(TossError) as e:c.lookup('toss','AAPL','D',fail,force=True)
        assert e.value.last_success_at==good['fetchedAt']
        saved=c.store.get(c.key('toss','AAPL','D'))
        assert saved['fetchedAt']==good['fetchedAt'] and saved['snapshotId']==good['snapshotId']
    finally:c.close()


class Pager:
    def __init__(self):
        start=datetime(2026,9,1,14,tzinfo=timezone.utc)
        self.rows=[dict(timestamp=(start-timedelta(days=i)).isoformat(),openPrice=100,highPrice=110,lowPrice=90,closePrice=105,volume=100) for i in range(800)]
        self.calls=[]
    def get(self,path,**params):
        self.calls.append(params)
        rows=[r for r in self.rows if not params.get('before') or r['timestamp']<=params['before']]
        page=rows[:params['count']]
        return {'candles':deepcopy(page),'nextBefore':page[-1]['timestamp'] if len(rows)>len(page) else None}


def test_recent_30_merge_and_restart_preserve_volume_without_sum(tmp_path):
    now=[NOW];p=Pager();path=tmp_path/'cache.db';store=MarketStore(path)
    collector=CandleCollection(p,store,clock=lambda:now[0])
    old=collector.daily('AAPL','America/New_York')
    assert len(p.calls)==4 and len(old[0])>=797
    now[0]+=31;p.rows[0]['volume']=150
    new=collector.daily('AAPL','America/New_York')
    assert len(p.calls)==5 and p.calls[-1]['count']==30
    assert new[0][-1]['volume']==150 and new[0][:-1]==old[0][:-1]
    assert new[3]!=old[3]
    store.close();store=MarketStore(path)
    try:
        restored=CandleCollection(p,store,clock=lambda:now[0]).daily('AAPL','America/New_York')
        assert restored[1] is True and restored[2]==new[2] and len(p.calls)==5
    finally:store.close()


def test_historical_correction_replaces_whole_revision_atomically(tmp_path):
    now=[NOW];p=Pager();store=MarketStore(tmp_path/'cache.db')
    try:
        collector=CandleCollection(p,store,clock=lambda:now[0])
        old=collector.daily('AAPL','America/New_York')
        for row in p.rows:
            for field in ('openPrice','highPrice','lowPrice','closePrice'):row[field]/=2
        now[0]+=31
        new=collector.daily('AAPL','America/New_York')
        assert len(p.calls)==9 and p.calls[4]['count']==30
        assert all(r['close']==52.5 for r in new[0]) and new[3]!=old[3]
        assert len(new[0])==len(old[0])
    finally:store.close()


def test_gap_triggers_full_and_failed_reconcile_leaves_old_revision(tmp_path):
    now=[NOW];p=Pager();store=MarketStore(tmp_path/'cache.db');c=CandleCollection(p,store,clock=lambda:now[0])
    try:
        old=c.daily('AAPL','America/New_York')
        # New 30-bar window shares no dates with the previous history.
        p.rows=[dict(r,timestamp=(datetime.fromisoformat(r['timestamp'])+timedelta(days=1000)).isoformat()) for r in p.rows]
        now[0]+=31
        new=c.daily('AAPL','America/New_York')
        assert len(p.calls)==9 and new[3]!=old[3]
        # No partial commit on invalid OHLCV.
        p.rows[0]['highPrice']=1;now[0]+=31
        with pytest.raises(TossError,match='invalid-candle'):c.daily('AAPL','America/New_York')
        hit=store.get('candles|AAPL|D|adjusted|America/New_York|v1')
        assert hit['dataRevision']==new[3] and hit['fetchedAt']==new[2]
    finally:store.close()


def test_full_reconcile_daily_and_post_close_once(tmp_path):
    now=[NOW];p=Pager();store=MarketStore(tmp_path/'cache.db');c=CandleCollection(p,store,clock=lambda:now[0])
    try:
        c.daily('AAPL','America/New_York');assert len(p.calls)==4
        now[0]+=31;c.daily('AAPL','America/New_York',reconcile_after=NOW+30);assert len(p.calls)==8
        c.daily('AAPL','America/New_York',reconcile_after=NOW+30);assert len(p.calls)==8
        now[0]+=86401;c.daily('AAPL','America/New_York');assert len(p.calls)==12
    finally:store.close()


def test_429_group_blocks_force_other_symbol_and_survives_restart(tmp_path,monkeypatch):
    import market_cache
    now=[NOW];store=MarketStore(tmp_path/'cache.db')
    monkeypatch.setattr(ProviderBudget,'_store',lambda self:store)
    b=ProviderBudget(clock=lambda:now[0],jitter=lambda:.5)
    c=TossClient(budget=b);c.token=Mock(return_value='dummy');c._request=Mock(side_effect=TossError('rate-limited',429,retry_after=180))
    try:
        with pytest.raises(TossError) as first:c.get('/api/v1/candles',symbol='AAPL')
        assert first.value.retry_after==181
        with pytest.raises(TossError):c.get('/api/v1/candles',symbol='MSFT')
        assert c._request.call_count==1
        # Independent group is not blocked.
        c._request=Mock(return_value={'result':[]});c._next_call=0
        assert c.get('/api/v1/stocks',symbols='AAPL')==[]
        b2=ProviderBudget(clock=lambda:now[0],jitter=lambda:.5)
        with pytest.raises(TossError):b2.check('/api/v1/candles')
        now[0]+=181;b2.check('/api/v1/candles')
    finally:store.close()


def test_fallback_backoff_and_transient_failures_no_immediate_retry(monkeypatch):
    now=[NOW];b=ProviderBudget(clock=lambda:now[0],jitter=lambda:.5)
    monkeypatch.setattr(b,'_store',lambda:None)
    for expected in (31,61,121,241,481,481):
        e=TossError('rate-limited',429);b.failure('/api/v1/candles',e)
        assert e.retry_after==expected
        with pytest.raises(TossError):b.check('/api/v1/candles')
        now[0]+=expected
    b.success('/api/v1/candles');b.check('/api/v1/candles')
    for code,status in [('upstream-error',500),('authentication-failed',401),('permission-or-ip-denied',403),('network-or-timeout',0)]:
        b.failure('/api/v1/prices',TossError(code,status))
        with pytest.raises(TossError):b.check('/api/v1/prices')
        now[0]+=61
        b.success('/api/v1/prices')


def test_unknown_db_version_refuses_unbacked_migration(tmp_path):
    p=tmp_path/'future.db'
    with sqlite3.connect(p) as db:db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError,match='backup required'):MarketStore(p)
    with sqlite3.connect(p) as db:assert db.execute('PRAGMA user_version').fetchone()[0]==99


def test_20_symbols_recent_updates_reduce_candle_requests_75_percent(tmp_path):
    now=[NOW];p=Pager();store=MarketStore(tmp_path/'cache.db');c=CandleCollection(p,store,clock=lambda:now[0])
    try:
        for i in range(20):c.daily('S'+str(i),'America/New_York')
        assert len(p.calls)==80
        now[0]+=31
        for i in range(20):c.daily('S'+str(i),'America/New_York')
        assert len(p.calls)-80==20  # 20 recent requests versus previous 80 full pages.
    finally:store.close()


def test_full_pagination_conflicting_adjustments_never_published(tmp_path):
    now=[NOW];p=Pager();store=MarketStore(tmp_path/'cache.db');c=CandleCollection(p,store,clock=lambda:now[0])
    try:
        old=c.daily('AAPL','America/New_York')
        original=p.get
        def inconsistent(path,**params):
            reply=original(path,**params)
            if 'before' in params:
                reply['candles'][0]['closePrice']=104
            return reply
        p.get=inconsistent;now[0]+=86401
        with pytest.raises(TossError,match='adjusted-history-conflict'):c.daily('AAPL','America/New_York')
        assert store.get('candles|AAPL|D|adjusted|America/New_York|v1')['dataRevision']==old[3]
    finally:store.close()


def test_reference_metadata_reused_without_token_or_rest_call(monkeypatch):
    b=ProviderBudget();monkeypatch.setattr(b,'_store',lambda:None)
    c=TossClient(budget=b);c.token=Mock(return_value='dummy-token');c._request=Mock(return_value={'result':[{'name':'Apple'}]})
    one=c.get('/api/v1/stocks',symbols='AAPL');one[0]['name']='changed'
    assert c.get('/api/v1/stocks',symbols='AAPL')==[{'name':'Apple'}]
    assert c.token.call_count==1 and c._request.call_count==1


def test_production_api_uses_shared_source_for_daily_weekly_monthly(tmp_path,monkeypatch):
    import serve_dashboard as server
    import market_cache
    import toss_market
    import toss_catalog
    now=[NOW];cache=MarketCache(tmp_path/'cache.db',clock=lambda:now[0])
    try:
        monkeypatch.setattr(market_cache,'enabled',lambda:True)
        monkeypatch.setattr(market_cache,'services',lambda:cache)
        monkeypatch.setattr(toss_market,'enabled',lambda:True)
        monkeypatch.setattr(toss_catalog,'resolve',lambda code:code)
        monkeypatch.setattr(server,'_with_meta',lambda value,meta:{**value,**meta})
        source=Mock(side_effect=lambda code,force=False:payload(now[0]))
        monkeypatch.setattr(server,'_market_lookup',source)
        first=server.market_lookup('AAPL')
        second=server.market_lookup('AAPL',force=True)
        assert source.call_count==1 and second['cacheHit']
        assert first['weekly']['dataRevision']==first['monthly']['dataRevision']==first['dataRevision']
        assert first['fetchedAt']==second['fetchedAt']
    finally:cache.close()


def test_production_candle_frame_pipeline_reuses_one_daily_revision(tmp_path,monkeypatch):
    import serve_dashboard as server
    import market_cache
    import toss_market
    import toss_catalog
    now=[NOW];cache=MarketCache(tmp_path/'cache.db',clock=lambda:now[0]);pager=Pager()
    def provider(path,**params):
        if path=='/api/v1/candles':return pager.get(path,**params)
        if path=='/api/v1/stocks':return [{'name':'Apple'}]
        pytest.fail('unexpected external endpoint: '+path)
    try:
        monkeypatch.setattr(market_cache,'enabled',lambda:True)
        monkeypatch.setattr(market_cache,'services',lambda:cache)
        monkeypatch.setattr(toss_market,'enabled',lambda:True)
        monkeypatch.setattr(toss_catalog,'resolve',lambda code:code)
        monkeypatch.setattr(toss_market.CLIENT,'get',provider)
        monkeypatch.setattr(server,'_TOSS_NAMES',{})
        monkeypatch.setattr(server,'market_session',lambda code:{'state':'open','lastSessionEnd':None})
        monkeypatch.setattr(server,'_with_meta',lambda value,meta:{**value,**meta})
        first=server.market_lookup('AAPL')
        assert len(pager.calls)==4
        for part in (first,first['weekly'],first['monthly']):assert part['dataRevision']==first['dataRevision']
        now[0]+=31;pager.rows[0]['volume']=12345
        second=server.market_lookup('AAPL')
        assert len(pager.calls)==5 and second['candles'][-1]['volume']==12345
        assert first['dataRevision']!=second['dataRevision'] and second['fetchedAt']!=first['fetchedAt']
        third=server.market_lookup('AAPL',force=True)
        assert third['fetchedAt']==second['fetchedAt'] and third['cacheHit'] and len(pager.calls)==5
    finally:cache.close()


def test_warm_symbol_cache_does_not_wait_behind_slow_other_symbol(tmp_path):
    cache=MarketCache(tmp_path/'cache.db',clock=lambda:NOW,wait_seconds=.2)
    release,entered=Event(),Event()
    try:
        cache.lookup('toss','AAPL','D',lambda f:payload())
        def slow(force):entered.set();assert release.wait(1);return payload()
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(cache.lookup,'toss','MSFT','D',slow)
            assert entered.wait(1)
            hit=cache.lookup('toss','AAPL','D',lambda f:pytest.fail('no source call'))
            assert hit['cacheHit'] and not pending.done()
            release.set();pending.result()
    finally:release.set();cache.close()


def test_401_invalidates_token_but_does_not_immediately_reissue(monkeypatch):
    now=[NOW];b=ProviderBudget(clock=lambda:now[0]);monkeypatch.setattr(b,'_store',lambda:None)
    c=TossClient(budget=b);c._token='dummy';c._expires=monotonic()+10000
    c._request=Mock(side_effect=TossError('authentication-failed',401))
    import toss_market
    credentials=Mock(side_effect=AssertionError('must not reauthenticate during cooldown'))
    monkeypatch.setattr(toss_market,'read_credentials',credentials)
    with pytest.raises(TossError):c.get('/api/v1/candles',symbol='AAPL')
    assert c._expires==0
    with pytest.raises(TossError):c.get('/api/v1/prices',symbols='AAPL')
    assert c._request.call_count==1 and credentials.call_count==0


def test_provider_timeout_is_not_mislabeled_as_queue_busy():
    scheduler=RequestScheduler(wait_seconds=1)
    try:
        def fail():raise TimeoutError('provider timeout')
        with pytest.raises(TimeoutError,match='provider timeout'):
            scheduler.execute('one','toss',fail)
    finally:scheduler.close()
