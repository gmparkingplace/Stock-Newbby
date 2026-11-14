"""Opt-in market collection services shared by chart, CLI and watchlist requests."""
from copy import deepcopy
import json
import os
from pathlib import Path
from threading import Lock
from time import time
from market_store import MarketStore, epoch, revision
from request_scheduler import RequestScheduler, QueueBusy
import perf_probe

ROOT = Path(__file__).resolve().parents[1]
_INSTANCE = None
_LOCK = Lock()


def enabled():
    value = os.environ.get('CHART_SHARED_CACHE')
    if value is not None:
        return value == '1'
    try:
        return json.loads((ROOT / '.local.json').read_text()).get('sharedMarketCache') is True
    except (OSError, ValueError):
        return False


class MarketCache:
    def __init__(self, path, clock=time, wait_seconds=15, stale_wait_seconds=None):
        self.store = MarketStore(path)
        self.clock = clock
        self.scheduler = RequestScheduler(wait_seconds=wait_seconds)
        # With a last-good snapshot we only wait briefly for the collector; the
        # snapshot is labeled stale and a quick retry picks up the fresh result.
        self.stale_wait_seconds = min(4.0, wait_seconds) if stale_wait_seconds is None else stale_wait_seconds
        self.version = revision([ (ROOT/'scripts'/name).read_text() for name in ('signals.py','indicators.py','kr_p5.py','fetch_snapshot.py','time_contract.py','exchange_sessions.py','yahoo_quality.py','h4_sessions.py','intraday_timeframes.py')])[:16]
        self.stats = dict(cacheHits=0, sourceCollections=0, staleServed=0)
        self.lock = Lock()

    def key(self, provider, symbol, tf):
        return '|'.join((provider,symbol,tf,'adjusted',self.version))

    @staticmethod
    def _lane(provider, tf):
        # A long intraday backfill must not starve daily lookups on the same
        # provider. The Toss client serializes HTTP calls, so lanes are safe.
        from intraday_timeframes import is_intraday
        return provider + ':h4' if is_intraday(tf) else provider

    def _age(self, hit):
        try:
            return self.clock()-epoch(hit['fetchedAt'])
        except (KeyError, TypeError, ValueError):
            return None

    def _cached(self, hit, force):
        age = self._age(hit) if hit else None
        if hit and age is not None and 0 <= age < (10 if force else 30):
            with self.lock:
                self.stats['cacheHits'] += 1
            return {**hit,'cacheHit':True,'cacheAge':round(age,1),'stale':False}
        return None

    def stale(self, key, error, force=False):
        """Local contention must not hide the last successful snapshot.

        This is deliberately limited to scheduler waiting limits. Provider errors
        still surface because they may need credentials or a policy decision.
        """
        hit = self.store.get(key)
        if not hit:
            raise error
        # A concurrent collector may have refreshed this key while we waited.
        fresh = self._cached(hit, force)
        if fresh is not None:
            return fresh
        age = self._age(hit)
        with self.lock:
            self.stats['staleServed'] += 1
        return {**hit, 'cacheHit':True, 'cacheAge':None if age is None else round(max(0.0,age),1),
                'stale':True, 'staleReason':getattr(error,'reason','busy'),
                'retryAt':getattr(error,'retry_at',None),
                'lastSuccessAt':hit.get('lastSuccessAt') or hit.get('fetchedAt'),
                'note':'이전 저장값 표시 · 새 자료 수집 중'}

    def lookup(self, provider, symbol, tf, fn, force=False, background=False, prefer_stale=False):
        key = self.key(provider,symbol,tf)
        # A fresh cache must not wait behind another symbol's slow collection.
        with perf_probe.span('market','cache-read'):
            hit = self.store.get(key)
            ready = self._cached(hit, force)
        if ready is not None:
            return ready
        def collect():
            hit = self.store.get(key)
            ready = self._cached(hit, force)
            if ready is not None:
                return ready
            try:
                with perf_probe.span('market','source-collect'):
                    payload = deepcopy(fn(force))
                if not payload.get('fetchedAt'):
                    raise ValueError('source-fetched-at-required')
                epoch(payload['fetchedAt'])
                payload.setdefault('source',provider)
                data_revision = payload.get('dataRevision') or revision(payload['candles'])
                payload.update(dataRevision=data_revision, snapshotId=revision([key,data_revision,payload['fetchedAt']]),
                               cacheHit=False,cacheAge=0,stale=False,lastSuccessAt=payload['fetchedAt'],
                               calculationVersion=self.version)
                for name in ('weekly','monthly'):
                    if name in payload:
                        payload[name].update(dataRevision=data_revision,snapshotId=payload['snapshotId'],lastSuccessAt=payload['fetchedAt'],source=provider,calculationVersion=self.version)
                with perf_probe.span('market','store-publish'):
                    self.store.put(key,payload)
                with self.lock:
                    self.stats['sourceCollections'] += 1
                return payload
            except Exception as error:
                if hit:
                    error.last_success_at=hit['fetchedAt']
                raise
        # A labeled last-good snapshot is shown immediately; cache fill continues
        # in the provider worker so the browser never waits for a provider call.
        if prefer_stale and hit and not force:
            reason = 'collecting'
            try:
                # Priority 2: a detached fill must yield to a waiting request.
                self.scheduler.enqueue(key, self._lane(provider, tf), collect, priority=2)
            except QueueBusy as error:
                reason = error.reason
            return self.stale(key, QueueBusy(reason), force)
        try:
            # A stale snapshot only shortens the wait when another collector is
            # already working on this key. The first refresh keeps the full wait.
            wait = self.stale_wait_seconds if hit and self.scheduler.in_flight(key) else None
            with perf_probe.span('market','queue-wait'):
                return self.scheduler.execute(key, self._lane(provider, tf), collect,
                                              priority=0 if force else 1,
                                              background=background, wait_seconds=wait)
        except QueueBusy as error:
            # The collection (if any) keeps running in its provider worker. Return
            # the last good snapshot with an explicit stale label instead of a 503.
            return self.stale(key, error, force)
        except Exception as error:
            hit = self.store.get(key)
            if hit:
                error.last_success_at=hit['fetchedAt']
            raise

    def snapshot(self):
        with self.lock:
            return {'enabled':True,**self.stats,'queue':self.scheduler.snapshot()}

    def close(self):
        self.scheduler.close()
        if not any(worker.is_alive() for worker in self.scheduler.workers.values()):
            self.store.close()


def services():
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = MarketCache(ROOT/'logs'/'market-cache.sqlite3')
        return _INSTANCE


def diagnostics():
    if not enabled():
        return {'enabled':False}
    return _INSTANCE.snapshot() if _INSTANCE else {'enabled':True,'queue':{'inFlight':0,'pendingCount':0}}
