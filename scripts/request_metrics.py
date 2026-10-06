"""In-memory request counters. No query strings, bodies, tokens or symbols."""
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from time import monotonic


class RequestMetrics:
    def __init__(self):
        self.lock = Lock()
        self.rows = {}

    def start(self, operation):
        with self.lock:
            row = self.rows.setdefault(operation, {
                'calls': 0, 'inFlight': 0, 'failures': 0, 'cacheHits': 0,
                'statuses': {}, 'totalDurationMs': 0,
            })
            row['calls'] += 1
            row['inFlight'] += 1
        return monotonic()

    def finish(self, operation, started, status, error_kind=None, cache_hit=False):
        elapsed = round(max(0, monotonic() - started) * 1000, 2)
        with self.lock:
            row = self.rows[operation]
            row['inFlight'] -= 1
            row['failures'] += int(error_kind is not None)
            row['cacheHits'] += int(bool(cache_hit))
            key = str(status) if status is not None else 'network'
            row['statuses'][key] = row['statuses'].get(key, 0) + 1
            row['totalDurationMs'] = round(row['totalDurationMs'] + elapsed, 2)
            row.update(lastStatus=status, lastErrorKind=error_kind, lastDurationMs=elapsed,
                       lastCompletedAt=datetime.now(timezone.utc).isoformat(timespec='seconds'))

    def snapshot(self):
        with self.lock:
            return deepcopy(self.rows)
