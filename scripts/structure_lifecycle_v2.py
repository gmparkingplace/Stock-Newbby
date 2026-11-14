"""Sequential lifecycle for structure evidence v2.

The engine walks confirmed bars once. A candidate is created only when its last
anchor pivot becomes available; the breakout yardstick (ATR) is frozen at that
bar. Every later state change is an append-only event, so a failed pattern keeps
its original confirmation record.

No cache, database, clock, network or DOM access.
"""
from market_store import revision
from pattern_math import atr14, validated
from structure_geometry_v2 import (available_pivots, double_candidate, geometry,
                                   head_shoulders_candidate, neckline_at)
import structure_evidence_v2 as evidence
from structure_v2_profiles import config_id, parameters, rule_version

TERMINAL = ('failed', 'expired', 'invalidated')
VOLUME_REASON = {'supported': 'volume-supported', 'weak': 'volume-weak', 'unknown': 'volume-unknown'}
PRICE_REASON = {'beyond': 'close-beyond-trigger', 'at': 'close-at-trigger', 'short': 'close-short-of-trigger'}


def _price_reason(close, trigger, sign):
    """Compare the bar close with the published price, never a re-derived spread.

    ``triggerPrice`` is what the API and the screen show. Recomputing the same
    difference from the neckline reintroduces floating-point cancellation, so a
    close that equals the published trigger used to read as a breakout.
    """
    if close == trigger:
        return PRICE_REASON['at']
    return PRICE_REASON['beyond'] if sign * (close - trigger) > 0 else PRICE_REASON['short']


def _beyond(close, price, sign):
    """Strictly past the price in the pattern direction; equality waits."""
    return sign * (close - price) > 0


def _context_reasons(candidate):
    trend = candidate['base']['priorTrend']
    if not trend['available']:
        return ['prior-trend-unknown']
    codes = ['prior-trend-' + trend['direction']] if trend['direction'] in ('up', 'down', 'flat') else ['prior-trend-unknown']
    if trend['reversalContext'] is True:
        codes.append('reversal-context')
    elif trend['reversalContext'] is False:
        codes.append('continuation-risk')
    return codes


def _candidate_invalidation(candidate, cfg):
    """Before confirmation the shape dies at the opposite extreme, not the neckline."""
    prices = [price for _, price in candidate['peaks']]
    extreme = max(prices) if candidate['sign'] == -1 else min(prices)
    return extreme - candidate['sign'] * cfg['invalidationAtr'] * candidate['atr0']


def _snapshot(close, neckline, trigger, invalidation, ratio, volume_status, phase, reasons, **extra):
    return dict(close=close, neckline=neckline, triggerPrice=trigger,
                invalidationPrice=invalidation, volumeRatio=ratio,
                volumeStatus=volume_status, phaseAfter=phase,
                reasons=[dict(code=code, text=evidence.describe(code)) for code in reasons], **extra)


def _emit(candidate, rows, index, event_type, snapshot):
    event = dict(eventId=revision([candidate['patternId'], event_type, rows[index]['time'], len(candidate['events'])]),
                 patternId=candidate['patternId'], eventType=event_type,
                 observedAt=rows[index]['time'], effectiveBarTime=rows[index]['time'],
                 dataRevision=candidate.get('dataRevision'), snapshot=snapshot)
    candidate['events'].append(event)
    return event


def _codes_reasons(codes):
    """Every reason list is a code/description pair, including later transitions."""
    return [dict(code=code, text=evidence.describe(code)) for code in codes]


