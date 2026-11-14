"""Causal double top/bottom and head-and-shoulders structure patterns.

Only confirmed pivots (two bars on each side) participate, and a structure is
"confirmed" only when a later confirmed close breaks its neckline. No network,
DOM or wall-clock.
"""
from market_store import revision
from pattern_math import validated, analyze_contiguous, atr14, pivots
from pattern_profiles import parameters, rule_version

RULE = rule_version('structure')


def _cfg(profile):
    return parameters(profile)['structure']


def _neckline(rows, a, b, side):
    """Flat neckline across an index span. `side` is 'low' for a top, 'high' for a bottom."""
    j = max(range(a + 1, b), key=(lambda j: rows[j][side])) if side == 'high' else min(range(a + 1, b), key=(lambda j: rows[j][side]))
    return rows[j][side], j


def _geometry(kind, peaks, neckline, neck_index, rows):
    """Polygon points: 위쪽 경로(고점/저점)를 왼쪽에서 오른쪽으로, 이어서 목선을
    오른쪽에서 왼쪽으로 되돌린다. 이 순서여야 변이 서로 교차하지 않는다.
    (고점→목선→고점→목선 순서는 채움 도형이 나비넥타이처럼 꼬인다.)"""
    if kind in ('double-top', 'double-bottom'):
        (i1, v1), (i2, v2) = peaks
        points = [dict(time=rows[i1]['time'], price=v1),
                  dict(time=rows[i2]['time'], price=v2),
                  dict(time=rows[i2]['time'], price=neckline),
                  dict(time=rows[i1]['time'], price=neckline)]
    else:
        (il, vl), (ih, vh), (ir, vr) = peaks
        points = [dict(time=rows[il]['time'], price=vl),
                  dict(time=rows[ih]['time'], price=vh),
                  dict(time=rows[ir]['time'], price=vr),
                  dict(time=rows[ir]['time'], price=neckline),
                  dict(time=rows[il]['time'], price=neckline)]
    return dict(kind=kind, points=points)


def _volume(rows, end):
    vol = sum(r['volume'] for r in rows[max(0, end - 20):end]) / 20 if end >= 20 else 0
    rv = rows[end]['volume'] / vol if vol > 0 else None
    return rv, 'volume-confirmed' if rv is not None and rv >= 1.2 else 'volume-insufficient'


def _present(p, i, status, rule, timeframe, rows):
    end = p['confirmedIndex'] if p['confirmedIndex'] is not None else i
    a = p['atr14Previous']
    sign = 1 if p['direction'] == 'up' else -1
    neckline = p['neckline']
    boundary = neckline + sign * .1 * a
    rv, evidence = _volume(rows, end)
    clean = {k: v for k, v in p.items() if k in (
        'patternId', 'type', 'direction', 'ruleVersion', 'anchorTime', 'structureStartTime',
        'discoveredTime', 'neckline', 'peakPrices', 'peakTimes', 'atr14Previous',
        'peakToleranceAtr', 'headExcessAtr', 'structureBars')}
    return dict(clean, status=status, barTime=rows[end]['time'], close=rows[end]['close'],
                boundary=boundary, triggerPrice=boundary,
                invalidationPrice=neckline - sign * .1 * a,
                geometry=_geometry(p['type'], p['peaks'], neckline, p['neckIndex'], rows),
                rvol20Previous=rv, volumeEvidence=evidence)


