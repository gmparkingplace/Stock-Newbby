"""Audit must catch bad evidence and leave the input cache unchanged."""
from copy import deepcopy
from datetime import datetime
import importlib.util
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

from market_store import MarketStore, revision
from pattern_service import evaluate
from test_horizontal_patterns import payload
from triangle_fixture import triangle_rows

spec = importlib.util.spec_from_file_location('pattern_audit', Path(__file__).resolve().parents[1]/'tools/audit-patterns.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def seeded(path):
    p = payload(triangle_rows())
    now = datetime.fromisoformat(p['fetchedAt'])
    store = MarketStore(path)
    store.put('toss|TEST|D|adjusted|test',p)
    evaluate(p,store,now,family='triangle')
    e = store.pattern_events()[0]
    snap = store.pattern_snapshot(e['basisSnapshotId'])
    store.close()
    return e,snap


def logical_contents(path):
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        return revision({t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in
                         ('entries','revisions','pattern_results','pattern_events','pattern_snapshots')})
    finally:
        db.close()


def test_audit_replay_never_changes_input_cache(tmp_path):
    path = tmp_path/'cache.db';seeded(path)
    before = logical_contents(path)
    report = audit.run(path)
    assert report['passed'] and report['evidenceChecked']==1
    assert report['newEventsAfterRepeatsRestartConcurrency']==0
    assert report['changedOriginalSnapshots']==0
    assert logical_contents(path)==before


def test_audit_rejects_non_crossing_and_future_pivot(tmp_path):
    e,snap = seeded(tmp_path/'cache.db')
    assert not audit.event_checks(e,snap)
    changed = deepcopy(snap)
    changed['candles'][-1]['close'] = e['triggerPrice']
    assert 'close-not-beyond-trigger' in audit.event_checks(e,changed)
    changed = deepcopy(e);changed['pivotHighTimes'] += [e['confirmedBarTime']]
    assert 'unconfirmed-pivot' in audit.event_checks(changed,snap)


def test_empty_cache_is_not_a_successful_validation(tmp_path):
    path = tmp_path/'empty.db';MarketStore(path).close()
    assert not audit.run(path)['passed']