def _evaluate(candidate, index, rows, cfg):
    sign, atr0 = candidate['sign'], candidate['atr0']
    neckline = neckline_at(candidate, index)
    close = rows[index]['close']
    trigger = neckline + sign * cfg['breakoutAtr'] * atr0
    invalidation = neckline - sign * cfg['invalidationAtr'] * atr0
    phase = candidate['phase']
    shown_invalidation = (_candidate_invalidation(candidate, cfg)
                          if phase == 'candidate' else invalidation)
    beyond = _beyond(close, trigger, sign)
    previous_beyond = candidate.get('lastBeyond')
    candidate['lastBeyond'] = beyond
    candidate['last'] = dict(index=index, time=rows[index]['time'], neckline=neckline,
                             triggerPrice=trigger, invalidationPrice=shown_invalidation, close=close)
    ratio, volume_status = evidence.volume_ratio(rows, index, cfg)
    candidate['latestVolume'] = dict(ratio=ratio, status=volume_status)
    codes = [_price_reason(close, trigger, sign), VOLUME_REASON[volume_status]] + _context_reasons(candidate)
    snapshot = _snapshot(close, neckline, trigger, shown_invalidation, ratio, volume_status, phase, codes)

    if phase == 'candidate':
        if beyond:
            candidate['phase'] = 'confirmed'
            candidate['confirmedIndex'] = index
            candidate['confirmedAt'] = rows[index]['time']
            candidate['triggerAtEvent'] = trigger
            candidate['necklineAtEvent'] = neckline
            candidate['invalidationAtEvent'] = invalidation
            candidate['breakoutVolume'] = dict(ratio=ratio, status=volume_status)
            candidate['last']['invalidationPrice'] = invalidation
            snapshot.update(phaseAfter='confirmed',
                            reasons=_codes_reasons(codes + ['breakout-confirmed']),
                            triggerPriceAtEvent=trigger, necklineAtEvent=neckline,
                            invalidationPriceAtEvent=invalidation, invalidationPrice=invalidation)
            _emit(candidate, rows, index, 'breakout-confirmed', snapshot)
        elif sign * (close - shown_invalidation) < 0:
            candidate['phase'] = 'invalidated'
            candidate['closedAt'] = rows[index]['time']
            snapshot.update(phaseAfter='invalidated',
                            reasons=_codes_reasons(['candidate-invalidated'] + _context_reasons(candidate)))
            _emit(candidate, rows, index, 'candidate-invalidated', snapshot)
        elif index - candidate['discoveredIndex'] > cfg['candidateBars']:
            candidate['phase'] = 'expired'
            candidate['closedAt'] = rows[index]['time']
            candidate['expiredBeforeConfirmation'] = True
            snapshot.update(phaseAfter='expired',
                            reasons=_codes_reasons(['candidate-expired'] + _context_reasons(candidate)))
            _emit(candidate, rows, index, 'expired', snapshot)
        return

    if phase in TERMINAL:
        return

    if sign * (close - invalidation) < 0:
        candidate['phase'] = 'failed'
        candidate['closedAt'] = rows[index]['time']
        snapshot.update(phaseAfter='failed',
                        reasons=_codes_reasons(['breakout-failed'] + _context_reasons(candidate)))
        _emit(candidate, rows, index, 'breakout-failed', snapshot)
        return
    if index - candidate['confirmedIndex'] > cfg['trackingBars']:
        candidate['phase'] = 'expired'
        candidate['closedAt'] = rows[index]['time']
        snapshot.update(phaseAfter='expired',
                        reasons=_codes_reasons(['tracking-expired'] + _context_reasons(candidate)))
        _emit(candidate, rows, index, 'expired', snapshot)
        return

    band = cfg['retestBandAtr'] * atr0
    touch = rows[index]['low'] <= neckline + band and rows[index]['high'] >= neckline - band
    if phase in ('confirmed', 'holding') and index != candidate['confirmedIndex'] and touch:
        candidate['phase'] = 'retesting'
        candidate['retestVolumes'] = []
        bars = cfg['volumeBaselineBars']
        baseline = (sum(rows[k]['volume'] for k in range(index - bars, index)) / bars
                    if index >= bars else None)
        candidate['retestBaselineVolume'] = baseline if baseline and baseline > 0 else None
        candidate['retestIndex'] = index
        snapshot.update(phaseAfter='retesting',
                        reasons=_codes_reasons(['retest-in-progress'] + _context_reasons(candidate)))
        _emit(candidate, rows, index, 'retest-started', snapshot)
    elif phase == 'retesting' and beyond and previous_beyond is False:
        # Re-crossing needs a prior close on the inside. A bar that never left
        # the breakout side is not a new hold.
        candidate['phase'] = 'holding'
        snapshot.update(phaseAfter='holding',
                        reasons=_codes_reasons(['retest-held'] + _context_reasons(candidate)))
        _emit(candidate, rows, index, 'retest-held', snapshot)

    if candidate['phase'] == 'retesting' and touch:
        candidate['retestVolumes'].append(rows[index]['volume'])
        baseline = candidate.get('retestBaselineVolume')
        if baseline:
            candidate['retestVolume'] = dict(
                ratio=(sum(candidate['retestVolumes']) / len(candidate['retestVolumes'])) / baseline,
                bars=len(candidate['retestVolumes']), baselineBars=cfg['volumeBaselineBars'])

    if (not candidate.get('boosted') and candidate['phase'] in ('confirmed', 'retesting', 'holding')
            and beyond and volume_status == 'supported'):
        candidate['boosted'] = True
        candidate['boostedAt'] = rows[index]['time']
        boost = dict(snapshot, phaseAfter=candidate['phase'],
                     reasons=_codes_reasons(['volume-boosted-later'] + _context_reasons(candidate)))
        _emit(candidate, rows, index, 'volume-supported', boost)


