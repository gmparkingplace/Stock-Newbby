"""P4 검증: 동일 시작일·t+1 체결가·회계 정합·전 후보 존재 확인.

실행: .venv/bin/python scripts/verify_p4.py  (종료코드 0 = 통과)
출력: 결과만 표준출력 (성과표는 backtest_p4.py가 생성)
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "exp002"
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)


def main() -> None:
    snap = pd.read_csv(ROOT / "data" / "snapshots" / "exp002" / "ohlcv.csv", parse_dates=["date"])
    satl = snap[snap["symbol"] == "SATL"].sort_values("date").reset_index(drop=True)
    satl["date_s"] = satl["date"].dt.date.astype(str)
    ind = pd.read_csv(RES / "indicators_satl.csv", parse_dates=["date"])
    ind["date_s"] = ind["date"].dt.date.astype(str)
    eval_dates = ind[ind["in_eval"]]["date_s"].tolist()
    opens = dict(zip(satl["date_s"], satl["open"]))
    closes = dict(zip(satl["date_s"], satl["close"]))

    eqs = {}
    for s in ("A", "B", "C", "BH"):
        e = pd.read_csv(RES / f"equity_{s}.csv", dtype={"date": str})
        eqs[s] = e
        check(f"{s} 동일 평가 시작·종료·봉수",
              e["date"].iloc[0] == eval_dates[0] and e["date"].iloc[-1] == eval_dates[-1]
              and len(e) == len(eval_dates),
              f"rows={len(e)}")

    # 거래 한 건 대조: 첫 A 완료 거래의 시가·수량·손익
    t = pd.read_csv(RES / "trades_A.csv", dtype=str).fillna("")
    r = t[t["status"] == "completed"].iloc[0]
    check("체결가==스냅샷 시가",
          float(r["entry_price"]) == opens[r["entry_exec_date"]]
          and float(r["exit_price"]) == opens[r["exit_exec_date"]],
          f"entry {r['entry_price']} exit {r['exit_price']}")
    shares = 10_000.0 / float(r["entry_price"])
    pnl = shares * float(r["exit_price"]) - 10_000.0
    check("수량·손익 재계산 일치",
          abs(shares - float(r["shares"])) < 1e-6 and abs(pnl - float(r["pnl"])) < 0.01,
          f"shares={r['shares']} pnl={r['pnl']}")

    # 회계 정합: 최종 지분 == 현금 + 보유*종가 (B&H는 보유*종가)
    last = eval_dates[-1]
    eq_bh = eqs["BH"]["equity"].astype(float).tolist()
    bh_shares = 10_000.0 / opens[eval_dates[1]]
    check("B&H 최종==보유*종가",
          abs(eq_bh[-1] - bh_shares * closes[last]) < 0.01, f"{eq_bh[-1]}")

    # MDD 재계산 대조 (전략 A 전구간)
    eq = eqs["A"]["equity"].astype(float).tolist()
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    import re
    perf = (RES / "performance_p4.md").read_text()
    m = re.search(r"\| A \| ([-\d.]+) \| ([-\d.]+) \|", perf)
    check("A 순수익·MDD 표기 일치",
          m and abs(float(m.group(1)) - (eq[-1] / eq[0] - 1) * 100) < 0.01
          and abs(float(m.group(2)) - mdd * 100) < 0.01,
          m.group(0) if m else "no row")

    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
