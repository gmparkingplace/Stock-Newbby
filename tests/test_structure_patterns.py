"""Double top/bottom and head-and-shoulders structure pattern regressions."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import structure_patterns
from structure_fixture import double_top, double_bottom, head_shoulders, inverse_head_shoulders
from geometry_check import self_intersects as _self_intersects


def types(rows, timeframe='D'):
    out = structure_patterns.analyze(rows, 'AAPL', rows[-1]['time'], timeframe=timeframe)
    return [e['type'] for e in out['events']], out


@pytest.mark.parametrize('builder,expected', [
    (double_top, 'double-top'),
    (double_bottom, 'double-bottom'),
    (head_shoulders, 'head-shoulders'),
    (inverse_head_shoulders, 'inverse-head-shoulders'),
])
def test_each_structure_is_confirmed(builder, expected):
    kinds, out = types(builder())
    assert expected in kinds
    assert out['timeline'][-1]['status'] == 'ready'
    event = next(e for e in out['events'] if e['type'] == expected)
    assert event['eventType'] == 'confirmed'
    assert event['geometry']['points']
    assert event['triggerPrice'] == event['boundary']


def test_unconfirmed_structure_emits_no_event():
    rows = double_top(confirmed=False)
    out = structure_patterns.analyze(rows, 'AAPL', rows[-1]['time'])
    assert out['events'] == []


def test_rule_version_and_timeframe():
    rows = double_top()
    out = structure_patterns.analyze(rows, 'AAPL', rows[-1]['time'])
    assert out['ruleVersion'] == 'structure-d-v2'
    assert out['timeframe'] == 'D'


def test_unsupported_timeframe_rejected():
    rows = double_top()
    with pytest.raises(ValueError, match='unsupported-pattern-timeframe'):
        structure_patterns.analyze(rows, 'AAPL', rows[-1]['time'], timeframe='W')


def test_structure_attaches_and_publishes(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import market_cache
    import pattern_service
    from market_store import MarketStore
    store = MarketStore(tmp_path / 'struct.sqlite3')
    monkeypatch.setattr(market_cache, 'enabled', lambda: True)
    monkeypatch.setattr(market_cache, 'services', lambda: SimpleNamespace(store=store))
    for name in ['enabled', 'flags_enabled', 'triangles_enabled', 'structures_enabled']:
        monkeypatch.setattr(pattern_service, name, lambda: True)
    try:
        rows = double_top()
        payload = dict(symbol='AAPL', tf='D', fetchedAt='2026-10-18T20:00:00+00:00',
                       candles=rows, dataRevision='rev', source='yfinance',
                       marketSession={'state': 'open', 'sessionDate': '2026-01-18'},
                       lastConfirmedTime=rows[-1]['time'], snapshotEligible=True,
                       lastError=None, stale=False)
        out = pattern_service.attach(payload)
        assert out['structureAnalysis']['sourceStatus'] == 'ready'
        assert any(e['type'] == 'double-top' for e in out['structureAnalysis']['events'])
        assert out['structureAnalysis']['ruleVersion'] == 'structure-d-v2'
    finally:
        store.close()


@pytest.mark.parametrize('builder,expected', [
    (double_top, 'double-top'),
    (double_bottom, 'double-bottom'),
    (head_shoulders, 'head-shoulders'),
    (inverse_head_shoulders, 'inverse-head-shoulders'),
])
def test_geometry_polygon_does_not_self_intersect(builder, expected):
    rows = builder()
    out = structure_patterns.analyze(rows, 'AAPL', rows[-1]['time'])
    event = next(e for e in out['events'] if e['type'] == expected)
    points = event['geometry']['points']
    assert not _self_intersects(points, [r['time'] for r in rows]), points
    # 위쪽 경로가 먼저, 목선이 뒤에 온다: 목선 두 점의 시간이 역순이 아니어야 한다.
    assert points[-1]['price'] == points[-2]['price'] or event['geometry']['kind'].startswith('head')
