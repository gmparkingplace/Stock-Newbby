"""Causal flags, negative examples, close policy and durable geometry snapshots."""
from copy import deepcopy
from datetime import datetime,timezone,date,timedelta
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from flag_fixture import flag_rows
from flag_patterns import analyze,pivots,RULE
from market_store import MarketStore,revision
from test_horizontal_patterns import payload,NOW,append
import pattern_service as svc


@pytest.mark.parametrize('direction,kind',[('up','bull-flag'),('down','bear-flag')])
def test_mirrored_flags_and_frozen_channel(direction,kind):
    rows=flag_rows(direction);out=analyze(rows,'T',rows[-1]['time'])
    confirmed=[e for e in out['events'] if e['eventType']=='confirmed']
    assert len(confirmed)==1
    e=confirmed[0];assert e['type']==kind and e['direction']==direction
    assert e['adjustmentBars']==14 and e['adjustmentStartTime']==rows[35]['time']
    assert len(e['pivotHighTimes'])>=2 and len(e['pivotLowTimes'])>=2
    assert e['geometry']['kind']=='channel' and len(e['geometry']['points'])==4
    assert e['adjustmentVolumeRatio']<1 and e['rvol20Previous']>1.2
    assert all(t<=rows[-3]['time'] for t in e['pivotHighTimes']+e['pivotLowTimes'])


def test_provisional_cannot_discover_pivots_or_emit():
    rows=flag_rows();cut=rows[-2]['time'];out=analyze(rows,'T',cut,True)
    assert not out['events']
    assert any(p['status']=='breakout-pending' for p in out['timeline'][-1]['patterns'])
    assert all(p['discoveredTime']<=cut for p in out['timeline'][-1]['patterns'])
    paused=analyze(rows,'T',cut,False)
    assert all(p['status']=='paused' for p in paused['timeline'][-1]['patterns'])


def test_every_prefix_is_identical_after_later_bars():
    rows=flag_rows();full=analyze(rows,'T',rows[-1]['time'])
    for n in range(30,len(rows)+1):
        prefix=analyze(rows[:n],'T',rows[n-1]['time'])
        assert full['timeline'][:n]==prefix['timeline']
        assert [e for e in full['events'] if e['confirmedBarTime']<=rows[n-1]['time']]==prefix['events']


def test_future_extreme_and_volume_cannot_change_earlier_geometry():
    rows=flag_rows();original=analyze(rows,'T',rows[-1]['time'])
    extended=append(rows,180,90,200,volume=999999)
    full=analyze(extended,'T',extended[-1]['time'])
    assert full['timeline'][:len(rows)]==original['timeline']
    assert full['events'][0]==original['events'][0]


@pytest.mark.parametrize('mode',['no-pole','no-pivots','retracement','nonparallel','calendar-unknown'])
def test_negative_examples(mode):
    rows=flag_rows()
    cutoff=rows[-1]['time']
    if mode=='no-pole':
        for r in rows:r.update(open=100,close=100,high=101,low=99)
    elif mode=='no-pivots':
        for i,r in enumerate(rows[35:]):r.update(open=113-i*.1,close=113-i*.1,high=114-i*.1,low=112-i*.1)
    elif mode=='retracement':
        for r in rows[35:]:r.update(open=103,close=103,high=104,low=102)
    elif mode=='nonparallel':
        for j,r in enumerate(rows[35:-1]):r['low']=min(r['low'],109-j*1.4)
    else:cutoff=None
    assert not analyze(rows,'T',cutoff)['events']


def test_twenty_bar_boundary_and_expiration():
    legacy=lambda *args:analyze(*args,profile='legacy')
    rows=flag_rows(breakout=False,adjustment=20)
    out=legacy(rows,'T',rows[-1]['time'])
    assert not out['events']
    assert any(p['status']=='forming' and p['adjustmentBars']==20 for p in out['timeline'][-1]['patterns'])
    # The 20th adjustment bar may break; the 21st cannot.
    valid=deepcopy(rows);valid[-1].update(open=118,close=118,high=119,low=112)
    assert any(e['eventType']=='confirmed' for e in legacy(valid,'T',valid[-1]['time'])['events'])
    expired=append(rows,118,112,119)
    out=legacy(expired,'T',expired[-1]['time'])
    assert not out['events'] and any(p['status']=='expired' for p in out['timeline'][-1]['patterns'])


