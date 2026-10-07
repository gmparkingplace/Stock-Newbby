"""Identify missing stock H4 buckets without counting market closures as gaps."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def trim_first_session(frame, symbol):
    """Yahoo rolling lookbacks may begin mid-session; omit that partial first day."""
    from universe import is_coin, market_of
    if is_coin(symbol) or frame.empty:
        return frame, []
    from exchange_sessions import calendar_days
    tz = market_of(symbol)[0]
    local = frame.index.tz_convert(tz)
    day = local[0].date().isoformat()
    market = 'KR' if tz == 'Asia/Seoul' else 'US'
    intervals = calendar_days(market, day).get(day, ())
    if not intervals or local[0].to_pydatetime() == min(s for s, _ in intervals):
        return frame, []
    keep = local.date != local[0].date()
    trimmed = frame.loc[keep].copy()
    if trimmed.empty:
        raise ValueError('완전한 거래일의 4시간봉 자료 부족')
    return trimmed, [dict(code='partial-first-yahoo-session', sessionDate=day,
                         excludedSourceBars=int((~keep).sum()))]


def annotate(candles, symbol):
    from universe import is_coin, market_of
    if is_coin(symbol) or not candles:
        return
    from exchange_sessions import calendar_days
    tz = market_of(symbol)[0]
    market = 'KR' if tz == 'Asia/Seoul' else 'US'
    first, last = (datetime.fromtimestamp(candles[i]['time'], timezone.utc)
                   for i in (0, -1))
    day, final = first.astimezone(ZoneInfo(tz)).date(), last.astimezone(ZoneInfo(tz)).date()
    expected = set()
    while day <= final:
        intervals = calendar_days(market, day.isoformat()).get(day.isoformat(), ())
        if intervals:
            start, end = min(s for s, _ in intervals), max(e for _, e in intervals)
            while start < end:
                if any(s <= start < e for s, e in intervals):
                    expected.add(int(start.timestamp()))
                start += timedelta(hours=4)
        day += timedelta(days=1)
    positions = {stamp: i for i, stamp in enumerate(sorted(expected))}
    previous = None
    for candle in candles:
        stamp = candle['time']
        if stamp not in positions:
            raise ValueError('4시간봉 시작 시각이 거래 세션과 다릅니다')
        position = positions[stamp]
        candle['missingBarsBefore'] = 0 if previous is None else position - previous - 1
        previous = position
