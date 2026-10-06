"""Deterministic P2 replay, revisions, SQLite migration and zero-collection reads."""
from copy import deepcopy
from datetime import date, timedelta, datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from horizontal_patterns import analyze, settings
from market_store import MarketStore, revision
import pattern_service as svc


def bars(close=140, n=24):
    rows = [dict(time=(date(2026,1,1)+timedelta(days=i)).isoformat(),open=100,high=101,low=99,close=100,volume=100) for i in range(n)]
    rows[-1].update(close=close,high=max(101,close+1),low=min(99,close-1),volume=240)
    return rows


def append(rows,close,low,high,volume=100):
    return rows+[dict(time=(date.fromisoformat(rows[-1]['time'])+timedelta(days=1)).isoformat(),open=close,high=high,low=low,close=close,volume=volume)]


def payload(rows):
    return dict(symbol='TEST',name='Test',tf='D',candles=rows,dataRevision=revision(rows),fetchedAt='2026-02-01T22:00:00+00:00',
                source='fixture',marketSession={'state':'closed'},confirmedPolicy='market-calendar',lastConfirmedTime=rows[-1]['time'])


NOW=datetime(2026,2,1,22,0,1,tzinfo=timezone.utc)

@pytest.mark.parametrize('close,direction',[(140,'up'),(60,'down')])
def test_crossings_and_volume_prior20(close,direction):
    rows=bars(close)
    out=analyze(rows,'TEST',rows[-1]['time'])
    assert len(out['events'])==1
    e=out['events'][0]
    assert e['direction']==direction and e['rvol20Previous']==2.4 and e['volumeEvidence']=='volume-confirmed'
    assert e['boundary']==(101 if direction=='up' else 99)
    assert e['atr14Previous']==2
    assert e['triggerPrice']==(101.2 if direction=='up' else 98.8)


def test_provisional_and_paused_never_create_events():
    rows=bars()
    for eligible,expected in [(True,'breakout-pending'),(False,'paused')]:
        out=analyze(rows,'TEST',rows[-2]['time'],eligible)
        assert out['events']==[] and out['timeline'][-1]['levels'][0]['status']==expected


def test_prefix_invariance_future_does_not_change_events():
    rows=bars();extended=append(append(rows,142,100,144),98,97,141)
    first=analyze(rows,'TEST',rows[-1]['time'])
    full=analyze(extended,'TEST',extended[-1]['time'])
    assert full['timeline'][:len(rows)]==first['timeline']
    assert [e for e in full['events'] if e['confirmedBarTime']<=rows[-1]['time']]==first['events']
    e=first['events'][0];followers=[x for x in full['events'] if x['patternId']==e['patternId']]
    assert [x['eventType'] for x in followers]==['confirmed','retested','failed']
    assert all(x['boundary']==101 and x['atr14Previous']==2 for x in followers)


def test_failed_wins_over_retest_and_provisional_failure_is_ignored():
    rows=bars();nextrows=append(rows,98,97,144)
    e=analyze(rows,'TEST',rows[-1]['time'])['events'][0]
    out=analyze(nextrows,'TEST',rows[-1]['time'],True)
    assert [x['eventType'] for x in out['events'] if x['patternId']==e['patternId']]==['confirmed']
    full=analyze(nextrows,'TEST',nextrows[-1]['time'])
    assert [x['eventType'] for x in full['events'] if x['patternId']==e['patternId']]==['confirmed','failed']


def test_low_volume_does_not_hide_crossing_and_zero_volume_is_unknown():
    rows=bars();rows[-1]['volume']=90
    assert analyze(rows,'T',rows[-1]['time'])['events'][0]['volumeEvidence']=='volume-insufficient'
    for row in rows[:-1]:row['volume']=0
    assert analyze(rows,'T',rows[-1]['time'])['events'][0]['rvol20Previous'] is None


def test_rolling_boundary_drop_without_price_cross_is_not_event():
    rows=bars(100,45)
    rows[21].update(high=150)
    for r in rows[22:]:r.update(open=120,close=120,high=121,low=119)
    # At index42 the old high rolls out, ATR also changes, price stayed 120.
    out=analyze(rows,'T',rows[-1]['time'])
    assert not any(e['direction']=='up' and e['confirmedBarTime']==rows[42]['time'] for e in out['events'])


