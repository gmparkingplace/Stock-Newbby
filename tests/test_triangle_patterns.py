"""Three triangle types, actual breakout directions, causal geometry and durability."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from triangle_fixture import triangle_rows
from triangle_patterns import analyze, RULE
from test_horizontal_patterns import append,payload
from market_store import MarketStore,revision,epoch
import pattern_service as svc


@pytest.mark.parametrize('kind',['ascending','descending','symmetrical'])
@pytest.mark.parametrize('direction',['up','down'])
def test_types_and_both_actual_directions(kind,direction):
    rows=triangle_rows(kind,direction);out=analyze(rows,'T',rows[-1]['time'])
    events=[e for e in out['events'] if e['eventType']=='confirmed'];assert len(events)==1
    e=events[0];assert e['type']==kind+'-triangle' and e['direction']==direction and e['contactCount']>=5
    assert e['convergenceRatio']<=.6 and e['apexRemainingBars']>0
    assert len(e['geometry']['points'])==3 and e['geometry']['points'][1]['logicalOffset']>e['structureBars']-1
    assert e['triggerPrice']==(e['upTrigger'] if direction=='up' else e['downTrigger'])
    assert e['rvol20Previous']==4


@pytest.mark.parametrize('kind',['ascending','descending','symmetrical'])
def test_each_prefix_identical_and_future_extremes_cannot_rewrite(kind):
    rows=triangle_rows(kind);full=analyze(rows,'T',rows[-1]['time'])
    for n in range(30,len(rows)+1):
        part=analyze(rows[:n],'T',rows[n-1]['time'])
        assert full['timeline'][:n]==part['timeline']
        assert [e for e in full['events'] if e['confirmedBarTime']<=rows[n-1]['time']]==part['events']
    ext=append(rows,1000,1,1001,999999);out=analyze(ext,'T',ext[-1]['time'])
    assert out['timeline'][:len(rows)]==full['timeline']


def test_provisional_direction_no_event_and_no_new_pivot():
    rows=triangle_rows('ascending','down');cut=rows[-2]['time']
    out=analyze(rows,'T',cut,True);assert not out['events']
    p=out['timeline'][-1]['patterns'][0];assert p['status']=='breakout-pending' and p['direction']=='down' and p['triggerPrice']==p['downTrigger']
    assert all(t<=rows[-3]['time'] for t in p['pivotHighTimes']+p['pivotLowTimes'])
    assert analyze(rows,'T',cut,False)['timeline'][-1]['patterns'][0]['status']=='paused'


@pytest.mark.parametrize('mode',['flat','parallel','no-contact','unknown','two-sided'])
def test_negative_structures(mode):
    rows=triangle_rows();cut=rows[-1]['time']
    if mode=='flat':
        for r in rows:r.update(open=100,high=101,low=99,close=100)
    elif mode=='parallel':rows=triangle_rows(step=0.00001)
    elif mode=='no-contact':
        for j,r in enumerate(rows[30:]):r.update(open=110+j*.01,high=110.5+j*.01,low=109.5+j*.01,close=110+j*.01)
    elif mode=='unknown':cut=None
    else:rows[-1].update(low=90,high=130)
    assert not analyze(rows,'T',cut)['events']


def test_apex_expiration_and_maximum_sixty_bars():
    rows=triangle_rows('symmetrical',length=34,breakout=False)
    out=analyze(rows,'T',rows[-1]['time']);assert not out['events']
    assert any(p.get('reason')=='apex-reached' for t in out['timeline'] for p in t['patterns'])
    rows=triangle_rows(length=63,step=.08,width=8,breakout=False)
    out=analyze(rows,'T',rows[-1]['time']);assert not out['events']
    assert any(p.get('reason')=='structure-over-60' for t in out['timeline'] for p in t['patterns'])


def test_fixed_breakout_then_retest_failure_and_no_unconfirmed_failure():
    rows=triangle_rows();e=analyze(rows,'T',rows[-1]['time'])['events'][0]
    retest=append(rows,e['triggerPrice']+1,e['boundary'],e['triggerPrice']+2)
    failed=append(retest,e['invalidationPrice']-2,e['invalidationPrice']-3,e['upperPrice'])
    out=analyze(failed,'T',failed[-1]['time']);assert [x['eventType'] for x in out['events']]==['confirmed','retested','failed']
    assert all(x['geometry']==e['geometry'] for x in out['events'])
    assert [x['eventType'] for x in analyze(failed,'T',retest[-1]['time'],True)['events']]==['confirmed','retested']


def test_persistence_and_correction_keep_original_triangle(tmp_path):
    rows=triangle_rows();data=payload(rows);data.update(symbol='AAPL',fetchedAt=rows[-1]['time']+'T22:00:00+00:00')
    now=datetime.fromisoformat(data['fetchedAt']);store=MarketStore(tmp_path/'cache.sqlite3')
    one=svc.evaluate(data,store,now,family='triangle');e=one['events'][0];old=store.pattern_snapshot(e['basisSnapshotId'])
    store.close();store=MarketStore(tmp_path/'cache.sqlite3');svc.evaluate(data,store,now,family='triangle')
    assert len(store.pattern_events())==1
    revised=deepcopy(data);revised['candles'][-1].update(close=112,high=118,low=111);revised.update(dataRevision=revision(revised['candles']),fetchedAt=rows[-1]['time']+'T23:00:00+00:00')
    svc.evaluate(revised,store,datetime.fromisoformat(revised['fetchedAt']),family='triangle')
    assert any(x['eventType']=='revised' for x in store.pattern_events())
    assert store.pattern_snapshot(e['basisSnapshotId'])==old
    store.close()


def test_family_key_and_read_api_no_source_collection(tmp_path,monkeypatch):
    import market_cache,analysis_jobs
    from types import SimpleNamespace
    store=MarketStore(tmp_path/'cache.sqlite3');data=payload(triangle_rows());data.update(symbol='AAPL',fetchedAt='2026-03-08T22:00:00+00:00')
    svc.evaluate(data,store,datetime.fromisoformat(data['fetchedAt']),family='triangle')
    monkeypatch.setenv('CHART_TRIANGLE_PATTERNS','1');monkeypatch.setattr(market_cache,'enabled',lambda:True)
    monkeypatch.setattr(market_cache,'services',lambda:SimpleNamespace(store=store))
    h=SimpleNamespace(path='/api/patterns?symbol=AAPL&tf=D&kind=triangle',command='GET',headers={'Host':'127.0.0.1:8735'},server=SimpleNamespace(server_port=8735))
    monkeypatch.setattr(analysis_jobs,'_reply',lambda h,status,result:(status,result))
    code,out=svc.handle(h);assert code==200 and out['ruleVersion']==RULE
    assert store.pattern_result(svc.result_key('AAPL',{},'flag')) is None
    assert not out['provisionalEligible']
    store.close()


def test_headless_monitor_records_triangle_and_filters_families(tmp_path,monkeypatch):
    from monitor_service import MonitorService
    rows=triangle_rows('ascending','down');data=payload(rows);data.update(symbol='AAPL',fetchedAt=rows[-1]['time']+'T22:00:00+00:00')
    now=epoch(data['fetchedAt']);store=MarketStore(tmp_path/'cache.sqlite3');calls=[]
    monkeypatch.setenv('CHART_TRIANGLE_PATTERNS','1')
    def collect(code,**kwargs):
        calls.append(code);data['triangleAnalysis']=svc.evaluate(data,store,datetime.fromtimestamp(now,timezone.utc),family='triangle');return data
    session=lambda code,t:dict(state='closed',sessionDate=rows[-1]['time'],lastSessionEnd=rows[-1]['time']+'T21:00:00+00:00',nextTransitionAt=rows[-1]['time']+'T23:00:00+00:00')
    worker=MonitorService(store,collect,session,lambda:now);worker.configure([dict(symbol='AAPL',rules=['triangle'])],0);worker.control('start');worker.step()
    events=worker.events()['events'];assert len(events)==1 and events[0]['direction']=='down'
    assert worker.status()['items'][0]['status']=='confirmed-history'
    assert store.pattern_snapshot(events[0]['basisSnapshotId'])['event']['geometry']['kind']=='triangle'
    worker.close();worker=MonitorService(store,collect,session,lambda:now);worker.step()
    assert len(calls)==1 and worker.events()['events']==events
    worker.close();store.close()


def test_sixtieth_bar_allowed_sixty_first_expires():
    rows=triangle_rows(length=61,step=.08,width=8)
    out=analyze(rows,'T',rows[-1]['time']);assert len(out['events'])==1 and out['events'][0]['structureBars']==60
    rows=triangle_rows(length=62,step=.08,width=8)
    out=analyze(rows,'T',rows[-1]['time']);assert not out['events']
    assert out['timeline'][-1]['patterns'][0]['reason']=='structure-over-60'


def test_monitor_preset_upgrade_is_once_and_custom_rules_remain(tmp_path,monkeypatch):
    from monitor_service import MonitorService
    store=MarketStore(tmp_path/'cache.sqlite3')
    session=lambda *args:dict(state='unknown')
    w=MonitorService(store,lambda *args:None,session);w.configure([dict(symbol='AAPL'),dict(symbol='MSFT',rules=['flag'])],0);w.close()
    monkeypatch.setenv('CHART_TRIANGLE_PATTERNS','1');w=MonitorService(store,lambda *args:None,session)
    items=w.status()['items'];assert items[0]['rules']==['flag','horizontal','triangle'] and items[1]['rules']==['flag']
    w.configure([dict(symbol='AAPL',rules=['flag','horizontal'])],w.state['configRevision']);w.close()
    w=MonitorService(store,lambda *args:None,session);assert w.status()['items'][0]['rules']==['flag','horizontal']
    w.close();store.close()


def test_disabled_triangle_only_monitor_does_not_collect(tmp_path,monkeypatch):
    from monitor_service import MonitorService
    monkeypatch.setenv('CHART_TRIANGLE_PATTERNS','0')
    store=MarketStore(tmp_path/'cache.sqlite3');calls=[];now=epoch('2026-03-09T15:00:00+00:00')
    session=lambda *args:dict(state='open',sessionDate='2026-03-09',nextTransitionAt='2026-03-09T21:00:00+00:00')
    worker=MonitorService(store,lambda *args,**kwargs:calls.append(args),session,lambda:now)
    worker.configure([dict(symbol='AAPL',rules=['triangle'])],0);worker.control('start');worker.step()
    assert not calls and worker.status()['items'][0]['status']=='rules-disabled'
    assert epoch(worker.state['runtime']['AAPL']['nextDueAt'])==now+60
    worker.close();store.close()
