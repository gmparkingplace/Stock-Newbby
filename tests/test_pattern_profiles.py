"""Balanced thresholds expand geometry while preserving confirmation and version isolation."""
from copy import deepcopy
from datetime import datetime
import importlib.util
from pathlib import Path
import sqlite3
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from flag_fixture import flag_rows
from triangle_fixture import triangle_rows
import flag_patterns as flag
import triangle_patterns as triangle
from pattern_profiles import parameters,rule_version
from pattern_service import evaluate,visible_events
from market_store import MarketStore,revision
from test_horizontal_patterns import append,payload


def test_balanced_triangle_is_visible_earlier_without_unconfirmed_events():
    rows=triangle_rows(length=22,breakout=False)
    old=triangle.analyze(rows,'AAPL',rows[-1]['time'],profile='legacy')
    new=triangle.analyze(rows,'AAPL',rows[-1]['time'])
    assert not old['timeline'][-1]['patterns']
    assert new['timeline'][-1]['patterns'][0]['status']=='forming'
    assert not new['events'] and new['timeline'][-1]['patterns'][0]['contactCount']>=5
    # Four contacts allowed an unrelated warmup low to become a false triangle. Keep five.
    assert parameters()['triangle_contacts']==5


def test_thirtieth_flag_bar_allowed_and_thirty_first_expires():
    rows=flag_rows(adjustment=30,breakout=False)
    assert not flag.analyze(rows,'AAPL',rows[-1]['time'],profile='legacy')['timeline'][-1]['patterns']
    new=flag.analyze(rows,'AAPL',rows[-1]['time']);assert new['timeline'][-1]['patterns'][0]['adjustmentBars']==30
    valid=deepcopy(rows);valid[-1].update(open=118,close=118,high=119,low=112)
    assert len([e for e in flag.analyze(valid,'AAPL',valid[-1]['time'])['events'] if e['eventType']=='confirmed'])==1
    expired=append(rows,118,112,119);out=flag.analyze(expired,'AAPL',expired[-1]['time'])
    assert not out['events'];assert out['timeline'][-1]['patterns'][0]['reason']=='adjustment-over-30'


@pytest.mark.parametrize('engine,make',[(flag,flag_rows),(triangle,triangle_rows)])
def test_two_profiles_keep_price_confirmation_causal_and_versioned(engine,make):
    rows=make();frozen=deepcopy(rows)
    for profile in ['legacy','balanced']:
        full=engine.analyze(rows,'AAPL',rows[-1]['time'],profile=profile)
        before=engine.analyze(rows,'AAPL',rows[-2]['time'],True,profile=profile)
        assert not before['events']
        for n in range(30,len(rows)+1):
            part=engine.analyze(rows[:n],'AAPL',rows[n-1]['time'],profile=profile)
            assert full['timeline'][:n]==part['timeline']
        for e in full['events']:
            if e['eventType']=='confirmed':
                sign=1 if e['direction']=='up' else -1
                assert sign*(e['close']-e['triggerPrice'])>0
        ids=[e['eventId'] for e in full['events']];assert len(ids)==len(set(ids))
    old=engine.analyze(rows,'AAPL',rows[-1]['time'],profile='legacy')
    new=engine.analyze(rows,'AAPL',rows[-1]['time'])
    assert old['ruleVersion'].endswith('-v1') and new['ruleVersion'].endswith('-v2')
    assert {e['eventId'] for e in old['events']}.isdisjoint(e['eventId'] for e in new['events'])
    assert rows==frozen


def test_version_upgrade_keeps_original_snapshot_and_monitor_hides_legacy_duplicates(tmp_path):
    data=payload(flag_rows());data['symbol']='AAPL';store=MarketStore(tmp_path/'migration.sqlite3')
    old=flag.analyze(data['candles'],'AAPL',data['lastConfirmedTime'],profile='legacy')
    event=deepcopy(old['events'][0]);event['basisSnapshotId']='legacy-basis';snap=dict(snapshotId='legacy-basis',event=deepcopy(event))
    store.pattern_publish('flag|AAPL|D|flag-d-v1',old,[(event,snap)])
    new=evaluate(data,store,datetime.fromisoformat(data['fetchedAt']),family='flag')
    rows=store.pattern_events(with_symbol=True)
    assert len(rows)==2
    assert len(visible_events(store,rows,current_only=True))==1
    assert visible_events(store,rows,current_only=True)[0]['ruleVersion']=='flag-d-v2'
    assert store.pattern_snapshot('legacy-basis')==snap
    evaluate(data,store,datetime.fromisoformat(data['fetchedAt']),family='flag')
    assert len(store.pattern_events())==2
    assert all(e['ruleVersion']=='flag-d-v2' for e in new['recentEvents'])
    store.close()


def test_profile_comparison_uses_read_only_cache(tmp_path):
    path=tmp_path/'source.sqlite3';conn=sqlite3.connect(path);conn.execute('CREATE TABLE entries(key TEXT,value TEXT)')
    data=payload(triangle_rows(length=22,breakout=False));data['symbol']='AAPL'
    import json
    conn.execute('INSERT INTO entries VALUES(?,?)',('toss|AAPL|D|test',json.dumps(data)));conn.commit();conn.close()
    before=path.read_bytes()
    spec=importlib.util.spec_from_file_location('profile_audit',Path(__file__).resolve().parents[1]/'tools/audit-pattern-profiles.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.compare(path)
    assert len(result['samples'])==2 and path.read_bytes()==before
    assert result['groups']['stock-D-triangle']['balanced']['current']==1


def test_rule_contract_and_immutable_parameters():
    assert rule_version('flag','H4')=='flag-h4-v3'
    assert rule_version('triangle','H4')=='triangle-h4-v3'
    assert rule_version('flag','D')=='flag-d-v2'
    assert rule_version('flag','H4','legacy')=='flag-h4-v1'
    with pytest.raises(TypeError):parameters()['fit_atr']=99
    with pytest.raises(ValueError):parameters('unsupported')
