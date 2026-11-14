"""Regressions for the parallel structure evidence engine (design 2026-11-13).

Every test is offline: synthetic confirmed candles, no provider, no cache store.
"""
from datetime import date, timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import structure_evidence_v2 as evidence
import structure_lifecycle_v2 as engine
import structure_patterns
from pattern_math import atr14
from structure_fixture import (double_bottom, double_top, head_shoulders,
                               inverse_head_shoulders)


def bar(rows, o, c, h, l, v=100):
    rows.append(dict(time=(date(2026, 1, 1) + timedelta(days=len(rows))).isoformat(),
                     open=o, close=c, high=h, low=l, volume=v))


def warmup(rows, n=20, price=100, v=100):
    for _ in range(n):
        bar(rows, price, price, price + 1, price - 1, v)


def peak(rows, top, v=100):
    bar(rows, top - 2, top - 1, top - 1, top - 3, v)
    bar(rows, top - 1, top, top, top - 2, v)
    bar(rows, top - 1, top - 1, top - 1, top - 3, v)
    bar(rows, top - 2, top - 2, top - 1, top - 3, v)


def trough(rows, bottom, v=100):
    bar(rows, bottom + 2, bottom + 1, bottom + 3, bottom + 1, v)
    bar(rows, bottom + 1, bottom, bottom + 1, bottom, v)
    bar(rows, bottom + 1, bottom + 1, bottom + 3, bottom + 1, v)
    bar(rows, bottom + 2, bottom + 2, bottom + 3, bottom + 1, v)


def run(rows, index=None):
    cutoff = rows[-1]['time'] if index is None else rows[index]['time']
    subset = rows if index is None else rows[:index + 1]
    return engine.analyze(subset, 'AAPL', cutoff)


def pattern_of(out, kind):
    return next((p for p in out['patterns'] if p['type'] == kind), None)


def state_at(pattern, through):
    state = 'candidate'
    for event in pattern['events']:
        if event['effectiveBarTime'] <= through:
            state = event['snapshot']['phaseAfter']
    return state


P0_CASES = [
    (double_top, 'double-top', 95, 94.99, 94.98, 'down'),
    (double_bottom, 'double-bottom', 105, 105.01, 105.02, 'up'),
    (head_shoulders, 'head-shoulders', 97, 96.99, 96.98, 'down'),
    (inverse_head_shoulders, 'inverse-head-shoulders', 103, 103.01, 103.02, 'up'),
]


@pytest.mark.parametrize('builder,kind,neckline,first,last,direction', P0_CASES)
def test_existing_engine_confirms_between_neckline_and_trigger(builder, kind, neckline, first, last, direction):
    """P0: the shipped engine confirms while the displayed trigger is not crossed."""
    rows = builder()
    rows[-2]['close'] = first
    rows[-1]['close'] = last
    out = structure_patterns.analyze(rows, 'AAPL', rows[-1]['time'])
    event = next(e for e in out['events'] if e['type'] == kind)
    assert event['eventType'] == 'confirmed'
    crossed = event['close'] < event['triggerPrice'] if direction == 'down' else event['close'] > event['triggerPrice']
    assert not crossed


@pytest.mark.parametrize('builder,kind,neckline,first,last,direction', P0_CASES)
def test_new_engine_requires_the_displayed_trigger(builder, kind, neckline, first, last, direction):
    rows = builder()
    rows[-2]['close'] = first
    rows[-1]['close'] = last
    pattern = pattern_of(run(rows), kind)
    assert pattern['lifecycleState'] == 'candidate'
    assert pattern['confirmedAt'] is None
    assert not any(e['eventType'] == 'breakout-confirmed' for e in pattern['events'])


def test_trigger_keeps_full_precision():
    rows = double_top()
    pattern = pattern_of(run(rows), 'double-top')
    event = next(e for e in pattern['events'] if e['eventType'] == 'breakout-confirmed')
    assert event['snapshot']['triggerPrice'] == (
        event['snapshot']['neckline'] + (-1) * 0.1 * pattern['atr14Previous'])
    assert pattern['triggerPriceAtEvent'] == event['snapshot']['triggerPrice']


