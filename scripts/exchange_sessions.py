"""Local regular-session calendars for keyless Yahoo Finance operation."""
from functools import lru_cache


@lru_cache(maxsize=2)
def _calendar(market):
    import exchange_calendars
    name = {'KR': 'XKRX', 'US': 'XNYS'}[market]
    return exchange_calendars.get_calendar(name)


def calendar_days(market, query_date):
    """Return today's, previous and next sessions, including explicit holidays.

    These are maintained exchange schedules, not live exchange status. Never
    guess weekday hours if the dependency or supported date range is missing.
    """
    try:
        import pandas as pd
        cal = _calendar(market)
        session = cal.is_session(query_date)
        previous = cal.date_to_session(query_date, direction='previous')
        following = cal.date_to_session(query_date, direction='next')
        if session:
            previous = cal.previous_session(previous)
            following = cal.next_session(following)
        days = {query_date: ()}
        for label in (previous, following, query_date if session else None):
            if label is None:
                continue
            row = cal.schedule.loc[label]
            start, end = row['open'].to_pydatetime(), row['close'].to_pydatetime()
            if pd.notna(row['break_start']) and pd.notna(row['break_end']):
                intervals = ((start, row['break_start'].to_pydatetime()),
                             (row['break_end'].to_pydatetime(), end))
            else:
                intervals = ((start, end),)
            days[str(label)[:10]] = intervals
        return days
    except (ImportError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ValueError('exchange-calendar-unavailable') from exc
