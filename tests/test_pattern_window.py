from copy import deepcopy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pattern_window import start,within,project
from market_store import MarketStore
from pattern_service import visible_events,result_key


def test_calendar_month_end_and_year_boundary():
    assert start('2026-05-31')=='2026-02-28'
    assert start('2024-05-31')=='2024-02-29'
    assert start('2026-01-31')=='2025-10-31'


def test_structure_start_and_future_event_filter():
    assert within(dict(anchorTime='2026-06-07',confirmedBarTime='2026-09-07'),'2026-09-07')
    assert not within(dict(structureStartTime='2026-06-06',confirmedBarTime='2026-09-07'),'2026-09-07')
    assert not within(dict(poleStartTime='2026-06-06',adjustmentStartTime='2026-06-09',confirmedBarTime='2026-09-07'),'2026-09-07')
    assert not within(dict(anchorTime='2026-07-01',confirmedBarTime='2026-09-08'),'2026-09-07')


def test_project_keeps_original_bookkeeping_and_archive():
    old=dict(anchorTime='2026-06-06',confirmedBarTime='2026-07-01')
    good=dict(anchorTime='2026-06-07',confirmedBarTime='2026-09-07')
    result=dict(timeline=[dict(barTime='2026-06-06',patterns=[]),dict(barTime='2026-09-07',patterns=[dict(structureStartTime='2026-06-06'),dict(structureStartTime='2026-06-07')])],events=[old,good],recentEvents=[old,good],trackedEvents={'old':old},barHashes={'old':'hash'})
    before=deepcopy(result);out=project(result)
    assert result==before and 'trackedEvents' not in out
    assert out['events']==[good] and out['recentEvents']==[good]
    assert len(out['timeline'])==1 and len(out['timeline'][0]['patterns'])==1
    assert out['window']['start']=='2026-06-07'


def test_stock_references_and_stored_snapshot_unchanged(tmp_path):
    store=MarketStore(tmp_path/'cache.sqlite3')
    old=dict(eventId='old',symbol='AAPL',ruleVersion='triangle-d-v1',anchorTime='2026-06-06',confirmedBarTime='2026-08-01',basisSnapshotId='snap')
    recent={**old,'eventId':'new','anchorTime':'2026-06-07','basisSnapshotId':'snap2'}
    other={**old,'symbol':'MSFT','eventId':'other','basisSnapshotId':'snap3'}
    store.pattern_publish(result_key('AAPL',{},'triangle'),{'symbol':'AAPL','timeline':[{'barTime':'2026-09-07'}]},[(old,dict(snapshotId='snap',event=old)),(recent,dict(snapshotId='snap2',event=recent))])
    store.pattern_publish(result_key('MSFT',{},'triangle'),{'symbol':'MSFT','timeline':[{'barTime':'2026-08-01'}]},[(other,dict(snapshotId='snap3',event=other))])
    shown=visible_events(store,store.pattern_events(with_symbol=True))
    assert [e['eventId'] for e in shown]==['new','other']
    assert store.pattern_snapshot('snap')['event']==old
    assert len(store.pattern_events())==3
    store.close()


def test_event_api_filters_window_advances_cursor_and_keeps_id_lookup(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import pattern_service as svc
    import market_cache,analysis_jobs
    store=MarketStore(tmp_path/'cache.sqlite3')
    old=dict(eventId='old',symbol='AAPL',ruleVersion='triangle-d-v1',anchorTime='2026-06-06',confirmedBarTime='2026-08-01',basisSnapshotId='snap')
    store.pattern_publish(result_key('AAPL',{},'triangle'),dict(symbol='AAPL',timeline=[dict(barTime='2026-09-07')]),[(old,dict(snapshotId='snap',event=old))])
    monkeypatch.setenv('CHART_TRIANGLE_PATTERNS','1');monkeypatch.setattr(market_cache,'enabled',lambda:True)
    monkeypatch.setattr(market_cache,'services',lambda:SimpleNamespace(store=store))
    monkeypatch.setattr(analysis_jobs,'_reply',lambda h,status,data:(status,data))
    h=SimpleNamespace(path='/api/events?symbol=AAPL',command='GET',headers={'Host':'127.0.0.1:8735'},server=SimpleNamespace(server_port=8735))
    code,data=svc.handle(h);assert code==200 and data==dict(events=[],nextCursor=1)
    h.path='/api/events/old';code,data=svc.handle(h);assert code==200 and data==old
    h.path='/api/snapshots/snap';code,data=svc.handle(h);assert code==200 and data['event']==old
    store.close()


def test_old_correction_does_not_displace_recent_event_limit(tmp_path):
    store=MarketStore(tmp_path/'cache.sqlite3')
    recent=dict(eventId='recent',symbol='AAPL',ruleVersion='triangle-d-v1',anchorTime='2026-07-01',confirmedBarTime='2026-08-01',basisSnapshotId='s1')
    old={**recent,'eventId':'old-correction','anchorTime':'2026-06-06','basisSnapshotId':'s2'}
    store.pattern_publish(result_key('AAPL',{},'triangle'),dict(symbol='AAPL',timeline=[dict(barTime='2026-09-07')]),[(recent,dict(snapshotId='s1')),(old,dict(snapshotId='s2'))])
    assert store.pattern_recent('AAPL',limit=1)[0]['eventId']=='old-correction'
    assert store.pattern_recent('AAPL',limit=1,reference='2026-09-07')[0]['eventId']=='recent'
    assert store.pattern_event('old-correction')==old
    store.close()