def test_boundary_equality_waits_for_the_next_bar():
    rows = double_top(confirmed=False)
    trigger = 95 - 0.1 * atr14(rows)[-1]
    bar(rows, trigger + 1, trigger, trigger + 1, trigger - 1)  # close exactly at trigger
    at_trigger = pattern_of(run(rows), 'double-top')
    assert at_trigger['lifecycleState'] == 'candidate'

    rows[-1]['close'] = trigger - 0.01  # just beyond
    beyond = pattern_of(run(rows), 'double-top')
    assert beyond['lifecycleState'] == 'confirmed'


def test_sloped_head_shoulders_neckline_uses_both_valleys():
    rows = []
    warmup(rows, 30)
    peak(rows, 104)
    trough(rows, 97)
    peak(rows, 108)
    trough(rows, 99)
    peak(rows, 104)
    bar(rows, 97, 96, 97, 95)
    bar(rows, 96, 95, 96, 94)
    pattern = pattern_of(run(rows), 'head-shoulders')
    assert pattern is not None
    points = pattern['neckline']['points']
    assert [p['price'] for p in points] == [97, 99]
    assert pattern['neckline']['flat'] is False
    assert len(pattern['geometry']['points']) == 5
    event = next(e for e in pattern['events'] if e['eventType'] == 'breakout-confirmed')
    assert event['snapshot']['triggerPrice'] == event['snapshot']['neckline'] - 0.1 * pattern['atr14Previous']


def test_candidate_needs_two_bars_after_the_right_pivot():
    rows = double_top()[:31]  # second peak has only one bar to its right
    out = run(rows)
    assert pattern_of(out, 'double-top') is None


def test_prefix_replay_matches_the_full_run():
    rows = double_top() + [dict(time=(date(2026, 1, 1) + timedelta(days=34 + k)).isoformat(),
                                open=94, close=93, high=95, low=92, volume=100) for k in range(5)]
    full = run(rows)
    cutoff = rows[33]['time']
    short = run(rows, 33)
    for kind in ('double-top',):
        full_pattern = pattern_of(full, kind)
        short_pattern = pattern_of(short, kind)
        assert full_pattern['patternId'] == short_pattern['patternId']
        assert state_at(full_pattern, cutoff) == short_pattern['lifecycleState']
        assert [e for e in full_pattern['events'] if e['effectiveBarTime'] <= cutoff] == short_pattern['events']


def test_future_extremes_do_not_rewrite_past_events():
    rows = double_top()
    cutoff = rows[-1]['time']
    before = run(rows)
    rows.append(dict(time=(date(2026, 1, 1) + timedelta(days=len(rows))).isoformat(),
                     open=95, close=200, high=200, low=94, volume=10 ** 6))
    after = run(rows)
    earlier = next(e for e in before['events'] if e['effectiveBarTime'] <= cutoff)
    matching = next(e for e in after['events'] if e['eventId'] == earlier['eventId'])
    assert matching == earlier
    assert pattern_of(before, 'double-top')['triggerPriceAtEvent'] == pattern_of(after, 'double-top')['triggerPriceAtEvent']


def test_tie_in_neckline_picks_the_earliest_bar():
    rows = []
    warmup(rows)
    peak(rows, 106)
    bar(rows, 96, 95, 96, 95)
    bar(rows, 96, 95, 96, 95)
    peak(rows, 106)
    bar(rows, 96, 94, 97, 93)
    bar(rows, 94, 93, 95, 92)
    pattern = pattern_of(run(rows), 'double-top')
    assert pattern['neckline']['anchorTimes'][0] == rows[24]['time']
    assert pattern['neckline']['anchorPrices'][0] == 95


