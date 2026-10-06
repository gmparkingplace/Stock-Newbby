"""Source collection times and official market-session judgment metadata."""
from time import time as _now

CONFIRM_BUFFER_MIN = 30

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from threading import RLock
import toss_market

_CALENDAR_CACHE = {}
_CALENDAR_LOCK = RLock()


def _aware(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ValueError("timezone-required")
    return result.astimezone(timezone.utc)


def _market(code):
    if code.endswith("-USD"):
        return "continuous", "UTC"
    if code.endswith((".KS", ".KQ")) or code in ("^KS11", "^KQ11"):
        return "KR", "Asia/Seoul"
    return "US", "America/New_York"


def calendar_days(market, query_date):
    """Official three-day calendar. Missing data is not an explicit holiday."""
    date.fromisoformat(query_date)
    with _CALENDAR_LOCK:
        key = (market, query_date)
        hit = _CALENDAR_CACHE.get(key)
        if hit and 0 <= _now() - hit[0] < 60:
            return hit[1]
        if not toss_market.enabled():
            raise ValueError("calendar-not-configured")
        reply = toss_market.CLIENT.get("/api/v1/market-calendar/" + market, date=query_date)
        days = {}
        for role in ("today", "previousBusinessDay", "nextBusinessDay"):
            day = reply[role]
            day_date = date.fromisoformat(day["date"]).isoformat()
            sessions = day["integrated"] if market == "KR" else day
            intervals = []
            if sessions is not None:
                names = ("preMarket", "regularMarket", "afterMarket")
                if market == "US":
                    names = ("dayMarket",) + names
                for name in names:
                    item = sessions[name]
                    if item is None:
                        continue
                    start, end = _aware(item["startTime"]), _aware(item["endTime"])
                    if start >= end:
                        raise ValueError("invalid-calendar-interval")
                    intervals.append((start, end))
            if day_date in days:
                raise ValueError("duplicate-calendar-date")
            days[day_date] = tuple(sorted(intervals))
        if reply["today"]["date"] != query_date:
            raise ValueError("calendar-date-mismatch")
        if not reply["previousBusinessDay"]["date"] < query_date < reply["nextBusinessDay"]["date"]:
            raise ValueError("calendar-date-order")
        if len(_CALENDAR_CACHE) >= 256:
            _CALENDAR_CACHE.pop(next(iter(_CALENDAR_CACHE)))
        _CALENDAR_CACHE[key] = (_now(), days)
        return days


def market_session(code, now=None):
    now = _aware(now or datetime.now(timezone.utc))
    market, tz = _market(code)
    today = now.astimezone(ZoneInfo(tz)).date().isoformat()
    result = dict(state="unknown", market=market, sessionDate=None,
                  checkedAt=now.isoformat(), nextTransitionAt=None, lastSessionEnd=None)
    if market == "continuous":
        return {**result, "state": "open", "sessionDate": today}
    try:
        days = calendar_days(market, today)
        boundaries = sorted({t for intervals in days.values() for pair in intervals for t in pair})
        result["nextTransitionAt"] = next((t.isoformat() for t in boundaries if t > now), None)
        completed = [max(end for _, end in intervals) for intervals in days.values()
                     if intervals and max(end for _, end in intervals) <= now]
        result["lastSessionEnd"] = max(completed).isoformat() if completed else None
        for session_date, intervals in sorted(days.items()):
            if any(start <= now < end for start, end in intervals):
                return {**result, "state": "open", "sessionDate": session_date}
        for session_date, intervals in sorted(days.items()):
            if intervals and min(start for start, _ in intervals) <= now < max(end for _, end in intervals):
                return {**result, "state": "break", "sessionDate": session_date}
        previous = [d for d, intervals in days.items() if intervals and max(e for _, e in intervals) <= now]
        return {**result, "state": "closed", "sessionDate": max(previous) if previous else today}
    except (ValueError, TypeError, KeyError, AttributeError, toss_market.TossError):
        return result


def ttl_cache(ttl: float, maxsize: int = 64):
    """(값, 캐시메타) 반환. force=True면 TTL 무시하고 원천 재조회.
    메타: cacheHit/cacheAge(초)/expiresAt(서버 epoch초)."""
    def deco(fn):
        store = {}

        def wrap(code, force=False):
            t = _now()
            hit = store.get(code)
            if hit and not force and t - hit[0] < ttl:
                return hit[1], {"cacheHit": True, "cacheAge": round(t - hit[0], 1),
                                "expiresAt": hit[0] + ttl}
            v = fn(code)
            if len(store) >= maxsize:
                store.pop(next(iter(store)))
            store[code] = (t, v)
            return v, {"cacheHit": False, "cacheAge": 0.0, "expiresAt": t + ttl}

        wrap.ttl = ttl
        return wrap

    return deco


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def confirmation_at(code, tz, candle_time, tf):
    """Earliest time candidate may be used, subject to a later source fetch."""
    market, _ = _market(code)
    if tf == "H4":
        start = datetime.fromtimestamp(float(candle_time), timezone.utc)
        end = start + timedelta(hours=4)
        day = start.astimezone(ZoneInfo(tz)).date()
    else:
        day = date.fromisoformat(str(candle_time)[:10])
        if tf == "W" and day.weekday() != 4:
            raise ValueError("weekly-label-must-be-friday")
        if tf == "M":
            # 월봉 라벨은 해당 월의 마지막 달력일로 고정한다. 실제 봉 종료 시각
            # (마지막 거래 세션 종료)은 아래에서 따로 구하며 라벨과 구분한다.
            if monthrange(day.year, day.month)[1] != day.day:
                raise ValueError("monthly-label-must-be-month-end")
            if market == "continuous":
                first = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
                end = datetime.combine(first, datetime.min.time(), timezone.utc)
        if not (tf == "M" and market == "continuous"):
            end = datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc)
    if market != "continuous":
        days = calendar_days(market, day.isoformat())
        if tf == "W":
            monday = day - timedelta(days=4)
            candidates = [d for d, intervals in days.items()
                          if monday.isoformat() <= d <= day.isoformat() and intervals]
            if not candidates:
                raise ValueError("weekly-session-unknown")
            intervals = days[max(candidates)]
        elif tf == "H4":
            # Extended sessions may cross midnight; use the containing trading day.
            matching = [v for v in days.values() if any(s <= start < e for s, e in v)]
            if not matching:
                raise ValueError("bucket-session-unknown")
            intervals = matching[0]
        elif tf == "M":
            # 해당 월의 마지막 거래 세션 종료를 사용한다. 조회 창에 월말이 없어도
            # 같은 달·라벨 이전 거래일 중 가장 늦은 종료를 쓴다. 없으면 보류다.
            # 아래 공유 꼬리가 session_end만 읽으므로 (라벨, 종료) 형태로 전달한다.
            month = day.isoformat()[:7]
            ends = [e for d, intervals in days.items()
                    if d[:7] == month and d <= day.isoformat() for _, e in intervals]
            if not ends:
                raise ValueError("monthly-session-unknown")
            intervals = [(day.isoformat(), max(ends))]
        else:
            intervals = days[day.isoformat()]
        if not intervals:
            raise ValueError("no-trading-session")
        session_end = max(e for _, e in intervals)
        end = min(end, session_end) if tf == "H4" else session_end
    return end + timedelta(minutes=CONFIRM_BUFFER_MIN)