def _register(candidates, rows, index, symbol, rule, cid, cfg, seen, all_candidates,
              data_revision=None):
    created = []
    for candidate in candidates:
        key = (candidate['type'], candidate['peaks'][0][0], candidate['peaks'][-1][0])
        if key in seen:
            continue
        if any(x['type'] == candidate['type'] and x['peaks'][-1][0] == candidate['peaks'][-1][0]
               for x in all_candidates):
            continue
        seen.add(key)
        candidate.update(
            patternId=revision([symbol, 'D', candidate['type'],
                                [rows[i]['time'] for i, _ in candidate['peaks']], rule, cid]),
            ruleVersion=rule, configId=cid, discoveredIndex=index,
            discoveredAt=rows[index]['time'], atr0=cfg['_atr0'], phase='candidate',
            confirmedIndex=None, confirmedAt=None, events=[], latestVolume=None,
            dataRevision=data_revision)
        candidate['base'] = evidence.base_evidence(rows, candidate, cfg)
        amount = cfg['breakoutAtr'] * candidate['atr0']
        neckline = neckline_at(candidate, index)
        _emit(candidate, rows, index, 'candidate-detected',
              _snapshot(rows[index]['close'], neckline,
                        neckline + candidate['sign'] * amount,
                        _candidate_invalidation(candidate, cfg),
                        None, 'unknown', 'candidate', ['candidate-detected']))
        all_candidates.append(candidate)
        created.append(candidate)
    return created


def _public(candidate, rows, cfg, data_revision, eligibility=None):
    last = candidate['last']
    points = [dict(time=rows[k]['time'], price=v) for k, v in candidate['neckline']]
    base = candidate['base']
    latest_ratio = candidate['latestVolume']['ratio'] if candidate['latestVolume'] else None
    latest_status = candidate['latestVolume']['status'] if candidate['latestVolume'] else 'unknown'
    breakout = candidate.get('breakoutVolume') or dict(ratio=None, status='unknown')
    price_code = _price_reason(last['close'], last['triggerPrice'], candidate['sign'])
    if candidate['phase'] == 'confirmed' and price_code == PRICE_REASON['short']:
        price_code = 'close-back-inside-trigger'
    reasons = [price_code, VOLUME_REASON[latest_status]] + _context_reasons(candidate)
    if candidate['phase'] == 'retesting':
        reasons = ['retest-in-progress', VOLUME_REASON[latest_status]] + _context_reasons(candidate)
    elif candidate['phase'] == 'holding':
        reasons = ['retest-held', VOLUME_REASON[latest_status]] + _context_reasons(candidate)
    elif candidate['phase'] == 'failed':
        reasons = ['breakout-failed'] + _context_reasons(candidate)
    elif candidate['phase'] == 'invalidated':
        reasons = ['candidate-invalidated'] + _context_reasons(candidate)
    elif candidate['phase'] == 'expired':
        reasons = [('candidate-expired' if candidate.get('expiredBeforeConfirmation') else 'tracking-expired')] + _context_reasons(candidate)
    return dict(
        patternId=candidate['patternId'], type=candidate['type'], direction=candidate['direction'],
        ruleVersion=candidate['ruleVersion'], configId=candidate['configId'],
        dataRevision=data_revision, lifecycleState=candidate['phase'],
        dataEligibility=dict(**(eligibility or dict(state='eligible')), evaluatedThrough=last['time']),
        structureStartTime=rows[candidate['peaks'][0][0]]['time'],
        structureEndTime=rows[candidate['peaks'][-1][0]]['time'],
        discoveredAt=candidate['discoveredAt'], confirmedAt=candidate['confirmedAt'],
        evaluatedAt=last['time'], barTime=last['time'], confirmedBarTime=candidate['confirmedAt'],
        structureBars=candidate['spanBars'],
        atr14Previous=candidate['atr0'],
        barsSinceDiscovery=candidate['last']['index'] - candidate['discoveredIndex'],
        barsSinceConfirmation=(candidate['last']['index'] - candidate['confirmedIndex']
                               if candidate['confirmedIndex'] is not None else None),
        expiredBeforeConfirmation=bool(candidate.get('expiredBeforeConfirmation')),
        anchors=dict(peakTimes=[rows[i]['time'] for i, _ in candidate['peaks']],
                     peakPrices=[price for _, price in candidate['peaks']],
                     neckline=points,
                     structureStart=rows[candidate['peaks'][0][0]]['time'],
                     structureEnd=rows[candidate['peaks'][-1][0]]['time']),
        neckline=dict(points=points, atEvaluation=last['neckline'], flat=candidate['flat'],
                      anchorTimes=[rows[k]['time'] for k in candidate['necklineIndexes']],
                      anchorPrices=[candidate['neckline'][n][1] for n in range(2)]),
        triggerPriceAtEvaluation=last['triggerPrice'],
        triggerPriceAtEvent=candidate.get('triggerAtEvent'),
        invalidationPrice=last['invalidationPrice'],
        invalidationPriceAtEvent=candidate.get('invalidationAtEvent'),
        close=last['close'],
        geometry=geometry(candidate, rows),
        evidence=evidence.summary(base, cfg, breakout['ratio'], breakout['status'],
                                  latest_ratio, latest_status,
                                  boosted_at=candidate.get('boostedAt'),
                                  retest_volume=candidate.get('retestVolume')),
        reasons=[dict(code=code, text=evidence.describe(code)) for code in reasons],
        events=list(candidate['events']))


