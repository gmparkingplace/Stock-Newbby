"""P2b 시장·섹터 맥락: 베타·상관·상대수익률·추세 계산.

계약 출처: Context-and-Journal.md §3 (수식), exp002 (심볼·추정 창).
실행: .venv/bin/python scripts/context_p2b.py
입력: data/snapshots/exp002/ohlcv.csv (SATL·IWM·ITA 필요)
출력: results/exp002/context_satl.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TARGET, MARKET, SECTOR = "SATL", "IWM", "ITA"
WINDOWS = [60, 120]
REL_LB = 20
VAR_EPS = 1e-12
OUT = ROOT / "results" / "exp002" / "context_satl.csv"


def beta_corr(rs: pd.Series, rm: pd.Series, w: int):
    """과거 W개 수익률(호출자가 t-1까지로 정렬)로 베타·상관·R²·사유 반환."""
    cov = rs.rolling(w, min_periods=w).cov(rm)
    var = rm.rolling(w, min_periods=w).var()
    n = rs.rolling(w, min_periods=w).count()
    beta = cov / var
    corr = rs.rolling(w, min_periods=w).corr(rm)
    reason = pd.Series("ok", index=rs.index)
    reason[n < w] = "insufficient"
    reason[(n >= w) & (var.abs() < VAR_EPS)] = "zero_variance"
    beta = beta.mask(reason != "ok")
    corr = corr.mask(reason != "ok")
    return beta, corr, corr ** 2, reason


def trend(close: pd.Series) -> pd.Series:
    s20 = close.rolling(20, min_periods=20).mean()
    s60 = close.rolling(60, min_periods=60).mean()
    t = pd.Series("undecided", index=close.index)
    ready = s20.notna() & s60.notna()
    t[ready & (close > s60) & (s20 > s60)] = "up"
    t[ready & (close < s60) & (s20 < s60)] = "down"
    t[ready & ~t.isin(["up", "down"])] = "mixed"
    return t


def cumret(close: pd.Series, n: int) -> pd.Series:
    return close / close.shift(n) - 1


def main() -> None:
    snap = pd.read_csv(ROOT / "data" / "snapshots" / "exp002" / "ohlcv.csv", parse_dates=["date"])
    missing = {TARGET, MARKET, SECTOR} - set(snap["symbol"].unique())
    if missing:
        raise SystemExit(f"스냅샷에 {missing} 없음 — fetch_snapshot.py 재실행 필요")
    px = snap.pivot(index="date", columns="symbol", values="close").sort_index()
    rets = px / px.shift(1) - 1  # r(t) = C(t)/C(t-1) - 1, 동일 조정 기준

    out = pd.DataFrame({"date": px.index.date.astype(str)})
    out["trend_satl"] = trend(px[TARGET]).to_numpy()
    out["trend_mkt"] = trend(px[MARKET]).to_numpy()
    out["trend_sec"] = trend(px[SECTOR]).to_numpy()

    for w in WINDOWS:
        for label, bench in (("mkt", MARKET), ("sec", SECTOR)):
            # t봉 맥락은 t-1까지 표본: shift(1) 후 rolling
            b, c, r2, reason = beta_corr(rets[TARGET].shift(1), rets[bench].shift(1), w)
            out[f"beta_{label}_{w}"] = (b.round(6).to_numpy())
            out[f"corr_{label}_{w}"] = (c.round(6).to_numpy())
            out[f"r2_{label}_{w}"] = (r2.round(6).to_numpy())
            out[f"na_{label}_{w}"] = reason.to_numpy()

    cs, cm, ce = cumret(px[TARGET], REL_LB), cumret(px[MARKET], REL_LB), cumret(px[SECTOR], REL_LB)
    out["rel_stock_mkt_pp"] = ((cs - cm) * 100).round(3).to_numpy()
    out["rel_stock_sec_pp"] = ((cs - ce) * 100).round(3).to_numpy()
    out["rel_sec_mkt_pp"] = ((ce - cm) * 100).round(3).to_numpy()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    ev = out[out["date"] >= "2022-09-01"]
    print(f"rows={len(out)} mkt60_ok={int((ev['na_mkt_60'] == 'ok').sum())} "
          f"sec120_ok={int((ev['na_sec_120'] == 'ok').sum())}")


if __name__ == "__main__":
    main()