def bar_confirmed(code: str, tz: str, last_t, tf: str, now=None) -> bool:
    """Time candidate only; judgment_metadata additionally requires source refresh."""
    try:
        return _aware(now or datetime.now(timezone.utc)) >= confirmation_at(code, tz, last_t, tf)
    except (ValueError, TypeError, KeyError, OverflowError, OSError, toss_market.TossError):
        return False


def judgment_metadata(out, code, tz, tf, now=None, session=None):
    """Shallow-copy frame metadata; never mutate cached payload or candle arrays."""
    result = dict(out)
    now = _aware(now or datetime.now(timezone.utc))
    session = session if session is not None else market_session(code, now)
    candles = out.get("candles", [])
    last = candles[-1]["time"] if candles else None
    result.update(marketSession=session, snapshotEligible=False, lastConfirmedTime=None,
                  confirmed=False, nextConfirmationAt=None, confirmedPolicy="market-calendar")
    try:
        fetched = _aware(out.get("fetchedAt"))
        if fetched > now:
            return result
        data_date = out.get("sourceDate", last)
        if tf == "H4" and last is not None:
            data_date = datetime.fromtimestamp(float(last), timezone.utc).astimezone(ZoneInfo(tz)).date().isoformat()
        result["snapshotEligible"] = bool(candles and session["state"] in ("open", "break")
                                          and str(data_date)[:10] == session["sessionDate"]
                                          and not out.get("lastError"))
        if session["state"] == "unknown" or out.get("lastError"):
            return result
        for candle in reversed(candles):
            try:
                threshold = confirmation_at(code, tz, candle["time"], tf)
            except (ValueError, TypeError, KeyError, toss_market.TossError):
                # Do not fan a failed calendar request out across the entire history.
                break
            if candle["time"] == last:
                result["nextConfirmationAt"] = threshold.isoformat()
            if threshold <= now and threshold <= fetched:
                result["lastConfirmedTime"] = candle["time"]
                result["confirmed"] = candle["time"] == last
                break
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        pass
    return result


def _fresh(out: dict, code: str, tz: str, last_t, tf: str, cache: dict) -> dict:
    result = {**out, "marketAsOf": last_t, "source": "yfinance",
              "delayStatus": "unknown", "barAsOf": None, **cache}
    return judgment_metadata(result, code, tz, tf)
