"""Toss adjusted minute history, bounded pagination and incremental refresh.

One shared client/budget; no Yahoo fallback after a Toss error. Failed backfills
retain checkpoints, never publish their partial history as a fresh chart frame.
"""
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from time import time
from zoneinfo import ZoneInfo

from market_store import epoch, revision


class MinuteCollection:
    TARGET_BARS = 260
    MAX_PAGES = 512

    def __init__(self, client, store=None, clock=time):
        self.client, self.store, self.clock = client, store, clock
        self.lock = RLock()
        self.memory = {}

    def _get(self, key):
        return self.store.get(key) if self.store else deepcopy(self.memory.get(key))

    def _put(self, key, value):
        if self.store:
            self.store.put(key, {**value, 'dataRevision': revision(value['rows'])})
        else:
            self.memory[key] = deepcopy(value)

    def _page(self, symbol, tz, before=None):
        from toss_market import normalize_candles, TossError
        params = dict(symbol=symbol, interval='1m', count=200, adjusted='true')
        if before:
            params['before'] = before
        reply = self.client.get('/api/v1/candles', **params)
        rows = normalize_candles(reply.get('candles', []), tz, interval='1m')
        if before and any(r['t'] > epoch(before) for r in rows):
            raise TossError('history-page-out-of-range')
        return rows, reply.get('nextBefore')

    @staticmethod
    def _bar_count(indexed, tz):
        # Match to_4h's exchange-date/first-source-bar anchoring. The oldest
        # fetched day may start mid-session, so it cannot count toward readiness.
        days = {}
        zone = ZoneInfo(tz)
        for t in sorted(indexed):
            day = datetime.fromtimestamp(t, zone).date()
            origin, buckets = days.setdefault(day, (t, set()))
            buckets.add((t-origin)//14400)
        first = min(days) if days else None
        return sum(len(buckets) for day, (_, buckets) in days.items() if day != first)

    def _full(self, symbol, tz, stage_key):
        from toss_market import TossError
        stage = self._get(stage_key)
        indexed = {r['t']: r for r in stage['rows']} if stage else {}
        before = stage.get('cursor') if stage else None
        seen = set(stage.get('seen', [])) if stage else set()
        pages = stage.get('pages', 0) if stage else 0
        cutoff = self.clock() - 186*86400
        exhausted = False
        try:
            while pages < self.MAX_PAGES:
                rows, cursor = self._page(symbol, tz, before)
                for row in rows:
                    previous = indexed.get(row['t'])
                    if previous is not None and previous != row:
                        raise TossError('adjusted-history-conflict')
                    indexed[row['t']] = row
                pages += 1
                exhausted = not rows or not cursor
                if exhausted:
                    break
                if cursor in seen or (before and epoch(cursor) >= epoch(before)):
                    raise TossError('history-cursor-repeated')
                seen.add(cursor)
                before = cursor
                if min(indexed) <= cutoff or self._bar_count(indexed, tz) >= self.TARGET_BARS:
                    break
                if pages % 8 == 0:
                    self._put(stage_key, dict(rows=list(indexed.values()), cursor=before,
                                             seen=sorted(seen), pages=pages))
        except TossError as error:
            # Save only coherent completed pages. Conflicting/malformed pages
            # cannot be resumed as trustworthy adjusted history.
            if indexed and error.code in ('rate-limited', 'network-or-timeout',
                                          'upstream-error', 'authentication-failed',
                                          'permission-or-ip-denied'):
                self._put(stage_key, dict(rows=list(indexed.values()), cursor=before,
                                         seen=sorted(seen), pages=pages))
            else:
                self._put(stage_key, dict(rows=[], cursor=None, seen=[], pages=0))
            raise
        if not indexed:
            raise TossError('no-candles')
        # Refresh the head after lengthy historical paging. fetchedAt must not
        # disguise an old initial page as freshly acquired current candles.
        latest, _ = self._page(symbol, tz)
        if not latest or latest[-1]['t'] < max(indexed):
            raise TossError('history-head-regressed')
        if latest[0]['t'] > max(indexed):
            raise TossError('history-head-gap')
        if any(r['t'] < max(indexed)-600 and r['t'] in indexed and
               any(r[k] != indexed[r['t']][k] for k in ('open','high','low','close'))
               for r in latest):
            self._put(stage_key, dict(rows=[], cursor=None, seen=[], pages=0))
            raise TossError('adjusted-history-conflict')
        indexed.update({r['t']: r for r in latest})
        data = [indexed[t] for t in sorted(indexed) if t >= cutoff]
        if not exhausted and data:
            day = datetime.fromtimestamp(data[0]['t'], ZoneInfo(tz)).date()
            data = [r for r in data if datetime.fromtimestamp(r['t'], ZoneInfo(tz)).date() != day]
        if not data:
            raise TossError('no-complete-history-day')
        return data, dict(pages=pages, limited=pages >= self.MAX_PAGES,
                          exhausted=exhausted, targetBars=self.TARGET_BARS)

    def _recent(self, symbol, tz, old):
        from toss_market import TossError
        indexed = {r['t']: r for r in old['rows']}
        latest_t = max(indexed)
        boundary = latest_t - 4*3600
        recent, before, seen = {}, None, set()
        for _ in range(self.MAX_PAGES):
            rows, cursor = self._page(symbol, tz, before)
            for row in rows:
                previous = recent.get(row['t'])
                if previous is not None and previous != row:
                    raise TossError('adjusted-history-conflict')
                recent[row['t']] = row
            if not rows:
                raise TossError('no-candles')
            if min(recent) <= boundary and any(t in indexed for t in recent):
                break
            if not cursor:
                if any(t in indexed for t in recent):
                    break
                return None
            if cursor in seen or (before and epoch(cursor) >= epoch(before)):
                raise TossError('history-cursor-repeated')
            seen.add(cursor); before = cursor
        else:
            raise TossError('history-page-limit')
        if max(recent) < latest_t:
            raise TossError('history-head-regressed')
        # Earlier closed-bar price changes can signal an adjustment correction.
        # Ongoing/recent minute changes are expected and simply replace the head.
        if any(t < latest_t-600 and t in indexed and
               any(recent[t][k] != indexed[t][k] for k in ('open','high','low','close'))
               for t in recent):
            return None
        indexed.update(recent)
        cutoff = self.clock() - 186*86400
        data = [indexed[t] for t in sorted(indexed) if t >= cutoff]
        if data and min(indexed) < cutoff:
            first_day = datetime.fromtimestamp(data[0]['t'], ZoneInfo(tz)).date()
            data = [r for r in data if datetime.fromtimestamp(r['t'], ZoneInfo(tz)).date() != first_day]
        return data or None

    def minute(self, code, tz, force=False):
        from toss_market import toss_symbol
        symbol = toss_symbol(code)
        key = '|'.join(('candles', symbol, '1m', 'adjusted', tz, 'v1'))
        stage_key = key+'|backfill'
        with self.lock:
            old, now = self._get(key), self.clock()
            age = now-epoch(old['fetchedAt']) if old else None
            if old and 0 <= age < (10 if force else 30):
                return deepcopy(old['rows']), True, old['fetchedAt'], old['dataRevision'], old['history']
            full = not old or now-old['fullRefreshAt'] >= 86400
            data = None if full else self._recent(symbol, tz, old)
            if data is None:
                data, history = self._full(symbol, tz, stage_key)
                full = True
            else:
                history = old['history']
            fetched = datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec='seconds')
            value = dict(rows=data, fetchedAt=fetched, dataRevision=revision(data), history=history,
                         fullRefreshAt=self.clock() if full else old['fullRefreshAt'])
            self._put(key, value)
            self._put(stage_key, dict(rows=[], cursor=None, seen=[], pages=0))
            return deepcopy(data), False, fetched, value['dataRevision'], deepcopy(history)