def test_user_line_direction_and_no_repeated_cross_on_hold():
    rows=bars();rows=append(rows,145,140,146)
    out=analyze(rows,'T',rows[-1]['time'],levels={'resistance':110,'support':90})
    fixed=[e for e in out['events'] if e['type']=='user-resistance']
    assert len(fixed)==1 and fixed[0]['boundary']==110


def test_follow_window_is_ten_bars():
    rows=bars();ident=analyze(rows,'T',rows[-1]['time'])['events'][0]['patternId']
    for _ in range(10):rows=append(rows,140,130,145)
    rows=append(rows,90,89,140)
    out=analyze(rows,'T',rows[-1]['time'])
    assert [e['eventType'] for e in out['events'] if e['patternId']==ident]==['confirmed']


@pytest.mark.parametrize('levels',[{'support':0},{'support':True},{'support':float('nan')},{'support':200,'resistance':100},{'other':1}])
def test_bad_settings(levels):
    with pytest.raises(ValueError):settings(levels)


def test_invalid_ohlcv_and_duplicate_order():
    rows=bars();rows[-1]['low']=150
    with pytest.raises(ValueError):analyze(rows,'T',None)
    rows=bars();rows[-1]['time']=rows[-2]['time']
    with pytest.raises(ValueError):analyze(rows,'T',None)
    assert analyze(bars(n=10),'T',None)['timeline'][-1]['status']=='insufficient-data'


def test_restart_dedup_and_snapshot_immutable(tmp_path):
    path=tmp_path/'cache.sqlite3';store=MarketStore(path)
    p=payload(bars());p['nextConfirmationAt']='2026-01-24T21:30:00+00:00'
    out=svc.evaluate(p,store,NOW);event=out['recentEvents'][0]
    assert event['barEndAt']=='2026-01-24T21:00:00+00:00'
    assert event['confirmedAt']==p['fetchedAt']
    snapshot=store.pattern_snapshot(event['basisSnapshotId'])
    for _ in range(3):svc.evaluate(p,store,NOW)
    assert len(store.pattern_events())==1
    store.close();store=MarketStore(path)
    svc.evaluate(p,store,NOW)
    assert store.pattern_events()[0]['eventId']==event['eventId']
    newer=payload(append(p['candles'],145,130,150));svc.evaluate(newer,store,NOW)
    assert store.pattern_snapshot(event['basisSnapshotId'])==snapshot
    assert snapshot['candles'][-1]['time']==event['confirmedBarTime']
    store.close()


def test_revisions_removal_and_restore_preserve_original(tmp_path):
    store=MarketStore(tmp_path/'c.db');initial=payload(bars())
    out=svc.evaluate(initial,store,NOW);event=out['recentEvents'][0]
    original=store.pattern_snapshot(event['basisSnapshotId'])
    changed=payload(bars(138));svc.evaluate(changed,store,NOW);svc.evaluate(changed,store,NOW)
    events=store.pattern_events();assert len(events)==2 and events[-1]['eventType']=='revised'
    assert events[-1]['before']['close']==140 and events[-1]['after']['close']==138
    corrected=store.pattern_snapshot(events[-1]['basisSnapshotId'])
    assert corrected['event']['close']==corrected['candles'][-1]['close']==138
    removed=payload(bars(100));svc.evaluate(removed,store,NOW)
    assert store.pattern_events()[-1]['after'] is None
    svc.evaluate(initial,store,NOW)
    assert len(store.pattern_events())==4 and store.pattern_events()[-1]['after']['close']==140
    assert store.pattern_snapshot(event['basisSnapshotId'])==original
    store.close()


def test_calendar_error_does_not_mark_failed_or_replace_good_result(tmp_path):
    store=MarketStore(tmp_path/'c.db');p=payload(bars());good=svc.evaluate(p,store,NOW)
    failed=payload(bars(90));failed['marketSession']={'state':'unknown'}
    out=svc.evaluate(failed,store,NOW)
    assert out['sourceStatus']=='paused' and len(store.pattern_events())==1
    assert store.pattern_result(svc.result_key('TEST',{}))['dataRevision']==good['dataRevision']
    store.close()


