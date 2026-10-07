"""24/7 coin D/H4: transport, confirmation, separate ledgers, no provider calls."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from market_store import MarketStore, revision
from pattern_window import start, within
from time_contract import judgment_metadata, market_session
import flag_patterns
import triangle_patterns
import pattern_service as svc
import market_cache
from flag_fixture import flag_rows
from triangle_fixture import triangle_rows


def coin_payload(family='triangle',tf='H4',direction='up',provisional=False):
    rows=flag_rows(direction) if family=='flag' else triangle_rows('ascending',direction)
    if tf=='H4':
        base=int(datetime(2026,1,1,tzinfo=timezone.utc).timestamp())
        for i,r in enumerate(rows):r['time']=base+i*14400
        begin=datetime.fromtimestamp(rows[-1]['time'],timezone.utc);duration=timedelta(hours=4)
    else:
        begin=datetime.fromisoformat(rows[-1]['time']).replace(tzinfo=timezone.utc);duration=timedelta(days=1)
    now=begin+duration/2 if provisional else begin+duration+timedelta(minutes=31)
    p=dict(symbol='BTC-USD',name='비트코인',tf=tf,source='yfinance',candles=rows,dataRevision=revision(rows),fetchedAt=now.isoformat())
    return judgment_metadata(p,'BTC-USD','UTC',tf,now=now),now


@pytest.fixture
def enabled_store(tmp_path,monkeypatch):
    store=MarketStore(tmp_path/'coin.db')
    for feature in ['CHART_FLAG_PATTERNS','CHART_TRIANGLE_PATTERNS','CHART_HORIZONTAL_PATTERNS']:monkeypatch.setenv(feature,'1')
    monkeypatch.setattr(market_cache,'enabled',lambda:True)
    monkeypatch.setattr(market_cache,'services',lambda:SimpleNamespace(store=store))
    yield store
    store.close()


@pytest.mark.parametrize('tf',['D','H4'])
@pytest.mark.parametrize('family',['flag','triangle'])
@pytest.mark.parametrize('direction',['up','down'])
def test_coin_shapes_and_original_source_confirmation(tf,family,direction,enabled_store,monkeypatch):
    p,now=coin_payload(family,tf,direction)
    assert p['confirmed'] and p['lastConfirmedTime']==p['candles'][-1]['time']
    monkeypatch.setattr(svc,'datetime',type('Clock',(datetime,),{'now':staticmethod(lambda tz:now)}))
    out=svc.attach(p)
    a=out['flagAnalysis' if family=='flag' else 'triangleAnalysis']
    events=[e for e in a['events'] if e['eventType']=='confirmed']
    assert a['timeframe']==tf and a['sourceStatus']=='ready' and len(events)==1
    assert events[0]['direction']==direction
    assert out['patternAnalysis']['sourceStatus']=='unsupported'
    assert out['source']=='yfinance' and out['candles']==p['candles']
    snap=enabled_store.pattern_snapshot(events[0]['basisSnapshotId'])
    assert snap['timeframe']==tf and snap['candles'][-1]['time']==events[0]['confirmedBarTime']


@pytest.mark.parametrize('family',['flag','triangle'])
@pytest.mark.parametrize('tf',['D','H4'])
def test_coin_provisional_expiry_failure_and_prefix(family,tf,enabled_store):
    p,now=coin_payload(family,tf,provisional=True)
    out=svc.evaluate(p,enabled_store,now,family)
    assert p['snapshotEligible'] and not out['events']
    assert out['timeline'][-1]['patterns'][0]['status']=='breakout-pending'
    expired=svc.evaluate(p,enabled_store,now+timedelta(seconds=91),family)
    assert not expired['provisionalEligible'] and expired['timeline'][-1]['patterns'][0]['status']=='paused'
    failed=deepcopy(p);failed['lastError']='offline-fixture'
    assert svc.evaluate(failed,enabled_store,now,family)['sourceStatus']=='paused'
    assert not enabled_store.pattern_events()
    engine=flag_patterns.analyze if family=='flag' else triangle_patterns.analyze
    full=engine(p['candles'],p['symbol'],p['candles'][-1]['time'],timeframe=tf)
    for n in range(30,len(p['candles'])+1):
        prefix=engine(p['candles'][:n],p['symbol'],p['candles'][n-1]['time'],timeframe=tf)
        assert prefix['timeline']==full['timeline'][:n]
        assert prefix['events']==[e for e in full['events'] if e['confirmedBarTime']<=p['candles'][n-1]['time']]


def test_coin_timeframe_keys_correction_and_window(enabled_store):
    h4,now=coin_payload();daily,dnow=coin_payload(tf='D')
    for p,t in [(h4,now),(daily,dnow)]:svc.evaluate(p,enabled_store,t,'triangle')
    keys=[svc.result_key('BTC-USD',{},'triangle',tf) for tf in ['D','H4']]
    assert keys[0]!=keys[1] and all(enabled_store.pattern_result(k) for k in keys)
    before=enabled_store.pattern_events();assert len(before)==2
    snap=enabled_store.pattern_snapshot(before[0]['basisSnapshotId'])
    # Serializing/deserializing H4 barHashes changes JSON integer keys to strings.
    for _ in range(3):svc.evaluate(h4,enabled_store,now,'triangle')
    assert len(enabled_store.pattern_events())==2
    corrected=deepcopy(h4);corrected['candles'][-1].update(close=112,high=118,low=111)
    corrected['dataRevision']=revision(corrected['candles']);svc.evaluate(corrected,enabled_store,now,'triangle')
    assert enabled_store.pattern_events()[-1]['eventType']=='revised'
    assert enabled_store.pattern_snapshot(before[0]['basisSnapshotId'])==snap
    shown=svc.visible_events(enabled_store,enabled_store.pattern_events(with_symbol=True))
    assert {e.get('timeframe','D') for e in shown}=={'D','H4'}
    stamp=int(datetime(2026,5,31,12,tzinfo=timezone.utc).timestamp())
    assert start(stamp)==int(datetime(2026,2,28,12,tzinfo=timezone.utc).timestamp())
    assert within(dict(anchorTime=start(stamp),confirmedBarTime=stamp),stamp)
    assert not within(dict(anchorTime=start(stamp)-14400,confirmedBarTime=stamp),stamp)


def test_intraday_ledger_survives_store_restart(tmp_path):
    path=tmp_path/'restart.db';p,now=coin_payload();store=MarketStore(path)
    try:
        first=svc.evaluate(p,store,now,'triangle');e=first['events'][0]
        snap=store.pattern_snapshot(e['basisSnapshotId'])
    finally:store.close()
    store=MarketStore(path)
    try:
        svc.evaluate(p,store,now,'triangle')
        assert len(store.pattern_events())==1
        assert store.pattern_snapshot(e['basisSnapshotId'])==snap
    finally:store.close()


def test_cached_coin_api_timeframe_filter_does_not_collect(enabled_store,monkeypatch):
    import analysis_jobs
    for tf in ['D','H4']:
        p,now=coin_payload(tf=tf);svc.evaluate(p,enabled_store,now,'triangle')
    monkeypatch.setattr(analysis_jobs,'_reply',lambda h,status,data:(status,data))
    h=SimpleNamespace(path='/api/patterns?symbol=BTC-USD&kind=triangle&tf=H4',command='GET',headers={'Host':'127.0.0.1:8735'},server=SimpleNamespace(server_port=8735))
    code,data=svc.handle(h);assert code==200 and data['timeframe']=='H4'
    h.path='/api/events?symbol=BTC-USD&tf=H4';code,data=svc.handle(h)
    assert code==200 and len(data['events'])==1 and data['events'][0]['timeframe']=='H4' and data['nextCursor']==2
    h.path='/api/patterns?symbol=AAPL&kind=triangle&tf=H4';assert svc.handle(h)[1]['sourceStatus']=='not-collected'


def test_intraday_transport_attaches_same_cached_frame_without_more_collections(enabled_store,monkeypatch):
    import serve_dashboard as server
    p,now=coin_payload()
    calls=[]
    def lookup(provider,symbol,tf,fn,*args,**kwargs):
        calls.append((provider,symbol,tf));return {**p,'cacheHit':True,'cacheAge':1,'stale':False}
    monkeypatch.setattr(market_cache,'services',lambda:SimpleNamespace(store=enabled_store,lookup=lookup))
    monkeypatch.setattr(svc,'datetime',type('Clock',(datetime,),{'now':staticmethod(lambda tz:now)}))
    monkeypatch.setattr(server,'_with_meta',lambda p,meta:{**p,**meta})
    out=server.market_intraday('BTC-USD')
    assert calls==[('yfinance','BTC-USD','H4')]
    assert out['triangleAnalysis']['timeframe']=='H4' and out['triangleAnalysis']['events']
    assert out['candles']==p['candles'] and out['source']=='yfinance'


@pytest.mark.parametrize('bad',[True,1.5,'2026-01-01',-14400,1767225601])
def test_invalid_intraday_timestamps_are_rejected(bad):
    p,_=coin_payload();p['candles'][0]['time']=bad
    with pytest.raises(ValueError):triangle_patterns.analyze(p['candles'],'BTC-USD',None,timeframe='H4')


def test_intraday_error_retains_timeframe_for_ui(enabled_store,monkeypatch):
    p,_=coin_payload();p['candles'][-1]['low']=p['candles'][-1]['high']+1
    out=svc.attach(p)
    assert out['triangleAnalysis']['sourceStatus']=='error'
    assert out['triangleAnalysis']['timeframe']=='H4'
    assert out['triangleAnalysis']['errorCode']=='invalid-data'


@pytest.mark.parametrize('family,engine',[('flag',flag_patterns),('triangle',triangle_patterns)])
@pytest.mark.parametrize('missing',[1,3,60])
def test_h4_missing_bars_break_patterns_and_restart_preparation(family,engine,missing):
    p,_=coin_payload(family=family);rows=p['candles'];frozen=deepcopy(rows)
    for row in rows[40:]:row['time']+=missing*14400
    result=engine.analyze(rows,'BTC-USD',rows[-1]['time'],timeframe='H4')
    assert result['segmentCount']==2 and result['dataWarnings'][0]['missingBars']==missing
    assert not result['events']
    assert all(not r['patterns'] and r['status']=='insufficient-data' for r in result['timeline'][40:54])
    # Old history stays identical; post-gap preparation uses only the new segment.
    before=engine.analyze(rows[:40],'BTC-USD',rows[39]['time'],timeframe='H4')
    after=engine.analyze(rows[40:],'BTC-USD',rows[-1]['time'],timeframe='H4')
    assert result['timeline'][:40]==before['timeline']
    assert result['timeline'][40:]==after['timeline']
    assert all(rows[i]['close']==frozen[i]['close'] for i in range(len(rows)))


@pytest.mark.parametrize('family,engine',[('flag',flag_patterns),('triangle',triangle_patterns)])
def test_new_h4_patterns_after_gap_and_prefix_causality(family,engine):
    p,_=coin_payload(family=family);base=p['candles'];rows=deepcopy(base)
    offset=base[-1]['time']+10*14400-base[0]['time']
    rows.extend({**r,'time':r['time']+offset} for r in base)
    frozen=deepcopy(rows);out=engine.analyze(rows,'BTC-USD',rows[-1]['time'],timeframe='H4')
    confirms=[e for e in out['events'] if e['eventType']=='confirmed']
    assert len(confirms)==2 and len({e['eventId'] for e in out['events']})==len(out['events'])
    assert confirms[0]['confirmedBarTime']<rows[len(base)]['time']<=confirms[1]['anchorTime']
    for n in [len(base)-1,len(base),len(base)+1,len(rows)-1,len(rows)]:
        part=engine.analyze(rows[:n],'BTC-USD',rows[n-1]['time'],timeframe='H4')
        assert out['timeline'][:n]==part['timeline']
        assert [e for e in out['events'] if e['confirmedBarTime']<=rows[n-1]['time']]==part['events']
    assert rows==frozen
    # A new unconfirmed segment cannot continue the old pattern or emit an event.
    preview=engine.analyze(rows,'BTC-USD',base[-1]['time'],True,timeframe='H4')
    assert not any(e['confirmedBarTime']>base[-1]['time'] for e in preview['events'])
    assert not preview['timeline'][-1]['patterns']


@pytest.mark.parametrize('family,engine',[('flag',flag_patterns),('triangle',triangle_patterns)])
def test_h4_v3_preserves_v2_events_and_snapshots(enabled_store,monkeypatch,family,engine):
    p,now=coin_payload(family=family)
    with monkeypatch.context() as patch:
        patch.setattr(engine,'rule_version',lambda *a,**kw:family+'-h4-v2')
        old=engine.analyze(p['candles'],'BTC-USD',p['lastConfirmedTime'],timeframe='H4')
    event=deepcopy(old['events'][0]);event['basisSnapshotId']='v2-'+family
    snapshot=dict(snapshotId=event['basisSnapshotId'],event=deepcopy(event),candles=deepcopy(p['candles']))
    enabled_store.pattern_publish(family+'|BTC-USD|H4|'+family+'-h4-v2',old,[(event,snapshot)])
    new=svc.evaluate(p,enabled_store,now,family)
    assert new['ruleVersion']==family+'-h4-v3'
    assert enabled_store.pattern_event(event['eventId'])==event
    assert enabled_store.pattern_snapshot(event['basisSnapshotId'])==snapshot
    assert {e['ruleVersion'] for e in svc.visible_events(enabled_store,enabled_store.pattern_events(with_symbol=True),current_only=True)}=={family+'-h4-v3'}
    before=len(enabled_store.pattern_events());svc.evaluate(p,enabled_store,now,family)
    assert len(enabled_store.pattern_events())==before