def test_candidate_invalidation_uses_the_opposite_extreme():
    pattern = pattern_of(run(double_top(confirmed=False)), 'double-top')
    assert pattern['lifecycleState'] == 'candidate'
    assert pattern['invalidationPrice'] == 106 + 0.3 * pattern['atr14Previous']
    confirmed = pattern_of(run(double_top()), 'double-top')
    assert confirmed['invalidationPrice'] == (confirmed['neckline']['atEvaluation']
                                               + 0.3 * confirmed['atr14Previous'])


def test_failure_keeps_the_original_confirmation():
    rows = double_top()
    bar(rows, 105, 109, 110, 104)
    out = run(rows)
    pattern = pattern_of(out, 'double-top')
    assert pattern['lifecycleState'] == 'failed'
    kinds = [e['eventType'] for e in pattern['events']]
    assert 'breakout-confirmed' in kinds and 'breakout-failed' in kinds
    assert kinds.index('breakout-confirmed') < kinds.index('breakout-failed')


def test_retest_then_hold_requires_a_real_re_cross():
    rows = double_top()
    bar(rows, 95, 95, 96, 94)  # close back inside the published trigger
    pattern = pattern_of(run(rows), 'double-top')
    kinds = [e['eventType'] for e in pattern['events']]
    assert 'retest-started' in kinds and 'retest-held' not in kinds
    assert pattern['lifecycleState'] == 'retesting'
    bar(rows, 93, 93, 94, 92)  # close beyond the trigger again
    pattern = pattern_of(run(rows), 'double-top')
    kinds = [e['eventType'] for e in pattern['events']]
    assert 'retest-held' in kinds and pattern['lifecycleState'] == 'holding'


def test_staying_on_the_breakout_side_is_not_a_re_cross():
    rows = double_top()
    for _ in range(3):
        bar(rows, 93, 92, 94, 92)  # never returns inside the trigger
    pattern = pattern_of(run(rows), 'double-top')
    assert 'retest-held' not in [e['eventType'] for e in pattern['events']]
    assert pattern['lifecycleState'] == 'retesting'


def test_later_volume_does_not_rewrite_breakout_volume():
    rows = double_top()
    bar(rows, 94, 92, 94, 91, 500)
    pattern = pattern_of(run(rows), 'double-top')
    boost = next(e for e in pattern['events'] if e['eventType'] == 'volume-supported')
    assert boost['effectiveBarTime'] == rows[-1]['time']
    assert pattern['evidence']['breakoutVolume']['ratio'] == 1.0
    assert pattern['evidence']['latestVolume']['ratio'] == 5.0


def test_volume_unknown_zero_and_weak_are_distinct():
    cfg = engine.parameters()
    assert evidence.volume_ratio([dict(volume=0)] * 5, 4, cfg) == (None, 'unknown')
    assert evidence.volume_ratio([dict(volume=0)] * 21, 20, cfg) == (None, 'unknown')
    flat = [dict(volume=100)] * 20 + [dict(volume=0)]
    assert evidence.volume_ratio(flat, 20, cfg) == (0.0, 'weak')
    busy = [dict(volume=100)] * 20 + [dict(volume=200)]
    assert evidence.volume_ratio(busy, 20, cfg) == (2.0, 'supported')


def test_invalid_rows_and_unknown_cutoff_are_rejected():
    rows = double_top()
    rows[5]['high'] = 1
    with pytest.raises(ValueError, match='invalid-ohlcv'):
        run(rows)
    with pytest.raises(ValueError, match='invalid-confirmed-cutoff'):
        engine.analyze(double_top(), 'AAPL', '1999-01-01')


def test_candidate_expires_without_a_breakout():
    rows = []
    warmup(rows)
    peak(rows, 106)
    trough(rows, 95)
    peak(rows, 106)
    for _ in range(25):
        bar(rows, 100, 100, 101, 99)
    out = run(rows)
    expired = [p for p in out['patterns']
               if p['type'] == 'double-top' and p['lifecycleState'] == 'expired']
    assert expired and expired[0]['expiredBeforeConfirmation'] is True
    assert any(r['code'] == 'candidate-expired' for r in expired[0]['reasons'])


