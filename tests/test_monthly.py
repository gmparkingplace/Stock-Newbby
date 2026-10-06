import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
"""월봉 집계(to_monthly) 경계 검사: 순수 계산, I/O 없음."""
import pandas as pd

from signals import frame, to_monthly


def daily(rows):
    return pd.DataFrame([{"t": t, "open": o, "high": h, "low": lo, "close": c, "volume": v}
                         for t, o, h, lo, c, v in rows])


def month_days(ym, close0=100.0, step=1.0, skip=()):
    import datetime as dt
    y, m = int(ym[:4]), int(ym[5:7])
    days = []
    d = dt.date(y, m, 1)
    i = 0
    while d.month == m:
        if d.weekday() < 5 and d.isoformat() not in skip:
            p = close0 + i * step
            days.append((d.isoformat(), p - 1, p + 2, p - 2, p, 1000 + i))
            i += 1
        d += dt.timedelta(days=1)
    return days


def test_ohlcv_rules():
    rows = [("2024-01-01", 9, 11, 8, 10, 50),
            ("2024-01-29", 10, 12, 9, 11, 100),
            ("2024-01-30", 11, 15, 10, 14, 200),
            ("2024-01-31", 14, 14, 12, 13, 300),
            ("2024-02-01", 13, 16, 13, 16, 400)]
    w, meta = to_monthly(daily(rows))
    assert list(w["t"]) == ["2024-01-31", "2024-02-29"]
    jan = w.iloc[0]
    assert (jan["open"], jan["high"], jan["low"], jan["close"], jan["volume"]) == (9, 15, 8, 13, 650)
    assert meta == {"droppedIncompleteFirst": False, "dailyBars": 5, "monthlyBars": 2}


def test_year_change_and_leap_february():
    rows = month_days("2023-12", close0=50.0) + month_days("2024-01", close0=60.0) \
        + month_days("2024-02", close0=70.0)
    assert any(t == "2024-02-29" for t, *_ in rows)
    w, meta = to_monthly(daily(rows))
    assert list(w["t"]) == ["2023-12-31", "2024-01-31", "2024-02-29"]
    assert meta["droppedIncompleteFirst"] is False
    feb = w.iloc[2]
    assert feb["close"] == rows[-1][4] and feb["volume"] == sum(r[5] for r in rows if r[0][:7] == "2024-02")


    rows = month_days("2024-05", close0=80.0) + month_days("2024-06", close0=90.0)
    assert rows[-1][0] == "2024-06-28"
    w, meta = to_monthly(daily(rows))
    assert list(w["t"]) == ["2024-05-31", "2024-06-30"]
    june = w.iloc[1]
    assert june["close"] == rows[-1][4]


def test_missing_month_makes_no_fake_bar():
    rows = month_days("2024-01", close0=60.0) + month_days("2024-03", close0=80.0)
    w, meta = to_monthly(daily(rows))
    assert list(w["t"]) == ["2024-01-31", "2024-03-31"]
    assert meta["monthlyBars"] == 2


def test_incomplete_first_month_dropped_with_flag():
    rows = [r for r in month_days("2024-01", close0=60.0) if r[0] >= "2024-01-15"] \
        + month_days("2024-02", close0=70.0)
    w, meta = to_monthly(daily(rows))
    assert list(w["t"]) == ["2024-02-29"]
    assert meta["droppedIncompleteFirst"] is True
    assert meta == {"droppedIncompleteFirst": True, "dailyBars": len(rows), "monthlyBars": 1}


def test_complete_first_month_kept():
    rows = month_days("2024-01", close0=60.0) + month_days("2024-02", close0=70.0)
    assert rows[0][0] == "2024-01-01"
    w, meta = to_monthly(daily(rows))
    assert list(w["t"])[0] == "2024-01-31"
    assert meta["droppedIncompleteFirst"] is False


def test_in_progress_current_month_kept():
    rows = month_days("2024-01", close0=60.0) + [r for r in month_days("2024-02", close0=70.0)
                                                if r[0] <= "2024-02-10"]
    w, meta = to_monthly(daily(rows))
    assert list(w["t"]) == ["2024-01-31", "2024-02-29"]
    assert meta["droppedIncompleteFirst"] is False


def test_empty_input():
    w, meta = to_monthly(daily([]))
    assert len(w) == 0
    assert meta == {"droppedIncompleteFirst": False, "dailyBars": 0, "monthlyBars": 0}


def test_no_future_month_leakage():
    jan = month_days("2024-01", close0=60.0, step=0.1)
    feb = [("2024-02-01", 1000, 1000, 1000, 1000, 999999)]  # 다음 달 급등이 1월에 섞이면 안 됨
    w, _ = to_monthly(daily(jan + feb))
    assert w.iloc[0]["close"] == jan[-1][4]
    assert w.iloc[0]["volume"] == sum(r[5] for r in jan)


def test_short_history_indicators_unavailable():
    rows = []
    for mi in range(1, 13):
        rows += month_days(f"2024-{mi:02d}", close0=50.0 + mi, step=0.0)
    w, _ = to_monthly(daily(rows))
    assert len(w) == 12
    f = frame(w, True)
    assert f["lines"]["sma20"] == [] and f["lines"]["sma60"] == []
    assert f["levels"]["sma20"] is None and f["levels"]["sma60"] is None
    assert all(v == "none" for s in f["state"] for k, v in s.items() if k.startswith("sig"))


def test_twenty_months_gives_sma20_without_sma60():
    rows = []
    for mi in range(1, 13):
        rows += month_days(f"2024-{mi:02d}", close0=40.0 + mi, step=0.0)
    for mi in range(1, 13):
        rows += month_days(f"2025-{mi:02d}", close0=52.0 + mi, step=0.0)
    w, _ = to_monthly(daily(rows))
    assert len(w) == 24
    f = frame(w, True)
    assert len(f["lines"]["sma20"]) == 5 and f["lines"]["sma60"] == []
    assert f["levels"]["sma20"] is not None and f["levels"]["sma60"] is None

def test_coin_utc_days_include_weekends_in_same_month():
    import datetime as dt
    rows = []
    d = dt.date(2024, 1, 1)
    i = 0
    while d.month == 1:
        p = 40000.0 + i * 10
        rows.append((d.isoformat(), p - 5, p + 5, p - 5, p, 100 + i))
        i += 1
        d += dt.timedelta(days=1)
    assert len(rows) == 31  # 주말 포함 UTC 1월 전체
    w, meta = to_monthly(daily(rows))
    assert list(w["t"]) == ["2024-01-31"]
    assert w.iloc[0]["volume"] == sum(range(100, 131))
    assert meta["droppedIncompleteFirst"] is False