def test_invalidation_wins_over_same_bar_breakout():
    rows=flag_rows();rows[-1]['low']=100
    assert not analyze(rows,'T',rows[-1]['time'])['events']


def test_retest_failure_and_unconfirmed_failure():
    rows=flag_rows();e=analyze(rows,'T',rows[-1]['time'])['events'][0]
    retest=append(rows,e['triggerPrice']+1,e['boundary'],e['triggerPrice']+2)
    failure=append(retest,e['invalidationPrice']-2,e['invalidationPrice']-3,e['boundary'])
    p=analyze(failure,'T',failure[-2]['time'],True)
    assert [x['eventType'] for x in p['events'] if x['patternId']==e['patternId']]==['confirmed','retested']
    full=analyze(failure,'T',failure[-1]['time'])
    events=[x for x in full['events'] if x['patternId']==e['patternId']]
    assert [x['eventType'] for x in events]==['confirmed','retested','failed']
    assert all(x['geometry']==e['geometry'] for x in events)


def test_tie_pivot_right_side_is_not_available_early():
    rows=flag_rows()
    hi,lo=pivots(rows,40)
    assert all(i<=38 for i,_ in hi+lo)
    rows[37]['high']=rows[36]['high']
    hi,_=pivots(rows,39)
    assert not any(i==36 for i,_ in hi)


def test_source_revision_preserves_original_polygon_and_no_duplicate_after_restart(tmp_path):
    path=tmp_path/'f.db';store=MarketStore(path);rows=flag_rows();p=payload(rows)
    p['fetchedAt']='2026-03-01T22:00:00+00:00'
    now=datetime(2026,3,1,22,tzinfo=timezone.utc)
    first=svc.evaluate(p,store,now,family='flag');e=first['recentEvents'][0]
    snap=store.pattern_snapshot(e['basisSnapshotId']);store.close();store=MarketStore(path)
    svc.evaluate(p,store,now,family='flag');assert len(store.pattern_events())==1
    changed=deepcopy(p);changed['candles'][-1].update(close=116,open=116);changed['dataRevision']=revision(changed['candles'])
    svc.evaluate(changed,store,now,family='flag')
    assert store.pattern_events()[-1]['eventType']=='revised'
    assert store.pattern_snapshot(e['basisSnapshotId'])==snap and snap['event']['geometry']==e['geometry']
    store.close()


def test_later_nonbreak_wicks_cannot_keep_invalid_channel_alive():
    rows=flag_rows(breakout=False,adjustment=16)
    base=analyze(rows[:46],'T',rows[45]['time'])
    ident=base['timeline'][-1]['patterns'][0]['patternId']
    for r in rows[-4:]:r['high']=200
    rows=append(rows,118,112,119)
    out=analyze(rows,'T',rows[-1]['time'])
    assert not any(e['patternId']==ident for e in out['events'])
    assert any(p['patternId']==ident and p['status']=='failed' for p in out['timeline'][-1]['patterns'])


def test_flag_api_cached_read_and_family_isolation(monkeypatch,tmp_path):
    import json
    from types import SimpleNamespace
    import market_cache
    from test_analysis_jobs import handler
    store=MarketStore(tmp_path/'f.db');p=payload(flag_rows())
    p['fetchedAt']='2026-03-01T22:00:00+00:00'
    svc.evaluate(p,store,datetime(2026,3,1,22,tzinfo=timezone.utc),family='flag')
    monkeypatch.setattr(svc,'flags_enabled',lambda:True);monkeypatch.setattr(svc,'enabled',lambda:False)
    monkeypatch.setattr(market_cache,'enabled',lambda:True)
    monkeypatch.setattr(market_cache,'services',lambda:SimpleNamespace(store=store))
    import serve_dashboard
    monkeypatch.setattr(serve_dashboard,'market_lookup',lambda *a,**k:pytest.fail('cached Flag API must not collect'))
    h=handler('/api/patterns?symbol=TEST&kind=flag');assert svc.handle(h)
    out=json.loads(h.wfile.getvalue());assert h.status==200 and out['events'][0]['type']=='bull-flag'
    h=handler('/api/patterns?symbol=TEST');assert svc.handle(h) and h.status==503
    assert store.pattern_recent('TEST',rule='horizontal-d-v1')==[]
    assert store.pattern_recent('TEST',rule=RULE)[0]['type']=='bull-flag'
    store.close()
