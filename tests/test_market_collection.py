"""P1 offline concurrency/storage/REST-count contracts. No credentials or sockets."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import sys
from threading import Event, Lock
from time import monotonic, sleep
from types import SimpleNamespace
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


def test_queued_job_still_collects_after_waiter_timed_out():
    scheduler=RequestScheduler(wait_seconds=.05,expire_seconds=5)
    entered,release=Event(),Event()
    def slow():
        entered.set();assert release.wait(2);return 1
    try:
        with ThreadPoolExecutor(1) as pool:
            timed_out=pool.submit(scheduler.execute,'one','toss',slow)
            assert entered.wait(1)
            with pytest.raises(QueueBusy):timed_out.result(timeout=1)
            with pytest.raises(QueueBusy) as busy:scheduler.execute('two','toss',lambda:2)
            assert busy.value.reason=='wait-timeout'
            with scheduler.cv: one,queued=scheduler.flights.get('one'),scheduler.flights.get('two')
            assert one is not None and queued is not None and not queued.done()
            release.set()
            # The HTTP waiters are gone, but cache fill still finishes.
            assert one.result(timeout=2)==1
            assert queued.result(timeout=2)==2
            assert scheduler.snapshot()['waitTimeout']==2
    finally:
        release.set();scheduler.close()


def test_busy_returns_labeled_last_good_snapshot_instead_of_503(tmp_path):
    now=[NOW];cache=MarketCache(tmp_path/'cache.db',clock=lambda:now[0],wait_seconds=.05)
    entered,release=Event(),Event()
    good=payload(NOW)
    try:
        first=cache.lookup('toss','AAPL','D',lambda f:good)
        now[0]+=31
        def slow(code,force=False):
            entered.set();assert release.wait(2);return payload(now[0])
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(cache.lookup,'toss','AAPL','D',slow,True, background=True)
            assert entered.wait(1)
            stale=cache.lookup('toss','AAPL','D',lambda f:pytest.fail('merged waiters must not collect'))
            assert stale['stale'] and stale['cacheHit']
            assert stale['staleReason']=='wait-timeout'
            assert stale['fetchedAt']==first['fetchedAt']
            assert stale['lastSuccessAt']==first['fetchedAt']
            assert stale['cacheAge']==31 and stale['note']
            release.set();fresh=pending.result()
        assert fresh['fetchedAt']!=first['fetchedAt'] and not fresh['stale']
        assert cache.stats['staleServed']==1
    finally:
        release.set();cache.close()


def test_daily_and_h4_lanes_do_not_block_each_other(tmp_path):
    now=[NOW];cache=MarketCache(tmp_path/'cache.db',clock=lambda:now[0],wait_seconds=1)
    entered,release=Event(),Event()
    try:
        with ThreadPoolExecutor(2) as pool:
            def slow_daily(force):
                entered.set();assert release.wait(2);return payload(now[0])
            blocked=pool.submit(cache.lookup,'toss','AAPL','D',slow_daily)
            assert entered.wait(1)
            h4=pool.submit(cache.lookup,'toss','AAPL','H4',lambda f:payload(now[0]))
            assert h4.result(timeout=1)['fetchedAt']==payload(now[0])['fetchedAt']
            assert not blocked.done(),'H4 backfill must not block the daily lane'
            release.set();assert blocked.result(timeout=2)['fetchedAt']==payload(now[0])['fetchedAt']
    finally:
        release.set();cache.close()


def test_stale_refresh_serves_as_fresh_when_collector_won(tmp_path):
    now=[NOW];cache=MarketCache(tmp_path/'cache.db',clock=lambda:now[0])
    try:
        first=cache.lookup('toss','AAPL','D',lambda f:payload(now[0]))
        now[0]+=5
        out=cache.stale(cache.key('toss','AAPL','D'),QueueBusy('wait-timeout'))
        assert not out['stale'] and out['cacheHit'] and out['cacheAge']==5
    finally:
        cache.close()


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


def test_full_reconcile_is_deferred_to_an_explicit_audit(tmp_path):
    now=[NOW];p=Pager();store=MarketStore(tmp_path/'cache.db');c=CandleCollection(p,store,clock=lambda:now[0])
    try:
        c.daily('AAPL','America/New_York');assert len(p.calls)==4
        now[0]+=31
        # Post-close and 24h checks no longer run inside the request path.
        c.daily('AAPL','America/New_York',reconcile_after=NOW+30);assert len(p.calls)==5
        assert c.needs_audit('AAPL','America/New_York',reconcile_after=NOW+30) is True
        c.daily('AAPL','America/New_York',audit=True);assert len(p.calls)==9
        assert c.needs_audit('AAPL','America/New_York',reconcile_after=NOW+30) is False
        now[0]+=86401
        assert c.needs_audit('AAPL','America/New_York') is True
        c.daily('AAPL','America/New_York');assert len(p.calls)==10
        c.daily('AAPL','America/New_York',audit=True);assert len(p.calls)==14
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
        with pytest.raises(TossError,match='adjusted-history-conflict'):
            c.daily('AAPL','America/New_York',audit=True)
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
        monkeypatch.setattr(server,'market_session',lambda code,**kw:{'state':'open','lastSessionEnd':None})
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


def test_prefer_stale_returns_last_good_without_waiting_for_provider(tmp_path):
    now=[NOW];cache=MarketCache(tmp_path/'cache.db',clock=lambda:now[0],wait_seconds=5)
    entered,release=Event(),Event()
    try:
        first=cache.lookup('toss','AAPL','D',lambda f:payload(NOW))
        now[0]+=120
        def slow(code,force=False):
            entered.set();assert release.wait(2);return payload(now[0])
        started=monotonic()
        stale=cache.lookup('toss','AAPL','D',slow,prefer_stale=True)
        elapsed=monotonic()-started
        assert elapsed<1,'a labeled snapshot must not wait for the provider'
        assert stale['stale'] and stale['cacheHit'] and stale['fetchedAt']==first['fetchedAt']
        assert stale['staleReason']=='collecting' and stale['retryAt']
        assert entered.wait(1),'cache fill must continue in the provider worker'
        assert cache.scheduler.snapshot()['inFlight']==1,'stale responses must not start a second collection'
        started=monotonic()
        again=cache.lookup('toss','AAPL','D',slow,prefer_stale=True)
        assert monotonic()-started<.5,'repeated UI polling must not wait four seconds on the same flight'
        assert again['stale'] and again['fetchedAt']==first['fetchedAt']
        assert cache.scheduler.snapshot()['submitted']==2,'one initial collection and one refresh only'
        release.set()
        fresh=cache.lookup('toss','AAPL','D',lambda f:pytest.fail('must merge into the running job'))
        assert not fresh['stale'] and fresh['fetchedAt']!=first['fetchedAt']
    finally:
        release.set();cache.close()


def test_prefer_stale_keeps_first_fetch_blocking_and_force_waiting(tmp_path):
    now=[NOW];cache=MarketCache(tmp_path/'cache.db',clock=lambda:now[0],wait_seconds=.2)
    try:
        cold=cache.lookup('toss','AAPL','D',lambda f:payload(now[0]),prefer_stale=True)
        assert cold['fetchedAt']==payload(now[0])['fetchedAt'] and not cold['stale']
        now[0]+=60
        seen=[]
        def fetch(force):
            seen.append(force);return payload(now[0])
        forced=cache.lookup('toss','AAPL','D',fetch,force=True,prefer_stale=True)
        assert seen==[True] and not forced['stale'],'an explicit refresh still collects before answering'
    finally:
        cache.close()


def test_market_lookup_ui_path_returns_saved_chart_before_provider(tmp_path,monkeypatch):
    import serve_dashboard as server
    import pattern_service
    now=[NOW];cache=MarketCache(tmp_path/'cache.db',clock=lambda:now[0],wait_seconds=5)
    entered,release=Event(),Event()
    try:
        cache.lookup('toss','AAPL','D',lambda f:payload(NOW))
        now[0]+=300
        def slow(code,force=False):
            entered.set();assert release.wait(2);return payload(now[0])
        monkeypatch.setattr(server,'market_cache',SimpleNamespace(enabled=lambda:True,services=lambda:cache))
        monkeypatch.setattr(server,'_provider_choice',lambda tf='D':'auto')
        # 공개본에는 키가 없으므로 공급처 선택도 fixture로 고정한다.
        import toss_market, toss_catalog
        monkeypatch.setattr(toss_market,'enabled',lambda:True)
        monkeypatch.setattr(toss_market,'supports',lambda code:True)
        monkeypatch.setattr(toss_catalog,'resolve',lambda code:code)
        monkeypatch.setattr(server,'_with_meta',lambda payload,cache_meta:payload)
        monkeypatch.setattr(pattern_service,'attach',lambda payload:payload)
        monkeypatch.setattr(server,'_market_lookup',slow)
        started=monotonic()
        out=server.market_lookup('AAPL',prefer_stale=True)
        assert monotonic()-started<1
        assert out['stale'] is True and out['cacheHit'] is True
        assert out['note'] and out['lastSuccessAt']==payload(NOW)['fetchedAt']
        assert entered.wait(1)
        release.set()
        fresh=server.market_lookup('AAPL')
        assert not fresh['stale'] and fresh['fetchedAt']!=out['fetchedAt']
    finally:
        release.set()
        server.market_cache=__import__('market_cache')
        cache.close()


def test_interactive_request_promotes_a_queued_job():
    scheduler=RequestScheduler(wait_seconds=5)
    entered,release=Event(),Event()
    try:
        with ThreadPoolExecutor(1) as pool:
            running=pool.submit(scheduler.execute,'A','toss',
                                lambda:(entered.set(),release.wait(2),1)[2])
            assert entered.wait(1)
            assert scheduler.enqueue('B','toss',lambda:2) is True
            with scheduler.cv:
                assert scheduler.pending['toss'][0][0]==2
                assert scheduler.has_waiting('toss',2) is False
            with pytest.raises(QueueBusy):
                scheduler.execute('B','toss',lambda:2,priority=0,wait_seconds=.01)
            with scheduler.cv:
                assert scheduler.pending['toss'][0][0]==0,'interactive work must move ahead'
                assert scheduler.has_waiting('toss',2) is True
            release.set()
            assert running.result(timeout=2)==1
            for _ in range(200):
                if scheduler.snapshot()['completed']>=2:break
                sleep(.01)
            assert scheduler.snapshot()['completed']==2
    finally:
        release.set();scheduler.close()


def test_deferred_collection_keeps_its_flight_and_resumes():
    from request_scheduler import CollectionDeferred
    scheduler=RequestScheduler(wait_seconds=2)
    seen=[]
    def job():
        seen.append(1)
        if len(seen)==1:raise CollectionDeferred('page-8')
        return 'done'
    try:
        scheduler.enqueue('k','toss',job)
        for _ in range(300):
            if scheduler.snapshot()['completed']:break
            sleep(.01)
        assert seen==[1,1],'a deferred job must resume from its checkpoint'
        assert scheduler.snapshot()['deferred']==1
        assert scheduler.flights=={}
    finally:
        scheduler.close()


def test_minute_backfill_yields_at_a_page_boundary(tmp_path,monkeypatch):
    from datetime import datetime, timezone
    from minute_collection import MinuteCollection
    from request_scheduler import CollectionDeferred
    store=MarketStore(tmp_path/'c.db')
    seen=[]
    def page(self,symbol,tz,before=None):
        seen.append(before)
        base=1700000000-200*60*len(seen)
        rows=[dict(t=base+i*60,open=1,high=1,low=1,close=1,volume=1) for i in range(200)]
        cursor=datetime.fromtimestamp(base-60,timezone.utc).isoformat()
        return rows,cursor
    monkeypatch.setattr(MinuteCollection,'_page',page)
    collector=MinuteCollection(None,store,clock=lambda:1700000000)
    try:
        with pytest.raises(CollectionDeferred):
            collector._full('AAPL','America/New_York','stage',yield_check=lambda:True)
        stage=store.get('stage')
        assert stage and stage['pages']==1 and stage['rows']
        assert len(seen)==1
        # Resuming continues from the stored cursor instead of restarting.
        with pytest.raises(CollectionDeferred):
            collector._full('AAPL','America/New_York','stage',yield_check=lambda:True)
        assert len(seen)==2 and seen[1] is not None
    finally:
        store.close()


def test_minute_needs_audit_follows_the_full_refresh_time():
    from minute_collection import MinuteCollection
    now=[NOW]
    collector=MinuteCollection(None,None,clock=lambda:now[0])
    key=collector._key('AAPL','America/New_York')
    stamp=datetime.fromtimestamp(now[0],timezone.utc).isoformat(timespec='seconds')
    collector._put(key,dict(rows=[],fetchedAt=stamp,dataRevision='x',history={},
                            fullRefreshAt=now[0]))
    assert collector.needs_audit('AAPL','America/New_York') is False
    now[0]+=86401
    assert collector.needs_audit('AAPL','America/New_York') is True


def test_audit_scheduling_is_bounded_and_merged(monkeypatch):
    import serve_dashboard as server
    class Scheduler:
        def __init__(self):self.calls=[]
        def enqueue(self,key,lane,fn,priority=2):
            self.calls.append((key,lane,priority));return True
    class Services:
        def __init__(self):self.scheduler=Scheduler()
    svc=Services()
    server._AUDIT_RETRY_AT.clear()
    try:
        assert server._queue_audit(svc,'audit|AAPL','toss',lambda:None) is True
        assert len(svc.scheduler.calls)==1 and svc.scheduler.calls[0][2]==3
        assert server._queue_audit(svc,'audit|AAPL','toss',lambda:None) is False,'retry cooldown'
        assert len(svc.scheduler.calls)==1
    finally:
        server._AUDIT_RETRY_AT.clear()
