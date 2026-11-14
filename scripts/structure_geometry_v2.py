"""Causal geometry for structure evidence v2.

Only confirmed pivots (two bars to the right) are used. A candidate is created
once, with the ATR of the bar before discovery frozen as its price yardstick;
later bars cannot rescan an old shape with a new ATR. No clock, network or DOM.
"""
from pattern_math import pivots


def available_pivots(rows, through):
    """Pivots whose right-hand confirmation bars are already present."""
    return pivots(rows, through)


def _between(rows, start, end, side):
    """Extremum strictly between two indexes; ties pick the earliest bar."""
    if side == 'low':
        value, index = min(((rows[j]['low'], j) for j in range(start + 1, end)),
                           key=lambda x: (x[0], x[1]))
        return value, index
    value, index = max(((rows[j]['high'], -j) for j in range(start + 1, end)),
                       key=lambda x: (x[0], x[1]))
    return value, -index


def simple_neckline(rows, start, end, side):
    value, j = _between(rows, start, end, side)
    return value, j


def double_candidate(rows, pivots_list, kind, newest, atr, cfg):
    """Return one candidate dict or None. `kind` is double-top/double-bottom."""
    side = 'low' if kind == 'double-top' else 'high'
    sign = -1 if kind == 'double-top' else 1
    i2, v2 = newest
    candidates = []
    for i1, v1 in pivots_list:
        if not cfg['minSeparationBars'] <= i2 - i1 <= cfg['maxSpanBars']:
            continue
        if abs(v1 - v2) > cfg['toleranceAtr'] * atr:
            continue
        edge = (max(v1, v2) + cfg['toleranceAtr'] * atr if kind == 'double-top'
                else min(v1, v2) - cfg['toleranceAtr'] * atr)
        # A more extreme pivot inside the span means this is not a double top/bottom.
        interfering = any(i1 < j < i2 and (v > edge if kind == 'double-top' else v < edge)
                          for j, v in pivots_list)
        if interfering:
            continue
        value, jn = simple_neckline(rows, i1, i2, side)
        candidates.append(dict(
            type=kind, direction='down' if sign == -1 else 'up', sign=sign,
            peaks=[(i1, v1), (i2, v2)],
            neckline=[(i1, value), (i2, value)], necklineIndexes=[jn, jn],
            flat=True, spanBars=i2 - i1 + 1,
            toleranceAtr=cfg['toleranceAtr'], headExcessAtr=None))
    candidates.sort(key=lambda c: c['peaks'][0][0])
    return candidates


def head_shoulders_candidate(rows, pivots_list, kind, newest, atr, cfg):
    """Three confirmed pivots. The neckline joins the two reaction points."""
    side = 'low' if kind == 'head-shoulders' else 'high'
    sign = -1 if kind == 'head-shoulders' else 1
    ir, vr = newest
    candidates = []
    for x, (il, vl) in enumerate(pivots_list):
        for ih, vh in pivots_list[x + 1:]:
            if not (il < ih < ir):
                continue
            if not cfg['minSeparationBars'] <= ih - il <= cfg['maxSpanBars']:
                continue
            if not cfg['minSeparationBars'] <= ir - ih <= cfg['maxSpanBars']:
                continue
            if ir - il + 1 > cfg['maxTotalBars']:
                continue
            if kind == 'head-shoulders':
                if not (vh - vl > cfg['headExcessAtr'] * atr and
                        vh - vr > cfg['headExcessAtr'] * atr):
                    continue
                if any(v > vh + cfg['toleranceAtr'] * atr
                       for j, v in pivots_list if il <= j <= ir):
                    continue
            else:
                if not (vl - vh > cfg['headExcessAtr'] * atr and
                        vr - vh > cfg['headExcessAtr'] * atr):
                    continue
                if any(v < vh - cfg['toleranceAtr'] * atr
                       for j, v in pivots_list if il <= j <= ir):
                    continue
            if abs(vl - vr) > cfg['toleranceAtr'] * atr:
                continue
            v1, n1 = simple_neckline(rows, il, ih, side)
            v2, n2 = simple_neckline(rows, ih, ir, side)
            candidates.append(dict(
                type=kind, direction='down' if sign == -1 else 'up', sign=sign,
                peaks=[(il, vl), (ih, vh), (ir, vr)],
                neckline=[(n1, v1), (n2, v2)], necklineIndexes=[n1, n2],
                flat=v1 == v2, spanBars=ir - il + 1,
                toleranceAtr=cfg['toleranceAtr'], headExcessAtr=cfg['headExcessAtr']))
    candidates.sort(key=lambda c: (c['peaks'][0][0], c['peaks'][1][0]))
    return candidates


def neckline_at(candidate, index):
    """Line through the two neckline anchors, sampled by trading-bar ordinal."""
    (k1, v1), (k2, v2) = candidate['neckline']
    if k1 == k2 or v1 == v2:
        return v1
    return v1 + (v2 - v1) * (index - k1) / (k2 - k1)


def geometry(candidate, rows):
    """Polygon points for the chart: peaks plus the actual neckline anchors."""
    (k1, v1), (k2, v2) = candidate['neckline']
    # 위쪽 경로를 왼쪽에서 오른쪽으로 그린 뒤 목선을 오른쪽에서 왼쪽으로 되돌린다.
    # 목선을 사이에 끼우면 변이 교차해 채움 도형이 꼬인다.
    if len(candidate['peaks']) == 2:
        (i1, p1), (i2, p2) = candidate['peaks']
        points = [dict(time=rows[i1]['time'], price=p1),
                  dict(time=rows[i2]['time'], price=p2),
                  dict(time=rows[k2]['time'], price=v2),
                  dict(time=rows[k1]['time'], price=v1)]
    else:
        (il, vl), (ih, vh), (ir, vr) = candidate['peaks']
        points = [dict(time=rows[il]['time'], price=vl),
                  dict(time=rows[ih]['time'], price=vh),
                  dict(time=rows[ir]['time'], price=vr),
                  dict(time=rows[k2]['time'], price=v2),
                  dict(time=rows[k1]['time'], price=v1)]
    return dict(kind=candidate['type'], points=points)