def test_snapshot_event_publish_rollback(tmp_path):
    store=MarketStore(tmp_path/'c.db')
    store.db.execute("CREATE TRIGGER reject_snapshot BEFORE INSERT ON pattern_snapshots BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):svc.evaluate(payload(bars()),store,NOW)
    assert store.pattern_events()==[] and store.pattern_result(svc.result_key('TEST',{})) is None
    store.close()


def test_schema_one_backed_up_with_wal_before_migration(tmp_path):
    path=tmp_path/'c.db'
    db=sqlite3.connect(path);db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE entries (key TEXT PRIMARY KEY,value TEXT NOT NULL)');db.execute("INSERT INTO entries VALUES ('fixture','{\"keep\":true}')")
    db.execute('PRAGMA user_version=1');db.commit()
    store=MarketStore(path)
    backup=sqlite3.connect(str(path)+'.schema1.bak')
    assert backup.execute('PRAGMA user_version').fetchone()[0]==1
    assert backup.execute("SELECT value FROM entries").fetchone()[0]=='{"keep":true}'
    assert store.get('fixture')=={'keep':True} and store.db.execute('PRAGMA user_version').fetchone()[0]==2
    store.close();backup.close();db.close()


def test_api_reads_no_market_lookup_settings_protected(monkeypatch,tmp_path):
    from test_analysis_jobs import handler
    import market_cache
    from analysis_jobs import SESSION_TOKEN
    store=MarketStore(tmp_path/'c.db');out=svc.evaluate(payload(bars()),store,NOW)
    monkeypatch.setattr(svc,'enabled',lambda:True);monkeypatch.setattr(market_cache,'enabled',lambda:True)
    monkeypatch.setattr(market_cache,'services',lambda:SimpleNamespace(store=store))
    import serve_dashboard
    monkeypatch.setattr(serve_dashboard,'market_lookup',lambda *a,**k:pytest.fail('cached API collected source'))
    def request(path,method='GET',headers=None,body=None):
        h=handler(path,method,headers,body);assert svc.handle(h)
        assert 'Access-Control-Allow-Origin' not in h.headers_written
        return h.status,json.loads(h.wfile.getvalue())
    assert request('/api/patterns?symbol=TEST')[1]['events']==out['events']
    e=request('/api/events?symbol=TEST')[1]['events'][0]
    snap=request('/api/snapshots/'+e['basisSnapshotId'])[1]
    assert snap['event']['close']==140
    assert request('/api/patterns?symbol=TEST&tf=W')[1]['sourceStatus']=='unsupported'
    assert request('/api/events?cursor=-1')[0]==400
    assert request('/api/events',headers={'Origin':'https://bad.example'})[0]==403
    assert request('/api/pattern-levels','POST',body={'symbol':'TEST','levels':{}})[0]==403
    assert request('/api/pattern-levels','POST',{'X-Chart-Session':SESSION_TOKEN},{'symbol':'TEST','levels':{'resistance':110}})[0]==200
    assert request('/api/patterns?symbol=TEST')[1]['sourceStatus']=='not-collected'
    store.close()


def test_first_eligible_cross_at_22_bars_and_precise_atr():
    rows=bars(n=22)
    out=analyze(rows,'T',rows[-1]['time'])
    assert len(out['events'])==1
    small=[dict(r,open=r['open']/10000,high=r['high']/10000,low=r['low']/10000,close=r['close']/10000) for r in rows]
    event=analyze(small,'T',small[-1]['time'])['events'][0]
    assert 0 < event['atr14Previous'] < .001 and event['triggerPrice'] > event['boundary']


def test_late_old_response_cannot_retract_new_snapshot(tmp_path):
    store=MarketStore(tmp_path/'c.db');old=payload(bars())
    new=payload(append(old['candles'],145,140,146));new['fetchedAt']='2026-02-01T22:00:01+00:00'
    svc.evaluate(new,store,NOW)
    out=svc.evaluate(old,store,NOW)
    assert out['sourceStatus']=='paused'
    assert store.pattern_result(svc.result_key('TEST',{}))['dataRevision']==new['dataRevision']
    assert not any(e['eventType']=='revised' for e in store.pattern_events())
    store.close()


def test_cached_before_close_not_promoted_and_stale_intraday_paused(tmp_path):
    store=MarketStore(tmp_path/'c.db');p=payload(bars())
    p['lastConfirmedTime']=p['candles'][-2]['time'];p['snapshotEligible']=True;p['marketSession']={'state':'open'}
    out=svc.evaluate(p,store,NOW)
    assert not out['events'] and out['timeline'][-1]['levels'][0]['status']=='breakout-pending'
    late=datetime(2026,2,1,22,3,tzinfo=timezone.utc)
    out=svc.evaluate(p,store,late)
    assert not out['events'] and out['timeline'][-1]['levels'][0]['status']=='paused'
    store.close()


def test_missing_confirmation_metadata_pauses_even_with_known_market(tmp_path):
    store=MarketStore(tmp_path/'c.db');p=payload(bars());p['lastConfirmedTime']=None
    assert svc.evaluate(p,store,NOW)['sourceStatus']=='paused'
    assert store.pattern_events()==[]
    store.close()


def test_concurrent_same_payload_publishes_event_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store=MarketStore(tmp_path/'c.db');p=payload(bars())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:svc.evaluate(p,store,NOW),range(16)))
    assert len(store.pattern_events())==1
    assert len({r['recentEvents'][0]['basisSnapshotId'] for r in results})==1
    store.close()