def test_flat_prior_trend_is_reported_without_reversal_claim():
    rows = []
    warmup(rows, 30)
    peak(rows, 102)
    trough(rows, 98)
    peak(rows, 102)
    bar(rows, 98, 97, 98, 96)
    pattern = pattern_of(run(rows), 'double-top')
    assert pattern['evidence']['priorTrend']['direction'] == 'flat'
    codes = [r['code'] for r in pattern['reasons']]
    assert 'prior-trend-flat' in codes and 'reversal-context' not in codes


def test_ids_are_stable_across_runs():
    rows = double_top()
    first, second = run(rows), run(rows)
    assert [(p['patternId'], [e['eventId'] for e in p['events']]) for p in first['patterns']] == \
           [(p['patternId'], [e['eventId'] for e in p['events']]) for p in second['patterns']]


def test_response_is_strict_json_serializable():
    import json
    out = run(double_top())
    text = json.dumps(out, ensure_ascii=False, allow_nan=False)
    assert 'structure-evidence-d-v1' in text
    assert '더블탑' not in text  # server sends codes/text, not display names


def test_config_and_rule_identifiers_are_explicit():
    out = run(double_top())
    assert out['ruleVersion'] == 'structure-evidence-d-v1'
    assert out['configId'].startswith('structure-evidence-v1-')
    assert out['config']['breakoutAtr'] == 0.1
    assert out['timeframe'] == 'D'


def _comparable(analysis):
    """Drop receipt-time fields that legitimately differ between two calls."""
    return dict(
        ruleVersion=analysis['ruleVersion'],
        events=[{k: v for k, v in e.items()
                 if k not in ('detectedAt', 'basisSnapshotId', 'barEndAt')} for e in analysis['events']],
        timeline=[[(p['patternId'], p['status']) for p in row['patterns']] for row in analysis['timeline']])


def _payload(rows, **overrides):
    payload = dict(symbol='AAPL', tf='D', fetchedAt='2026-10-18T20:00:00+00:00',
                   candles=rows, dataRevision='rev', source='yfinance',
                   marketSession={'state': 'open', 'sessionDate': '2026-01-18'},
                   lastConfirmedTime=rows[-1]['time'], snapshotEligible=True,
                   lastError=None, stale=False)
    payload.update(overrides)
    return payload


