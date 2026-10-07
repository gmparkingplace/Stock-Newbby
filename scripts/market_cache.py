"""Opt-in market collection services shared by chart, CLI and watchlist requests."""
from copy import deepcopy
import json
import os
from pathlib import Path
from threading import Lock
from time import time
from market_store import MarketStore, epoch, revision
from request_scheduler import RequestScheduler

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
    def __init__(self, path, clock=time, wait_seconds=15):
        self.store = MarketStore(path)
        self.clock = clock
        self.scheduler = RequestScheduler(wait_seconds=wait_seconds)
        self.version = revision([ (ROOT/'scripts'/name).read_text() for name in ('signals.py','indicators.py','kr_p5.py','fetch_snapshot.py','time_contract.py','exchange_sessions.py','yahoo_quality.py','h4_sessions.py')])[:16]
        self.stats = dict(cacheHits=0, sourceCollections=0)
        self.lock = Lock()

    def key(self, provider, symbol, tf):
        return '|'.join((provider,symbol,tf,'adjusted',self.version))

    def lookup(self, provider, symbol, tf, fn, force=False, background=False):
        key = self.key(provider,symbol,tf)
        def cached(hit):
            age = self.clock()-epoch(hit['fetchedAt']) if hit else None
            if hit and 0<=age<(10 if force else 30):
                with self.lock:
                    self.stats['cacheHits'] += 1
                return {**hit,'cacheHit':True,'cacheAge':round(age,1),'stale':False}
            return None
        # A fresh cache must not wait behind another symbol's slow collection.
        ready = cached(self.store.get(key))
        if ready is not None:
            return ready
        def collect():
            hit = self.store.get(key)
            ready = cached(hit)
            if ready is not None:
                return ready
            try:
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
                self.store.put(key,payload)
                with self.lock:
                    self.stats['sourceCollections'] += 1
                return payload
            except Exception as error:
                if hit:
                    error.last_success_at=hit['fetchedAt']
                raise
        try:
            return self.scheduler.execute(key, provider, collect, priority=0 if force else 1, background=background)
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