def test_attach_uses_existing_payload_only_and_failure_keeps_chart(monkeypatch,tmp_path):
    import market_cache
    store=MarketStore(tmp_path/'c.db');p=payload(bars())
    monkeypatch.setattr(svc,'enabled',lambda:True);monkeypatch.setattr(market_cache,'enabled',lambda:True)
    monkeypatch.setattr(market_cache,'services',lambda:SimpleNamespace(store=store))
    out=svc.attach(p);assert out['candles']==p['candles'] and out['patternAnalysis']['enabled']
    bad=deepcopy(p);bad['candles'][-1]['low']=200
    out=svc.attach(bad);assert out['candles']==bad['candles'] and out['patternAnalysis']['sourceStatus']=='error'
    for code in ('BTC-USD','^KS11'):
        assert svc.attach(dict(p,symbol=code))['patternAnalysis']['sourceStatus']=='unsupported'
    store.close()


def test_user_settings_do_not_duplicate_automatic_history(tmp_path):
    store=MarketStore(tmp_path/'c.db');p=payload(bars())
    svc.evaluate(p,store,NOW)
    store.put('pattern-levels|TEST',{'levels':{'resistance':110},'dataRevision':'settings1'})
    svc.evaluate(p,store,NOW)
    events=store.pattern_events()
    assert len([e for e in events if e['type']=='prior-20-high'])==1
    assert len([e for e in events if e['type']=='user-resistance'])==1
    store.close()


def test_repeated_result_event_references_existing_immutable_basis(tmp_path):
    store=MarketStore(tmp_path/'c.db');p=payload(bars())
    original=svc.evaluate(p,store,NOW)['events'][0]
    p['fetchedAt']='2026-02-01T22:00:01+00:00'
    again=svc.evaluate(p,store,NOW)['events'][0]
    assert again==original and store.pattern_snapshot(again['basisSnapshotId'])
    new=payload(append(p['candles'],145,140,146));new['fetchedAt']='2026-02-01T22:00:02+00:00'
    result=svc.evaluate(new,store,NOW)
    assert all(store.pattern_snapshot(e['basisSnapshotId']) for e in result['events'])
    assert len(store.pattern_events())==1
    store.close()


def test_removed_event_bar_revised_without_inventing_price(tmp_path):
    store=MarketStore(tmp_path/'c.db');p=payload(bars())
    original=svc.evaluate(p,store,NOW)['events'][0]
    newrows=append(p['candles'][:-1],145,140,146)
    newrows[-1]['time']=(date.fromisoformat(p['candles'][-1]['time'])+timedelta(days=1)).isoformat()
    svc.evaluate(payload(newrows),store,NOW)
    changed=next(e for e in store.pattern_events() if e['eventType']=='revised' and e['revisesEventId']==original['eventId'])
    assert changed['after'] is None and changed['close'] is None
    assert not store.pattern_snapshot(changed['basisSnapshotId'])['basisBarAvailable']
    store.close()
