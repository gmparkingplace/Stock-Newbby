"""Identify missing stock intraday buckets without counting closures as gaps."""
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


def annotate(candles, symbol, source='yfinance', minutes=240):
    """Stamp each stock intraday bar with how many expected buckets were skipped.

    `source='toss'` uses the provider's integrated session calendar so extended
    hours align with the minute feed; the Yahoo path keeps the local regular
    sessions. Coins have no session grid and are left untouched.
    """
    from universe import is_coin, market_of
    if is_coin(symbol) or not candles:
        return
    if minutes <= 0:
        raise ValueError('invalid-intraday-minutes')
    wording = {5: '5분봉', 15: '15분봉', 30: '30분봉',
               60: '1시간봉', 120: '2시간봉', 240: '4시간봉'}.get(minutes)
    if wording is None:
        raise ValueError('unsupported-intraday-minutes')
    step = timedelta(minutes=minutes)
    from time_contract import calendar_days
    tz = market_of(symbol)[0]
    market = 'KR' if tz == 'Asia/Seoul' else 'US'
    first, last = (datetime.fromtimestamp(candles[i]['time'], timezone.utc)
                   for i in (0, -1))
    day, final = first.astimezone(ZoneInfo(tz)).date(), last.astimezone(ZoneInfo(tz)).date()
    expected = set()
    def add(intervals):
        if not intervals:
            return
        start, end = min(s for s, _ in intervals), max(e for _, e in intervals)
        while start < end:
            if any(s <= start < e for s, e in intervals):
                expected.add(int(start.timestamp()))
            start += step
    # calendar_days returns the requested day plus its previous/next business
    # day, so two consecutive queries cover the range without skipping holidays.
    while day <= final:
        chunk = calendar_days(market, day.isoformat(), source=source)
        for offset in range(2):
            current = day + timedelta(days=offset)
            if current > final:
                break
            add(chunk.get(current.isoformat(), ()))
        day += timedelta(days=2)
    positions = {stamp: i for i, stamp in enumerate(sorted(expected))}
    ordered = sorted(positions)
    previous = None
    for candle in candles:
        stamp = candle['time']
        if stamp not in positions:
            # Toss 1m feeds can start one minute after the session boundary
            # (e.g. 08:01 for an 08:00 bucket). Snap a small offset instead of
            # rejecting the whole H4 stream; larger offsets still fail.
            if not ordered:
                raise ValueError(f'{wording} 시작 시각이 거래 세션과 다릅니다')
            nearest = min(ordered, key=lambda value: abs(value - stamp))
            if abs(nearest - stamp) > 120:
                raise ValueError(f'{wording} 시작 시각이 거래 세션과 다릅니다')
            stamp = nearest
        position = positions[stamp]
        candle['missingBarsBefore'] = 0 if previous is None else position - previous - 1
        previous = position
