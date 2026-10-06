"""순수 계산: 봉 집계·지표·신호·피보나치 (serve_dashboard에서 분리, 동작 동일).
I/O·캐시·시각 계약 없음. 의존: fetch_snapshot/indicators/kr_p5만."""
import pandas as pd

from fetch_snapshot import to_adjusted
from indicators import cross_down, cross_up, wilder_rsi
from kr_p5 import atr_wilder

FAST, SLOW, RSI_P = 20, 60, 14


def to_weekly(d: pd.DataFrame) -> pd.DataFrame:
    x = d.copy()
    x["dt"] = pd.to_datetime(x["t"])
    x = x.set_index("dt")
    w = pd.DataFrame({"open": x["open"].resample("W-FRI").first(),
                      "high": x["high"].resample("W-FRI").max(),
                      "low": x["low"].resample("W-FRI").min(),
                      "close": x["close"].resample("W-FRI").last(),
                      "volume": x["volume"].resample("W-FRI").sum()})
    w = w.dropna().reset_index(names="dt")
    w["t"] = w["dt"].dt.date.astype(str)
    return w

def to_monthly(d: pd.DataFrame):
    # 일봉 → 월봉 집계. 주식(거래일)과 코인(UTC일) 모두 일봉 날짜가 해당 시장의
    # 날짜이므로 YYYY-MM 그룹으로 묶는다. 라벨은 해당 월의 마지막 달력일(YYYY-MM-DD)로
    # 고정하고, 실제 봉 종료 시각(마지막 거래 세션 종료)은 time_contract가 따로 판단한다.
    # 없는 달은 가짜 봉을 만들지 않는다(관측된 달만 집계). 자료 시작이 월중인 경우
    # 첫 월봉은 불완전하므로 제외하고 meta에 표시한다. 진행 중 당월은 잠정으로 유지한다.
    x = d.copy()
    if len(x) == 0:
        empty = pd.DataFrame({"open": [], "high": [], "low": [], "close": [],
                              "volume": [], "t": []})
        return empty, {"droppedIncompleteFirst": False, "dailyBars": 0, "monthlyBars": 0}
    x["ym"] = x["t"].str[:7]
    g = x.groupby("ym", sort=True)
    rows = [{"ym": ym,
             "open": grp["open"].iloc[0],
             "high": grp["high"].max(),
             "low": grp["low"].min(),
             "close": grp["close"].iloc[-1],
             "volume": grp["volume"].sum(),
             "first_day": str(grp["t"].iloc[0])}
            for ym, grp in g]
    meta = {"droppedIncompleteFirst": False, "dailyBars": int(len(x)),
            "monthlyBars": len(rows)}
    if rows and rows[0]["first_day"][8:10] != "01":
        rows = rows[1:]
        meta["droppedIncompleteFirst"] = True
        meta["monthlyBars"] = len(rows)
    w = pd.DataFrame([{"open": r["open"], "high": r["high"], "low": r["low"],
                       "close": r["close"], "volume": r["volume"],
                       "t": pd.Period(r["ym"], freq="M").end_time.date().isoformat()}
                      for r in rows],
                     columns=["open", "high", "low", "close", "volume", "t"])
    return w, meta


def frame(d: pd.DataFrame, live: bool) -> dict:
    close, high, low = d["close"], d["high"], d["low"]
    sma20 = close.rolling(FAST, min_periods=FAST).mean()
    sma60 = close.rolling(SLOW, min_periods=SLOW).mean()
    rsi = wilder_rsi(close, RSI_P)
    don_hi = high.shift(1).rolling(20, min_periods=20).max()
    don_lo = low.shift(1).rolling(10, min_periods=10).min()
    atr = atr_wilder(high, low, close)
    vol_ratio = d["volume"] / d["volume"].rolling(20, min_periods=20).mean()
    ready = sma60.notna() & rsi.notna() & don_hi.notna() & don_lo.notna()
    sig = pd.DataFrame({"A": "none", "B": "none", "C": "none", "F": "none"}, index=d.index)
    sig.loc[cross_up(sma20, sma60) & ready, "A"] = "entry"
    sig.loc[cross_down(sma20, sma60) & ready, "A"] = "exit"
    sig.loc[(rsi.shift(1) <= 30) & (rsi > 30) & ready, "B"] = "entry"
    sig.loc[(rsi.shift(1) >= 70) & (rsi < 70) & ready, "B"] = "exit"
    sig.loc[(close > don_hi) & ready, "C"] = "entry"
    sig.loc[(close < don_lo) & ready, "C"] = "exit"
    gate = (close > sma60) & (sma20 > sma60) & ready
    sig.loc[(close > don_hi) & gate & (vol_ratio > 1.0) & ((close - don_hi) / atr > 0.1), "F"] = "entry"
    sig.loc[((close < don_lo) | cross_down(sma20, sma60)) & ready, "F"] = "exit"
    info = "서버 조회 신호 (원장 없음)" if live else ""
    return {"candles": [{"time": t, "open": round(float(o), 4), "high": round(float(h), 4),
                         "low": round(float(lo), 4), "close": round(float(c), 4),
                         "volume": int(v) if v == v else 0}
                        for t, o, h, lo, c, v in
                        zip(d["t"], d["open"], d["high"], d["low"], d["close"], d["volume"])],
            "lines": {"sma20": [{"time": t, "value": round(float(v), 4)} for t, v in zip(d["t"], sma20) if v == v],
                      "sma60": [{"time": t, "value": round(float(v), 4)} for t, v in zip(d["t"], sma60) if v == v]},
            "marks": {s: [{"time": t, "side": v, "info": info}
                          for t, v in zip(d["t"], sig[s]) if v in ("entry", "exit")]
                      for s in ("A", "B", "C", "F")},
            "state": [{**{"rsi14": None if r != r else round(float(r), 2),
                                "atr14": None if a != a else round(float(a), 2),
                                "vol_ratio": None if w != w else round(float(w), 3),
                                "don_hi": None if h != h else round(float(h), 2),
                                "don_lo": None if lo != lo else round(float(lo), 2)},
                             **{f"sig{s}": v for s, v in
                                zip(("A", "B", "C", "F"), (sa, sb, sc, sf))}}
                      for r, a, w, h, lo, sa, sb, sc, sf in
                      zip(rsi, atr, vol_ratio, don_hi, don_lo,
                          sig["A"], sig["B"], sig["C"], sig["F"])],
            "fib": fib_of(d), "levels": levels_of(d, sma20, sma60, don_hi, don_lo, atr, rsi, vol_ratio)}