def test_attach_adds_parallel_field_and_preserves_structure(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import market_cache
    import pattern_service
    from market_store import MarketStore
    store = MarketStore(tmp_path / 'ev.sqlite3')
    monkeypatch.setattr(market_cache, 'enabled', lambda: True)
    monkeypatch.setattr(market_cache, 'services', lambda: SimpleNamespace(store=store))
    for name in ['enabled', 'flags_enabled', 'triangles_enabled', 'structures_enabled']:
        monkeypatch.setattr(pattern_service, name, lambda: True)
    try:
        rows = double_top()
        with_off = pattern_service.attach(_payload(rows))
        monkeypatch.setattr(pattern_service, 'structure_evidence_v2_enabled', lambda: True)
        with_on = pattern_service.attach(_payload(rows))
        assert 'structureEvidenceV2' not in with_off
        assert _comparable(with_on['structureAnalysis']) == _comparable(with_off['structureAnalysis'])
        field = with_on['structureEvidenceV2']
        assert field['sourceStatus'] == 'ready'
        assert field['dataRevision'] == 'rev'
        assert any(p['lifecycleState'] == 'retesting' for p in field['patterns'])
    finally:
        store.close()


def test_attach_pauses_on_stale_data_without_erasing_history(monkeypatch):
    import pattern_service
    monkeypatch.setattr(pattern_service, 'structure_evidence_v2_enabled', lambda: True)
    rows = double_top()
    live = pattern_service.attach(_payload(rows))['structureEvidenceV2']
    field = pattern_service.attach(_payload(rows, stale=True))['structureEvidenceV2']
    assert field['sourceStatus'] == 'paused' and field['reason'] == 'data-paused'
    assert [p['patternId'] for p in field['patterns']] == [p['patternId'] for p in live['patterns']]
    assert [e['eventId'] for e in field['events']] == [e['eventId'] for e in live['events']]
    assert all(p['dataEligibility']['state'] == 'paused' for p in field['patterns'])
    assert not field['provisionalEligible']


def test_attach_reports_unsupported_scope(monkeypatch):
    import pattern_service
    monkeypatch.setattr(pattern_service, 'structure_evidence_v2_enabled', lambda: True)
    rows = double_top()
    for payload in (_payload(rows, symbol='BTC-USD'), _payload(rows, symbol='^KS11'),
                    _payload(rows, tf='H4')):
        field = pattern_service.attach(payload)['structureEvidenceV2']
        assert field['sourceStatus'] == 'unsupported'
        assert field['reason'] == 'stock-daily-only'


# --- price boundary: the published price is the contract ---------------------

def _scaled(rows, factor):
    out = []
    for row in rows:
        copy = dict(row)
        for key in ('open', 'high', 'low', 'close'):
            copy[key] = row[key] * factor
        out.append(copy)
    return out


@pytest.mark.parametrize('build,name', [
    (double_top, 'double-top'), (double_bottom, 'double-bottom'),
    (head_shoulders, 'head-shoulders'), (inverse_head_shoulders, 'inverse-head-shoulders')])
@pytest.mark.parametrize('factor', [0.01, 0.1, 1, 10, 100])
def test_close_equal_to_the_published_trigger_still_waits(build, name, factor):
    rows = _scaled(build(confirmed=False), factor)
    cutoff = rows[-1]['time']
    discovered = engine.analyze(rows, 'AAPL', cutoff)
    pattern = [p for p in discovered['patterns'] if p['type'] == name][0]
    assert pattern['lifecycleState'] == 'candidate'
    trigger = pattern['triggerPriceAtEvaluation']
    nxt = dict(rows[-1])
    nxt['time'] = (date.fromisoformat(rows[-1]['time']) + timedelta(days=1)).isoformat()
    for key in ('open', 'close'):
        nxt[key] = trigger
    nxt['high'] = max(trigger, nxt['high'])
    nxt['low'] = min(trigger, nxt['low'])
    out = engine.analyze(rows + [nxt], 'AAPL', nxt['time'])
    same = [p for p in out['patterns'] if p['type'] == name][0]
    assert same['lifecycleState'] == 'candidate'
    reason = [r['code'] for r in same['reasons']]
    assert 'close-at-trigger' in reason


@pytest.mark.parametrize('build,name', [
    (double_top, 'double-top'), (double_bottom, 'double-bottom'),
    (head_shoulders, 'head-shoulders'), (inverse_head_shoulders, 'inverse-head-shoulders')])
@pytest.mark.parametrize('factor', [0.01, 0.1, 1, 10, 100])
def test_close_equal_to_the_published_invalidation_is_not_a_failure(build, name, factor):
    rows = _scaled(build(), factor)
    cutoff = rows[-1]['time']
    confirmed = engine.analyze(rows, 'AAPL', cutoff)
    pattern = [p for p in confirmed['patterns'] if p['type'] == name][0]
    invalidation = pattern['invalidationPrice']
    nxt = dict(rows[-1])
    nxt['time'] = (date.fromisoformat(rows[-1]['time']) + timedelta(days=1)).isoformat()
    for key in ('open', 'close'):
        nxt[key] = invalidation
    nxt['high'] = max(invalidation, nxt['high'])
    nxt['low'] = min(invalidation, nxt['low'])
    out = engine.analyze(rows + [nxt], 'AAPL', nxt['time'])
    same = [p for p in out['patterns'] if p['type'] == name][0]
    assert same['lifecycleState'] != 'failed'


def test_one_tick_past_the_published_trigger_confirms():
    rows = _scaled(double_top(confirmed=False), 0.1)
    trigger = [p for p in engine.analyze(rows, 'AAPL', rows[-1]['time'])['patterns']
               if p['type'] == 'double-top'][0]['triggerPriceAtEvaluation']
    nxt = dict(rows[-1])
    nxt['time'] = (date.fromisoformat(rows[-1]['time']) + timedelta(days=1)).isoformat()
    nxt.update(open=trigger, close=trigger - 0.0001, high=trigger, low=trigger - 0.001)
    out = engine.analyze(rows + [nxt], 'AAPL', nxt['time'])
    same = [p for p in out['patterns'] if p['type'] == 'double-top'][0]
    assert same['lifecycleState'] == 'confirmed'


# --- gaps, revisions and reason shape ---------------------------------------

def test_reported_gap_restarts_instead_of_spanning_it():
    rows = double_top()
    rows[25]['missingBarsBefore'] = 5
    out = run(rows)
    assert out['dataEligibility']['state'] == 'reprepared'
    assert out['dataEligibility']['missingBarsBefore'] == 5
    for pattern in out['patterns']:
        assert pattern['structureStartTime'] >= rows[25]['time']
        assert pattern['dataEligibility']['state'] == 'reprepared'


def test_unknown_adjustment_policy_is_labeled_not_treated_as_failure():
    rows = double_top()
    out = engine.analyze(rows, 'AAPL', rows[-1]['time'], adjustment_policy='unknown')
    assert out['dataEligibility']['state'] == 'adjustment-unknown'
    assert out['patterns']
    assert all(p['dataEligibility']['adjustmentPolicy'] == 'unknown' for p in out['patterns'])


def test_every_event_carries_the_revision_and_object_reasons():
    rows = double_top()
    bar(rows, 93, 93, 94, 92)
    out = engine.analyze(rows, 'AAPL', rows[-1]['time'], data_revision='rev-1')
    for event in out['events']:
        assert event['dataRevision'] == 'rev-1'
        assert event['snapshot']['reasons'], event['eventType']
        for reason in event['snapshot']['reasons']:
            assert set(reason) == {'code', 'text'}
            assert reason['text'] and reason['text'] != reason['code']


def test_candidate_lifetime_allows_the_last_bar_and_expires_after_it():
    rows = []
    warmup(rows)
    peak(rows, 106)
    trough(rows, 95)
    peak(rows, 106)
    for _ in range(20):
        bar(rows, 100, 100, 101, 99)
    out = run(rows)
    candidate = [p for p in out['patterns'] if p['type'] == 'double-top'][0]
    assert candidate['lifecycleState'] == 'candidate'
    assert candidate['barsSinceDiscovery'] == 20
    bar(rows, 100, 100, 101, 99)
    out = run(rows)
    expired = [p for p in out['patterns'] if p['type'] == 'double-top'][0]
    assert expired['lifecycleState'] == 'expired'
    assert expired['barsSinceDiscovery'] == 21


def test_tracking_lifetime_allows_the_last_bar_and_expires_after_it():
    rows = double_top()
    base = [p for p in run(rows)['patterns'] if p['type'] == 'double-top'][0]
    for _ in range(30 - base['barsSinceConfirmation']):
        bar(rows, 93, 92, 94, 92)
    held = [p for p in run(rows)['patterns'] if p['type'] == 'double-top'][0]
    assert held['barsSinceConfirmation'] == 30
    assert held['lifecycleState'] != 'expired'
    bar(rows, 93, 92, 94, 92)
    expired = [p for p in run(rows)['patterns'] if p['type'] == 'double-top'][0]
    assert expired['barsSinceConfirmation'] == 31
    assert expired['lifecycleState'] == 'expired'


def test_shared_cache_off_still_exposes_the_parallel_evidence(monkeypatch):
    import serve_dashboard as server
    import pattern_service
    monkeypatch.setattr(pattern_service, 'structure_evidence_v2_enabled', lambda: True)
    monkeypatch.setattr(server.market_cache, 'enabled', lambda: False)
    rows = double_top()
    monkeypatch.setattr(server, '_market_lookup', lambda code, force=False: _payload(rows))
    out = server.market_lookup('AAPL')
    assert out['structureEvidenceV2']['sourceStatus'] == 'ready'
    assert out['structureEvidenceV2']['patterns']
