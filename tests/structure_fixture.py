"""Synthetic double top/bottom and head-and-shoulders series with explicit pivots."""
from datetime import date, timedelta


def _bar(rows, o, c, h, l, v=100):
    rows.append(dict(time=(date(2026, 1, 1) + timedelta(days=len(rows))).isoformat(),
                     open=o, close=c, high=h, low=l, volume=v))


def _warmup(rows):
    for _ in range(20):
        _bar(rows, 100, 100, 101, 99)


def _peak(rows, top):
    """A confirmed pivot high at `top`, surrounded by two lower bars each side."""
    _bar(rows, top - 2, top - 1, top - 1, top - 3)
    _bar(rows, top - 1, top, top, top - 2)      # pivot high
    _bar(rows, top - 1, top - 1, top - 1, top - 3)
    _bar(rows, top - 2, top - 2, top - 1, top - 3)


def _trough(rows, bottom):
    """A confirmed pivot low at `bottom`, surrounded by two higher bars each side."""
    _bar(rows, bottom + 2, bottom + 1, bottom + 3, bottom + 1)
    _bar(rows, bottom + 1, bottom, bottom + 1, bottom)      # pivot low
    _bar(rows, bottom + 1, bottom + 1, bottom + 3, bottom + 1)
    _bar(rows, bottom + 2, bottom + 2, bottom + 3, bottom + 1)


def double_top(confirmed=True):
    rows = []
    _warmup(rows)
    _peak(rows, 106)          # peak1
    _trough(rows, 95)         # neckline
    _peak(rows, 106)          # peak2
    if confirmed:
        _bar(rows, 96, 94, 97, 93)   # close breaks below neckline 95
        _bar(rows, 94, 93, 95, 92)
    return rows


def double_bottom(confirmed=True):
    rows = []
    _warmup(rows)
    _trough(rows, 94)         # trough1
    _peak(rows, 105)          # neckline
    _trough(rows, 94)         # trough2
    if confirmed:
        _bar(rows, 104, 106, 107, 103)  # close breaks above neckline 105
        _bar(rows, 106, 107, 108, 105)
    return rows


def head_shoulders(confirmed=True):
    rows = []
    _warmup(rows)
    _peak(rows, 104)          # left shoulder
    _trough(rows, 97)         # valley 1
    _peak(rows, 108)          # head (higher)
    _trough(rows, 97)         # valley 2
    _peak(rows, 104)          # right shoulder
    if confirmed:
        _bar(rows, 98, 96, 99, 95)   # close breaks below neckline 97
        _bar(rows, 96, 95, 97, 94)
    return rows


def inverse_head_shoulders(confirmed=True):
    rows = []
    _warmup(rows)
    _trough(rows, 96)         # left shoulder
    _peak(rows, 103)          # neckline 1
    _trough(rows, 92)         # head (lower)
    _peak(rows, 103)          # neckline 2
    _trough(rows, 96)         # right shoulder
    if confirmed:
        _bar(rows, 102, 104, 105, 101)  # close breaks above neckline 103
        _bar(rows, 104, 105, 106, 103)
    return rows
