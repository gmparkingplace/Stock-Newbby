"""P2 지표 계산: 스냅샷 -> A/B/C 지표값 + 확정봉 신호.

규칙 출처: Research.md '첫 비교 실험의 제안 규칙' (값은 exp002와 동일).
실행: .venv/bin/python scripts/indicators.py
입력: data/snapshots/exp002/ohlcv.csv
출력: results/exp002/indicators_satl.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TARGET = "SATL"
EVAL_START = "2022-09-01"
FAST, SLOW = 20, 60
RSI_PERIOD, RSI_ENTRY, RSI_EXIT = 14, 30, 70
C_ENTRY_LB, C_EXIT_LB = 20, 10
OUT = ROOT / "results" / "exp002" / "indicators_satl.csv"


def wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    # Wilder 원식: 첫 평균 = 앞 period개 단순평균, 이후 재귀 평활.
    # ewm(adjust=False)은 첫 관측값으로 초기화해서 시드가 다르므로 직접 구현한다.
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    ag = avg_gain.to_numpy().copy()
    al = avg_loss.to_numpy().copy()
    g = gain.to_numpy()
    l = loss.to_numpy()
    for i in range(period + 1, len(close)):
        if ag[i - 1] != ag[i - 1] or g[i] != g[i]:  # NaN 방어 (결측 봉)
            continue
        ag[i] = (ag[i - 1] * (period - 1) + g[i]) / period
        al[i] = (al[i - 1] * (period - 1) + l[i]) / period
    avg_gain = pd.Series(ag, index=close.index)
    avg_loss = pd.Series(al, index=close.index)
    rsi = 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi.mask(avg_loss == 0, 100.0)  # 무변동 구간 0/0 -> 100 (검증 루프와 동일)


def wilder_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    # Wilder ADX: DM/TR 초기 period개 단순평균 후 재귀 평활, DX의 첫 ADX는 앞 period개 평균.
    up, dn = high.diff(), -low.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    a = tr.rolling(period, min_periods=period).mean().to_numpy().copy()
    pv = plus_dm.rolling(period, min_periods=period).mean().to_numpy().copy()
    mv = minus_dm.rolling(period, min_periods=period).mean().to_numpy().copy()
    tv, gv, lv = tr.to_numpy(), plus_dm.to_numpy(), minus_dm.to_numpy()
    for i in range(period + 1, len(close)):
        if a[i - 1] != a[i - 1] or tv[i] != tv[i]:
            continue
        a[i] = (a[i - 1] * (period - 1) + tv[i]) / period
        pv[i] = (pv[i - 1] * (period - 1) + gv[i]) / period
        mv[i] = (mv[i - 1] * (period - 1) + lv[i]) / period
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi, mdi = 100 * pv / a, 100 * mv / a
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    dx[(pdi + mdi) == 0] = 0.0
    av = pd.Series(dx, index=close.index).rolling(period, min_periods=period).mean().to_numpy().copy()
    dv = pd.Series(dx, index=close.index).to_numpy()
    for i in range(2 * period - 1, len(close)):
        if av[i - 1] != av[i - 1] or dv[i] != dv[i]:
            continue
        av[i] = (av[i - 1] * (period - 1) + dv[i]) / period
    return pd.Series(av, index=close.index)


def cross_up(fast: pd.Series, slow: pd.Series) -> pd.Series:
    return (fast.shift(1) <= slow.shift(1)) & (fast > slow)


def cross_down(fast: pd.Series, slow: pd.Series) -> pd.Series:
    return (fast.shift(1) >= slow.shift(1)) & (fast < slow)


def main() -> None:
    snap = pd.read_csv(ROOT / "data" / "snapshots" / "exp002" / "ohlcv.csv", parse_dates=["date"])
    df = snap[snap["symbol"] == TARGET].sort_values("date").reset_index(drop=True)
    close, high, low = df["close"], df["high"], df["low"]

    sma20 = close.rolling(FAST, min_periods=FAST).mean()
    sma60 = close.rolling(SLOW, min_periods=SLOW).mean()
    rsi = wilder_rsi(close, RSI_PERIOD)
    don_hi = high.shift(1).rolling(C_ENTRY_LB, min_periods=C_ENTRY_LB).max()
    don_lo = low.shift(1).rolling(C_EXIT_LB, min_periods=C_EXIT_LB).min()

    out = pd.DataFrame({
        "date": df["date"].dt.date.astype(str),
        "close": close.round(4), "sma20": sma20.round(4), "sma60": sma60.round(4),
        "rsi14": rsi.round(4), "don_hi20": don_hi.round(4), "don_lo10": don_lo.round(4),
    })
    ready = sma60.notna() & rsi.notna() & don_hi.notna() & don_lo.notna()
    sig_a, sig_b, sig_c = pd.Series("none", index=df.index), pd.Series("none", index=df.index), pd.Series("none", index=df.index)
    sig_a[cross_up(sma20, sma60) & ready] = "entry"
    sig_a[cross_down(sma20, sma60) & ready] = "exit"
    sig_b[(rsi.shift(1) <= RSI_ENTRY) & (rsi > RSI_ENTRY) & ready] = "entry"
    sig_b[(rsi.shift(1) >= RSI_EXIT) & (rsi < RSI_EXIT) & ready] = "exit"
    sig_c[(close > don_hi) & ready] = "entry"
    sig_c[(close < don_lo) & ready] = "exit"
    out["sigA"], out["sigB"], out["sigC"] = sig_a, sig_b, sig_c
    out["in_eval"] = df["date"] >= pd.Timestamp(EVAL_START)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    ev = out[out["in_eval"]]
    print(f"rows={len(out)} eval_rows={len(ev)} "
          f"A={dict(ev['sigA'].value_counts())} B={dict(ev['sigB'].value_counts())} C={dict(ev['sigC'].value_counts())}")


if __name__ == "__main__":
    main()
