"""P4 과거 성과 비교: 동일 평가기간·자본·규칙으로 A/B/C + 매수후 보유(B&H).

실행: .venv/bin/python scripts/backtest_p4.py
입력: snapshots/exp002/ohlcv.csv + indicators_satl.csv + trades_{A,B,C}.csv
출력: results/exp002/equity_{A,B,C,BH}.csv + performance_p4.md
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "exp002"
INITIAL = 10_000.0
STRATS = ("A", "B", "C")


def simulate(dates, opens, closes, events, commission_bps: float = 0.0,
             sell_tax_bps: float = 0.0, slippage_bps: float = 0.0):
    """events: {date: ('buy'|'sell', price)}. 일별 지분 곡선 반환.
    전부 0이면 비용 0 베이스라인과 비트 동일."""
    comm = commission_bps / 10_000.0
    tax = sell_tax_bps / 10_000.0
    slip = slippage_bps / 10_000.0
    cash, shares = INITIAL, 0.0
    equity, held = [], []
    for d, o, c in zip(dates, opens, closes):
        if d in events:
            side, px = events[d]
            if side == "buy" and cash > 0:
                fee = cash * comm
                shares, cash = (cash - fee) / (px * (1 + slip)), 0.0
            elif side == "sell" and shares > 0:
                px_adj = px * (1 - slip)
                proceeds = shares * px_adj
                cash, shares = proceeds * (1 - comm - tax), 0.0
        equity.append(cash + shares * c)
        held.append(1 if shares > 0 else 0)
    return equity, held


def max_dd(equity: list[float]) -> float:
    peak, mdd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd


def seg_metrics(equity: list[float], held: list[int]) -> dict:
    n = len(equity)
    return {"net_ret_pct": round((equity[-1] / equity[0] - 1) * 100, 2),
            "mdd_pct": round(max_dd(equity) * 100, 2),
            "exposure_pct": round(sum(held) / n * 100, 1)}


def main() -> None:
    snap = pd.read_csv(ROOT / "data" / "snapshots" / "exp002" / "ohlcv.csv", parse_dates=["date"])
    ind = pd.read_csv(RES / "indicators_satl.csv", parse_dates=["date"])
    satl = snap[snap["symbol"] == "SATL"].sort_values("date").reset_index(drop=True)
    satl["date_s"] = satl["date"].dt.date.astype(str)
    ind["date_s"] = ind["date"].dt.date.astype(str)
    ev = ind[ind["in_eval"]].merge(satl[["date_s", "open", "close"]],
                                   on="date_s", how="left",
                                   suffixes=("", "_snap")).reset_index(drop=True)
    ev["close"] = ev["close_snap"]  # 스냅샷 정밀도(6자리) 사용, 지표 CSV 반올림값 아님
    dates, opens, closes = ev["date_s"].tolist(), ev["open"].tolist(), ev["close"].tolist()
    n, mid = len(ev), len(ev) // 2

    curves, segs, trade_rows = {}, {}, {}
    for s in STRATS:
        t = pd.read_csv(RES / f"trades_{s}.csv", dtype=str).fillna("")
        events = {}
        for _, r in t.iterrows():
            if r["entry_exec_date"]:
                events[r["entry_exec_date"]] = ("buy", float(r["entry_price"]))
            if r["exit_exec_date"]:
                events[r["exit_exec_date"]] = ("sell", float(r["exit_price"]))
        eq, held = simulate(dates, opens, closes, events)
        curves[s] = (eq, held)
        segs[s] = {"full": seg_metrics(eq, held),
                   "h1": seg_metrics(eq[:mid], held[:mid]),
                   "h2": seg_metrics(eq[mid:], held[mid:])}
        done = t[t["status"] == "completed"]
        pnl = done["pnl"].astype(float).tolist() if len(done) else []
        hp = [(dates.index(r["exit_exec_date"]) - dates.index(r["entry_exec_date"]))
              for _, r in done.iterrows()] if len(done) else []
        trade_rows[s] = {"completed": len(done),
                         "open": int((t["status"] == "open").sum()),
                         "win_rate_pct": round(sum(1 for v in pnl if v > 0) / len(pnl) * 100, 1) if pnl else "-",
                         "avg_pnl": round(sum(pnl) / len(pnl), 2) if pnl else "-",
                         "avg_hold_bars": round(sum(hp) / len(hp), 1) if hp else "-"}
        pd.DataFrame({"date": dates, "equity": [round(v, 2) for v in eq]}
                     ).to_csv(RES / f"equity_{s}.csv", index=False)

    # B&H: 첫 평가봉 다음 시가에 전액 매수, 기말까지 보유 (전략과 동일 체결 조건)
    bh_events = {dates[1]: ("buy", opens[1])}
    eq, held = simulate(dates, opens, closes, bh_events)
    curves["BH"] = (eq, held)
    segs["BH"] = {"full": seg_metrics(eq, held),
                  "h1": seg_metrics(eq[:mid], held[:mid]),
                  "h2": seg_metrics(eq[mid:], held[mid:])}
    trade_rows["BH"] = {"completed": 0, "open": 1, "win_rate_pct": "-",
                        "avg_pnl": "-", "avg_hold_bars": n - 1}
    pd.DataFrame({"date": dates, "equity": [round(v, 2) for v in eq]}
                 ).to_csv(RES / "equity_BH.csv", index=False)
    print("BH buy:", dates[1], opens[1], "final:", round(eq[-1], 2))

    md = ["# P4 성과 비교 (exp002, 평가 %s~%s, %d봉)" % (dates[0], dates[-1], n), "",
          "- 동일 조건: 초기자본 10,000 USD·전액/전량·비용 0·t+1 시가·조정가격. B&H는 첫 평가봉 다음 시가 매수 후 보유.",
          "- 웜업(평가 시작 전 147봉)은 파라미터 준비용으로만 사용, 성과 집계 제외. 규칙 변경 시 실험 번호를 새로 발급한다.", "",
          "| 전략 | 순수익% | MDD% | 노출% | 완료 | 미청산 | 승률% | 평균손익 | 평균보유봉 |",
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for s in (*STRATS, "BH"):
        f, tr = segs[s]["full"], trade_rows[s]
        md.append(f"| {s} | {f['net_ret_pct']} | {f['mdd_pct']} | {f['exposure_pct']} | "
                  f"{tr['completed']} | {tr['open']} | {tr['win_rate_pct']} | {tr['avg_pnl']} | {tr['avg_hold_bars']} |")
    md += ["", "| 전략 | 전반기 순수익% | 전반기 MDD% | 후반기 순수익% | 후반기 MDD% |",
           "| --- | ---: | ---: | ---: | ---: |"]
    for s in (*STRATS, "BH"):
        h1, h2 = segs[s]["h1"], segs[s]["h2"]
        md.append(f"| {s} | {h1['net_ret_pct']} | {h1['mdd_pct']} | {h2['net_ret_pct']} | {h2['mdd_pct']} |")
    md += ["", f"- 후반기 시작 자본 = 전반기 종료 지분(연속 곡선). 전반기 {dates[0]}~{dates[mid-1]}, 후반기 {dates[mid]}~{dates[-1]}.",
           "- 미청산(open)은 자동 청산 없이 기말 종가 평가로 포함. 미체결(unfilled)은 집계 없음.",
           "- 비용 0 베이스라인(세전, 실전 아님). 소형주 t+1 시가 체결 한계는 결과 해석 시 유의."]
    (RES / "performance_p4.md").write_text("\n".join(md) + "\n")
    for s in (*STRATS, "BH"):
        print(s, segs[s]["full"], trade_rows[s])


if __name__ == "__main__":
    main()