def levels_of(d, sma20, sma60, don_hi, don_lo, atr, rsi, vol_ratio) -> dict:
    def num(x):
        v = float(x.iloc[-1])
        return None if v != v else round(v, 4)
    return {"close": round(float(d['close'].iloc[-1]), 4),
            "sma20": num(sma20), "sma60": num(sma60),
            "don_hi": num(don_hi), "don_lo": num(don_lo),
            "atr14": num(atr), "rsi14": num(rsi), "vol_ratio": num(vol_ratio)}


def fib_of(d: pd.DataFrame) -> dict:
    last = d.tail(120)
    hi, lo = float(last["high"].max()), float(last["low"].min())
    rng = hi - lo or 1.0
    return {"from": str(last["t"].iloc[0]), "to": str(last["t"].iloc[-1]), "high": hi, "low": lo,
            "levels": {str(r): round(lo + rng * r, 4)
                       for r in (0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.618)}}


def to_4h(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    # 60분 원천 → 4시간 집계. 공급처(yfinance) 60m 인덱스는 봉 시작 시각(거래소 tz).
    # DST·휴장·단축세션: tz_convert로 처리, 휴장일은 원천에 봉 없음, 단축일은 구성
    # 60분봉이 적어 거래량이 작게 집계됨(있는 그대로 표시, 보간 없음).
    # 세션 경계: 날짜별 그룹 후 그날 시가(첫 60분봉 시작)에 origin을 맞춰
    # 거래일을 넘기는 봉을 만들지 않는다. 코인(24h)은 start_day 유지.
    x = to_adjusted(df).reset_index(names="timestamp")
    x["dt"] = pd.to_datetime(x["timestamp"]).dt.tz_convert(tz)
    if tz == "UTC":
        x = x.set_index("dt")
        w = pd.DataFrame({"open": x["open"].resample("4h", origin="start_day").first(),
                          "high": x["high"].resample("4h", origin="start_day").max(),
                          "low": x["low"].resample("4h", origin="start_day").min(),
                          "close": x["close"].resample("4h", origin="start_day").last(),
                          "volume": x["volume"].resample("4h", origin="start_day").sum()})
        w = w.dropna().reset_index(names="dt")
        w["t"] = w["dt"].map(lambda v: int(v.timestamp()))  # 차트용 UTC초, 봉 시작
        return w
    x["day"] = x["dt"].dt.date
    parts = []
    for _day, g in x.groupby("day"):
        g = g.set_index("dt").sort_index()
        if len(g) == 0:
            continue
        origin = g.index[0]  # 그날 시장 개장(첫 60분봉 시작) 기준
        r = pd.DataFrame({"open": g["open"].resample("4h", origin=origin).first(),
                          "high": g["high"].resample("4h", origin=origin).max(),
                          "low": g["low"].resample("4h", origin=origin).min(),
                          "close": g["close"].resample("4h", origin=origin).last(),
                          "volume": g["volume"].resample("4h", origin=origin).sum()})
        r = r.dropna()
        if len(r):
            parts.append(r)
    if not parts:
        return pd.DataFrame({"open": [], "high": [], "low": [], "close": [],
                             "volume": [], "dt": [], "t": []})
    import pandas as _pd
    w = _pd.concat(parts).sort_index().reset_index(names="dt")
    w["t"] = w["dt"].map(lambda v: int(v.timestamp()))  # 봉 시작 시각
    return w
