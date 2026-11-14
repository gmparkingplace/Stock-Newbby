"""Repeated identical inputs must reuse the pure engine and skip re-publishing."""
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from market_store import MarketStore
import pattern_service as svc
from test_horizontal_patterns import bars, payload


def _evaluate(store, rows, fetched='2026-02-01T22:00:00+00:00'):
    data=payload(rows)
    data['fetchedAt']=fetched
    return svc.evaluate(data, store, family='horizontal')


def test_identical_input_reuses_engine_without_republishing(tmp_path,monkeypatch):
    store=MarketStore(tmp_path/'c.db')
    computed,published=[],[]
    real_analyze,real_publish=svc.analyze,MarketStore.pattern_publish
    def spy_analyze(*a,**k):
        computed.append(1);return real_analyze(*a,**k)
    def spy_publish(self,*a,**k):
        published.append(1);return real_publish(self,*a,**k)
    monkeypatch.setattr(svc,'analyze',spy_analyze)
    monkeypatch.setattr(MarketStore,'pattern_publish',spy_publish)
    try:
        rows=bars(140)
        first=_evaluate(store,rows)
        second=_evaluate(store,rows,fetched='2026-02-01T22:05:00+00:00')
        third=_evaluate(store,rows,fetched='2026-02-01T22:10:00+00:00')
        assert computed==[1],'the same candles must be calculated once'
        assert published==[1],'an unchanged basis must not be published again'
        assert first['events']==second['events']==third['events']
        assert second['evaluatedAt']!=first['evaluatedAt'],'per-response times are refreshed'
        assert second['sourceFetchedAt']=='2026-02-01T22:05:00+00:00'
        assert second['sourceStatus']=='ready' and second['dataRevision']==first['dataRevision']
        # A changed candle is a different input and must recalculate.
        changed=bars(140);changed[-1]['close']=60;changed[-1]['low']=59
        fourth=_evaluate(store,changed,fetched='2026-02-01T22:15:00+00:00')
        assert computed==[1,1] and published==[1,1]
        assert fourth['events']!=first['events']
    finally:
        store.close()


def test_data_revision_alone_cannot_mask_changed_candles(tmp_path,monkeypatch):
    store=MarketStore(tmp_path/'c.db')
    computed=[]
    real_analyze=svc.analyze
    def spy_analyze(*a,**k):
        computed.append(1);return real_analyze(*a,**k)
    monkeypatch.setattr(svc,'analyze',spy_analyze)
    try:
        rows=bars(140)
        _evaluate(store,rows)
        tampered=bars(140)
        tampered[-1]['low']=200  # invalid OHLC, same declared revision
        data=payload(tampered)
        with pytest.raises(ValueError):
            svc.evaluate(data, store, family='horizontal')
        assert computed==[1,1],'the engine must still validate the supplied candles'
    finally:
        store.close()


def test_cache_is_isolated_per_store(tmp_path,monkeypatch):
    one,two=MarketStore(tmp_path/'one.db'),MarketStore(tmp_path/'two.db')
    computed=[]
    real_analyze=svc.analyze
    def spy_analyze(*a,**k):
        computed.append(1);return real_analyze(*a,**k)
    monkeypatch.setattr(svc,'analyze',spy_analyze)
    try:
        rows=bars(140)
        _evaluate(one,rows)
        _evaluate(two,rows)
        assert computed==[1,1],'separate caches must not share a result'
    finally:
        one.close();two.close()


def test_stale_payload_is_reused_without_publishing(tmp_path,monkeypatch):
    store=MarketStore(tmp_path/'c.db')
    computed,published=[],[]
    real_analyze,real_publish=svc.analyze,MarketStore.pattern_publish
    def spy_analyze(*a,**k):
        computed.append(1);return real_analyze(*a,**k)
    def spy_publish(self,*a,**k):
        published.append(1);return real_publish(self,*a,**k)
    monkeypatch.setattr(svc,'analyze',spy_analyze)
    monkeypatch.setattr(MarketStore,'pattern_publish',spy_publish)
    try:
        rows=bars(140)
        data=payload(rows);data['stale']=True
        paused=svc.evaluate(data, store, family='horizontal')
        again=svc.evaluate(dict(data), store, family='horizontal')
        assert paused['sourceStatus']=='paused' and again['sourceStatus']=='paused'
        assert computed==[1] and published==[],'paused input never publishes and is reused'
    finally:
        store.close()
