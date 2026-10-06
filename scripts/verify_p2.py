"""P2 검증: pandas 계산을 순수 파이썬으로 독립 재계산해 대조 + DoD 어서션.

실행: .venv/bin/python scripts/verify_p2.py  (종료코드 0 = 통과)
출력: results/exp002/spotcheck.md
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "exp002"
SNAP = ROOT / "data" / "snapshots" / "exp002" / "ohlcv.csv"
EVAL_START = "2022-09-01"
SAMPLE_DATES = ["2022-09-01", "2023-06-01", "2024-06-03"]  # 없으면 직전 거래일로 대체
TOL = 1e-3  # indicators_satl.csv는 소수 4자리 반올림이라 반올림 오차(최대 5e-05 + 부동소수) 허용
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)


def plain_sma(vals: list[float], i: int, n: int) -> float | None:
    if i + 1 < n or any(v != v for v in vals[i - n + 1:i + 1]):
        return None
    return sum(vals[i - n + 1:i + 1]) / n


def plain_rsi(vals: list[float], i: int, p: int = 14) -> float | None:
    if i < p:
        return None
    gains, losses = [], []
    for k in range(1, i + 1):
        d = vals[k] - vals[k - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:p]) / p
    al = sum(losses[:p]) / p
    for k in range(p, i):
        ag = (ag * (p - 1) + gains[k]) / p
        al = (al * (p - 1) + losses[k]) / p
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def main() -> None:
    manifest = json.loads((ROOT / "data" / "snapshots" / "exp002" / "manifest.json").read_text())
    check("manifest sha256 일치",
          hashlib.sha256(SNAP.read_bytes()).hexdigest() == manifest["sha256_ohlcv_csv"])

    snap = pd.read_csv(SNAP, parse_dates=["date"])
    for sym in ("SATL", "IWM"):
        d = snap[snap["symbol"] == sym].sort_values("date").reset_index(drop=True)
        check(f"{sym} 시간 단조증가·무중복",
              d["date"].is_monotonic_increasing and not d["date"].duplicated().any())
        check(f"{sym} OHLC 결측 0", int(d[["open", "high", "low", "close"]].isna().sum().sum()) == 0)
        check(f"{sym} 고저가 오류 0",
              int(((d["high"] < d["low"])).sum()) == 0)

    ind = pd.read_csv(RES / "indicators_satl.csv", parse_dates=["date"])
    snap_s = snap[snap["symbol"] == "SATL"].sort_values("date").reset_index(drop=True)
    closes = snap_s["close"].tolist()
    highs = snap_s["high"].tolist()
    lows = snap_s["low"].tolist()
    dates = snap_s["date"].dt.date.astype(str).tolist()

    check("준비구간 SMA60 NaN (앞 59행)", bool(ind["sma60"].head(59).isna().all()))
    check("준비구간 RSI NaN (앞 13행)", bool(ind["rsi14"].head(13).isna().all()))
    eval_ts = pd.Timestamp(EVAL_START)
    ev = ind[ind["date"] >= eval_ts]
    check("평가구간 지표 결측 0",
          int(ev[["sma20", "sma60", "rsi14", "don_hi20", "don_lo10"]].isna().sum().sum()) == 0,
          f"eval_rows={len(ev)}")
    not_ready = ind[["sma60", "rsi14", "don_hi20", "don_lo10"]].isna().any(axis=1)
    check("웜업(지표 미준비) 구간 신호 없음",
          bool((ind[not_ready][["sigA", "sigB", "sigC"]] == "none").all().all()),
          f"not_ready_rows={int(not_ready.sum())}")

    rows_md = []
    for sd in SAMPLE_DATES:
        cand = [d for d in dates if d <= sd]
        if not cand:
            check(f"표본 {sd} 존재", False)
            continue
        d0 = cand[-1]
        i = dates.index(d0)
        r = ind.iloc[i]
        e_sma20, e_sma60 = plain_sma(closes, i, 20), plain_sma(closes, i, 60)
        e_rsi = plain_rsi(closes, i)
        e_hi = max(highs[i - 20:i]) if i >= 20 else None
        e_lo = min(lows[i - 10:i]) if i >= 10 else None
        ok = all(abs((a or 0) - (b or 0)) < TOL
                 for a, b in [(e_sma20, r["sma20"]), (e_sma60, r["sma60"]),
                              (e_rsi, r["rsi14"]), (e_hi, r["don_hi20"]), (e_lo, r["don_lo10"])])
        check(f"독립 재계산 일치 ({d0} <- {sd})", ok,
              f"sma20={r['sma20']} sma60={r['sma60']} rsi={r['rsi14']} hi={r['don_hi20']} lo={r['don_lo10']}")
        rows_md.append((d0, r))

    md = ["# P2 검산표 (SATL, 독립 재계산 대조)", "",
          "| 표본봉 | 종가 | SMA20 | SMA60 | RSI14 | DonHi20 | DonLo10 | A | B | C |",
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |"]
    for d0, r in rows_md:
        md.append(f"| {d0} | {r['close']} | {r['sma20']} | {r['sma60']} | {r['rsi14']} | "
                  f"{r['don_hi20']} | {r['don_lo10']} | {r['sigA']} | {r['sigB']} | {r['sigC']} |")
    md += ["", f" independent recompute: pandas rolling/ewm 미사용 순수 파이썬(Wilder 루프)으로 {len(rows_md)}개 봉 대조, 허용오차 {TOL}.",
           "웜업(지표 NaN) 구간 신호 없음을 전수 확인. 평가 시작 전 ready 구간 신호는 있을 수 있어 검사하지 않음.",
           "전체 PASS 시 P2 계산 DoD 충족."]
    (RES / "spotcheck.md").write_text("\n".join(md) + "\n")
    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
