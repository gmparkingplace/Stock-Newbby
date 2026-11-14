"""Bounded in-process phase timings for collection and calculation.

Only a small fixed vocabulary of area/phase names is recorded; symbols, query
strings, payloads, credentials and exception messages never enter this module.
Counters are per process and require no configuration.
"""
from threading import Lock
from time import monotonic

LIMIT = 64
_LOCK = Lock()
_ROWS = {}


def record(key, elapsed_ms, failed=False):
    with _LOCK:
        row = _ROWS.get(key)
        if row is None:
            if len(_ROWS) >= LIMIT:
                return
            row = _ROWS[key] = dict(count=0, totalMs=0.0, maxMs=0.0, lastMs=0.0, failures=0)
        row['count'] += 1
        row['totalMs'] = round(row['totalMs'] + elapsed_ms, 2)
        row['maxMs'] = round(max(row['maxMs'], elapsed_ms), 2)
        row['lastMs'] = round(elapsed_ms, 2)
        row['failures'] += int(bool(failed))


class span:
    """Context manager: ``with span('market','queue-wait'): ...``."""
    __slots__ = ('key', 'started')

    def __init__(self, area, phase):
        self.key = str(area) + '.' + str(phase)
        self.started = monotonic()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, trace):
        record(self.key, (monotonic() - self.started) * 1000.0, kind is not None)
        return False


def snapshot():
    with _LOCK:
        return {key: dict(row, avgMs=round(row['totalMs'] / row['count'], 2) if row['count'] else 0.0)
                for key, row in sorted(_ROWS.items())}


def reset():
    with _LOCK:
        _ROWS.clear()