def analyze(candles, symbol, confirmed_through, provisional=False, levels=None, timeframe='D', profile='balanced'):
    from intraday_timeframes import is_intraday
    if timeframe != 'D' and not is_intraday(timeframe):
        raise ValueError('unsupported-pattern-timeframe')
    cfg = _cfg(profile)
    rule = rule_version('structure', timeframe, profile)
    rows = validated(candles, confirmed_through, timeframe, symbol)
    segmented = analyze_contiguous(analyze, rows, symbol, confirmed_through, provisional, levels, timeframe, profile)
    if segmented is not None:
        return segmented
    atr = atr14(rows)
    timeline, events, history = [], [], []
    tol, neck_atr = cfg['tolerance'], cfg['neckline']
    min_sep, max_bars = cfg['min_sep'], cfg['max_bars']
    head_atr, confirm_bars = cfg['head_atr'], cfg['confirm_bars']
    ident_set = set()
    necklines = {}
    def neckline_for(left, right, side):
        key = (left, right, side)
        if key not in necklines:
            necklines[key] = _neckline(rows, left, right, side)
        return necklines[key]
    # `pivots(rows, i)` re-scanned the whole prefix on every bar and dominated the
    # runtime. The set only grows, so precompute it once and advance two cursors.
    hi_all, lo_all = [], []
    for j in range(2, len(rows) - 2):
        h, l = rows[j]['high'], rows[j]['low']
        if all(h >= rows[k]['high'] for k in (j-2, j-1)) and all(h > rows[k]['high'] for k in (j+1, j+2)):
            hi_all.append((j, h))
        if all(l <= rows[k]['low'] for k in (j-2, j-1)) and all(l < rows[k]['low'] for k in (j+1, j+2)):
            lo_all.append((j, l))
    hi, lo = [], []
    hi_next = lo_next = 0

    for i, row in enumerate(rows):
        while hi_next < len(hi_all) and hi_all[hi_next][0] <= i - 2:
            hi.append(hi_all[hi_next]); hi_next += 1
        while lo_next < len(lo_all) and lo_all[lo_next][0] <= i - 2:
            lo.append(lo_all[lo_next]); lo_next += 1
        confirmed = confirmed_through is not None and row['time'] <= confirmed_through
        if confirmed and i >= 3 and atr[i - 1]:
            a = atr[i - 1]
            for kind, arr, side, sign in (
                    ('double-top', hi, 'low', -1), ('double-bottom', lo, 'high', 1)):
                for x in range(len(arr)):
                    i1, v1 = arr[x]
                    for y in range(x + 1, len(arr)):
                        i2, v2 = arr[y]
                        span = i2 - i1
                        if span > max_bars:
                            break  # indices only grow from here
                        if span < min_sep:
                            continue
                        if abs(v1 - v2) > tol * a or i2 >= i:
                            continue
                        if (kind, i1, i2) in ident_set:
                            continue
                        neckline, jn = neckline_for(i1, i2, side)
                        if sign * (row['close'] - neckline) > 0:
                            ident = revision([symbol, timeframe, kind, rule, rows[i1]['time'], rows[i2]['time']])
                            ident_set.add((kind, i1, i2))
                            p = dict(patternId=ident, type=kind, direction=('up' if sign == 1 else 'down'),
                                     ruleVersion=rule, anchorTime=rows[i1]['time'], structureStartTime=rows[i1]['time'],
                                     discoveredTime=rows[i]['time'], neckline=neckline, neckIndex=jn,
                                     peaks=[(i1, v1), (i2, v2)], peakPrices=[v1, v2],
                                     peakTimes=[rows[i1]['time'], rows[i2]['time']],
                                     atr14Previous=a, peakToleranceAtr=tol, headExcessAtr=None,
                                     structureBars=i2 - i1 + 1, confirmedIndex=i)
                            history.append(p)
                            e = _present(p, i, 'confirmed', rule, timeframe, rows)
                            e.update(eventType='confirmed', confirmedBarTime=rows[i]['time'],
                                     eventId=revision([ident, 'confirmed', rows[i]['time'], rule]))
                            if timeframe != 'D':
                                e['timeframe'] = timeframe
                            events.append(e)
            for kind, arr, side, sign in (
                    ('head-shoulders', hi, 'low', -1), ('inverse-head-shoulders', lo, 'high', 1)):
                for x in range(len(arr)):
                    il, vl = arr[x]
                    for y in range(x + 1, len(arr)):
                        ih, vh = arr[y]
                        if ih - il > max_bars:
                            break  # indices only grow from here
                        if ih - il < min_sep:
                            continue
                        for z in range(y + 1, len(arr)):
                            ir, vr = arr[z]
                            if ir - ih > max_bars:
                                break  # indices only grow from here
                            if ir - ih < min_sep:
                                continue
                            if (kind, il, ih, ir) in ident_set:
                                continue
                            # The middle pivot must be the extreme: higher than both
                            # shoulders for a head, lower than both for an inverse.
                            head_extended = (vh - vl > head_atr * a and vh - vr > head_atr * a) if kind == 'head-shoulders' else (vl - vh > head_atr * a and vr - vh > head_atr * a)
                            if not head_extended:
                                continue
                            if abs(vl - vr) > tol * a or ir >= i:
                                continue
                            neckline, jn = neckline_for(il, ir, side)
                            if sign * (row['close'] - neckline) > 0:
                                ident = revision([symbol, timeframe, kind, rule,
                                                  rows[il]['time'], rows[ih]['time'], rows[ir]['time']])
                                ident_set.add((kind, il, ih, ir))
                                p = dict(patternId=ident, type=kind, direction=('up' if sign == 1 else 'down'),
                                         ruleVersion=rule, anchorTime=rows[il]['time'], structureStartTime=rows[il]['time'],
                                         discoveredTime=rows[i]['time'], neckline=neckline, neckIndex=jn,
                                         peaks=[(il, vl), (ih, vh), (ir, vr)], peakPrices=[vl, vh, vr],
                                         peakTimes=[rows[il]['time'], rows[ih]['time'], rows[ir]['time']],
                                         atr14Previous=a, peakToleranceAtr=tol, headExcessAtr=head_atr,
                                         structureBars=ir - il + 1, confirmedIndex=i)
                                history.append(p)
                                e = _present(p, i, 'confirmed', rule, timeframe, rows)
                                e.update(eventType='confirmed', confirmedBarTime=rows[i]['time'],
                                         eventId=revision([ident, 'confirmed', rows[i]['time'], rule]))
                                if timeframe != 'D':
                                    e['timeframe'] = timeframe
                                events.append(e)

        displayed = []
        for p in history:
            if p['confirmedIndex'] is not None and i - p['confirmedIndex'] > confirm_bars:
                continue
            displayed.append(_present(p, i, 'confirmed', rule, timeframe, rows))
        rank = {'confirmed': 0}
        displayed.sort(key=lambda p: (rank.get(p['status'], 1), p['discoveredTime']))
        chosen = []
        for p in displayed:
            if not any(x['type'] == p['type'] for x in chosen):
                chosen.append(p)
        timeline.append(dict(barTime=row['time'], confirmed=confirmed,
                             status='ready' if chosen or i >= 30 else 'insufficient-data',
                             patterns=chosen))
    return dict(symbol=symbol, timeframe=timeframe, ruleVersion=rule, levels={}, configId=rule,
                confirmedThrough=confirmed_through, timeline=timeline, events=events)
