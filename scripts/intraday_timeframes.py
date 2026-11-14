"""Intraday timeframe contract shared by collection, confirmation and patterns.

The chart can show 5m..4h bars. H4 keeps its existing rule/version behavior;
new intraday timeframes reuse the same bar rules and are labelled as trial
patterns until separately evaluated.
"""
from __future__ import annotations

INTRADAY_MINUTES = {
    'M5': 5,
    'M15': 15,
    'M30': 30,
    'H1': 60,
    'H2': 120,
    'H4': 240,
}

# Enough history for the 60-bar indicators and pattern warm-up without making
# a 5m chart slow to calculate. H4 keeps its previous 260-bar tail.
INTRADAY_TAIL_BARS = {
    'M5': 800,
    'M15': 800,
    'M30': 800,
    'H1': 600,
    'H2': 400,
    'H4': 260,
}

INTRADAY_LABELS = {
    'M5': '5분봉',
    'M15': '15분봉',
    'M30': '30분봉',
    'H1': '1시간봉',
    'H2': '2시간봉',
    'H4': '4시간봉',
}

# New intraday timeframes are displayed but their patterns have not been
# calibrated or evaluated as a trading rule.
TRIAL_TIMEFRAMES = frozenset(('M5', 'M15', 'M30', 'H1', 'H2'))


def is_intraday(tf: str) -> bool:
    return tf in INTRADAY_MINUTES


def minutes(tf: str) -> int:
    try:
        return INTRADAY_MINUTES[tf]
    except KeyError:
        raise ValueError('unsupported-intraday-timeframe') from None


def seconds(tf: str) -> int:
    return minutes(tf) * 60


def tail_bars(tf: str) -> int:
    try:
        return INTRADAY_TAIL_BARS[tf]
    except KeyError:
        raise ValueError('unsupported-intraday-timeframe') from None


def label(tf: str) -> str:
    return INTRADAY_LABELS.get(tf, tf)


def aggregation(tf: str) -> str:
    return 'exchange-date-first-minute-' + str(minutes(tf)) + 'min'


def is_trial(tf: str) -> bool:
    return tf in TRIAL_TIMEFRAMES
