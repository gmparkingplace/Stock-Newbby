"""패턴 채움 도형이 화면에서 꼬이지 않는지 확인하는 공용 검사."""
import math


def _xy(points, calendar=None):
    out = []
    for p in points:
        if p.get('time'):
            x = calendar.index(p['time']) if calendar else p['time']
        else:
            base = p.get('anchorTime')
            x = (calendar.index(base) + float(p.get('logicalOffset') or 0)
                 if calendar and base in calendar else None)
        out.append((x, p.get('price')))
    return out


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_cross(a, b, c, d):
    d1, d2 = _cross(c, d, a), _cross(c, d, b)
    d3, d4 = _cross(a, b, c), _cross(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def self_intersects(points, calendar=None):
    """변이 교차하거나 좌표가 비정상이면 True. 정상이면 False."""
    xy = _xy(points, calendar)
    if any(x is None or y is None or not math.isfinite(y) for x, y in xy):
        return True
    n = len(xy)
    if n < 3:
        return True
    for i in range(n):
        a, b = xy[i], xy[(i + 1) % n]
        if a == b:
            return True
        for j in range(i + 1, n):
            if (j + 1) % n == i or (i + 1) % n == j:
                continue
            if _segments_cross(a, b, xy[j], xy[(j + 1) % n]):
                return True
    return False
