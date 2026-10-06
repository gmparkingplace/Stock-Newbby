"""Frequency audit must preserve its input and separate repeated bars from new episodes."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sqlite3

spec=importlib.util.spec_from_file_location('strategy_audit',Path(__file__).resolve().parents[1]/'tools/audit-strategies.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


def payload():
    times=['2026-07-01','2026-07-02','2026-10-01','2026-10-02','2026-10-05']
    state=[]
    for i,t in enumerate(times):
        state.append(dict(sigA='entry' if i==3 else 'none',sigB='none',
            sigC='entry' if i<2 else 'exit' if i==2 else 'none',
            sigF='entry' if i<2 or i==4 else 'exit' if i==2 else 'none',
            rsi14=50,don_hi=110,don_lo=90))
    return dict(symbol='TEST',candles=[dict(time=t,close=100) for t in times],state=state,
        lines={'sma60':[dict(time=t,value=95) for t in times]},
        fetchedAt='2026-10-05T15:00:00+00:00',lastConfirmedTime='2026-10-02')


def test_frequency_window_excludes_pending_and_retains_carry_in():
    p=payload();before=deepcopy(p);r=audit.summarize(p,True)
    assert r['from']=='2026-07-02' and r['bars']==3
    assert r['entry']==dict(A=1,B=0,C=1,F=1)
    assert r['newEntryEpisodes']['C']==0 and r['carryInEpisodes']['C']==1
    assert r['pairEntry']['C+F']==1 and r['fEntryOutsideC']==0
    assert p==before


def test_invalid_or_unconfirmed_history_is_excluded_not_counted_as_zero_signals():
    p=payload();p['lastConfirmedTime']=None
    assert audit.summarize(p)['excluded']=='no-confirmation-basis'
    p=payload();p['state'].pop()
    assert audit.summarize(p)['excluded']=='unaligned-bars-state'
    p=payload();p['lastConfirmedTime']='2026-10-03'
    assert audit.summarize(p)['excluded']=='invalid-confirmation-basis'


def test_audit_opens_only_public_cache_read_only(tmp_path):
    path=tmp_path/'cache.db';db=sqlite3.connect(path)
    db.execute('create table entries(key text primary key,value text not null)')
    db.execute('insert into entries values(?,?)',('toss|TEST|D|adjusted|v1',json.dumps(payload())))
    db.execute('insert into entries values(?,?)',('monitor|settings-v1','{}'))
    db.commit();db.close();before=sha256(path.read_bytes()).hexdigest()
    report=audit.analyze(path)
    assert len(report['samples'])==1 and report['groups']['stock-D']['recent']['entry']['C']==1
    assert sha256(path.read_bytes()).hexdigest()==before