def analyze(candles, symbol, confirmed_through, timeframe='D', profile='baseline',
            data_revision=None, adjustment_policy='provider-adjusted'):
    if timeframe != 'D':
        raise ValueError('unsupported-structure-evidence-timeframe')
    cfg = parameters(profile)
    rule = rule_version('D', profile)
    cid = config_id(profile)
    rows = validated(candles, confirmed_through, timeframe, symbol)
    if confirmed_through is None:
        return dict(enabled=True, symbol=symbol, timeframe='D', ruleVersion=rule, configId=cid,
                    dataRevision=data_revision, sourceStatus='paused', reason='unconfirmed-cutoff',
                    confirmedThrough=None, evaluatedThrough=None, patterns=[], events=[])
    cutoff = next(i for i, row in enumerate(rows) if row['time'] == confirmed_through)
    rows = rows[:cutoff + 1]
    eligibility = dict(state='eligible', adjustmentPolicy=adjustment_policy)
    if adjustment_policy != 'provider-adjusted':
        eligibility.update(state='adjustment-unknown', reason='adjustment-policy-unknown')
    # A reported data gap is a hard boundary: pivots, ATR and volume baselines
    # must not be carried across it. Restart from the latest coherent segment.
    starts = [0] + [i for i in range(1, len(rows)) if (rows[i].get('missingBarsBefore') or 0) > 0]
    if len(starts) > 1:
        gap_at = starts[-1]
        eligibility.update(state='reprepared', reason='missing-bars',
                           missingBarsBefore=rows[gap_at].get('missingBarsBefore'),
                           repreparedAt=rows[gap_at]['time'])
        rows = rows[gap_at:]
    if len(rows) < 15:
        return dict(enabled=True, symbol=symbol, timeframe='D', ruleVersion=rule, configId=cid,
                    dataRevision=data_revision, sourceStatus='paused', reason='insufficient-history',
                    dataEligibility=eligibility, confirmedThrough=confirmed_through,
                    evaluatedThrough=rows[-1]['time'] if rows else None, patterns=[], events=[])
    atr = atr14(rows)
    seen, all_candidates, events = set(), [], []
    for index in range(len(rows)):
        if index < 3 or not atr[index - 1]:
            continue
        newest = index - 2
        highs, lows = available_pivots(rows, index)
        config = dict(cfg, _atr0=atr[index - 1])
        created = []
        if highs and highs[-1][0] == newest:
            created += _register(double_candidate(rows, highs, 'double-top', highs[-1], atr[index - 1], cfg),
                                 rows, index, symbol, rule, cid, config, seen, all_candidates,
                                 data_revision)
            created += _register(head_shoulders_candidate(rows, highs, 'head-shoulders', highs[-1], atr[index - 1], cfg),
                                 rows, index, symbol, rule, cid, config, seen, all_candidates,
                                 data_revision)
        if lows and lows[-1][0] == newest:
            created += _register(double_candidate(rows, lows, 'double-bottom', lows[-1], atr[index - 1], cfg),
                                 rows, index, symbol, rule, cid, config, seen, all_candidates,
                                 data_revision)
            created += _register(head_shoulders_candidate(rows, lows, 'inverse-head-shoulders', lows[-1], atr[index - 1], cfg),
                                 rows, index, symbol, rule, cid, config, seen, all_candidates,
                                 data_revision)
        for candidate in all_candidates:
            if candidate['phase'] in TERMINAL:
                continue
            _evaluate(candidate, index, rows, cfg)
    created_order = [_public(candidate, rows, cfg, data_revision, eligibility)
                     for candidate in all_candidates]
    for pattern in created_order:
        events.extend(pattern['events'])
    events.sort(key=lambda e: e['effectiveBarTime'])
    public = sorted(created_order,
                    key=lambda p: (p['structureEndTime'], p['discoveredAt'], p['patternId']),
                    reverse=True)
    return dict(enabled=True, symbol=symbol, timeframe='D', sourceStatus='ready',
                ruleVersion=rule, configId=cid, dataRevision=data_revision,
                confirmedThrough=confirmed_through, evaluatedThrough=rows[-1]['time'],
                dataEligibility=eligibility, config=dict(cfg), patterns=public, events=events)
