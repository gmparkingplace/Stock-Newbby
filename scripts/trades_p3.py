"""P3 거래 생성: 확정봉 신호 -> t+1봉 시가 모의 체결, 전액/전량, 비용 0.

규칙 출처: experiments/exp002 (long-only, bar-close 확정, next-open, all-in-all-out).
실행: .venv/bin/python scripts/trades_p3.py
입력: data/snapshots/exp002/ohlcv.csv + results/exp002/indicators_satl.csv
출력: results/exp002/trades_{A,B,C}.csv + trades_summary.md
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "exp002"
INITIAL_CAPITAL = 10_000.0
STRATS = {"A": "sigA", "B": "sigB", "C": "sigC"}


def build(df: pd.DataFrame, sig_col: str, commission_bps: float = 0.0,
          sell_tax_bps: float = 0.0, slippage_bps: float = 0.0,
          include_fees: bool = False) -> tuple[list[dict], dict]:
    """비용 단위: bp(1bp=0.01%). 전부 0이면 비용 0 베이스라인과 비트 동일."""
    comm = commission_bps / 10_000.0
    tax = sell_tax_bps / 10_000.0
    slip = slippage_bps / 10_000.0
    cash, shares, holding = INITIAL_CAPITAL, 0.0, False
    entry_sig_date, entry_exec_date, entry_price = "", "", 0.0
    entry_fees = 0.0
    trades: list[dict] = []
    stats = {"completed": 0, "open": 0, "unfilled": 0,
             "skip_dup_entry": 0, "skip_exit_flat": 0, "fees_paid": 0.0}
    n = len(df)
    for i, r in df.iterrows():
        sig = r[sig_col]
        if sig not in ("entry", "exit"):
            continue
        if i + 1 >= n:  # 마지막 봉: 다음 시가 없음 -> 미체결로 남김
            stats["unfilled"] += 1
            trades.append({"entry_signal_date": r["date_s"] if sig == "entry" else "",
                           "entry_exec_date": "", "entry_price": "",
                           "exit_signal_date": r["date_s"] if sig == "exit" else "",
                           "exit_exec_date": "", "exit_price": "",
                           "shares": "", "pnl": "", "ret_pct": "",
                           "status": "unfilled"})
            continue
        nxt = df.iloc[i + 1]
        px = float(nxt["open"])
        if sig == "entry":
            if holding:
                stats["skip_dup_entry"] += 1
                continue
            holding = True
            buy_px = px * (1 + slip)
            entry_fees = cash * comm
            shares = (cash - entry_fees) / buy_px
            cash = 0.0
            entry_sig_date, entry_exec_date, entry_price = r["date_s"], nxt["date_s"], buy_px
        else:  # exit
            if not holding:
                stats["skip_exit_flat"] += 1
                continue
            holding = False
            sell_px = px * (1 - slip)
            proceeds = shares * sell_px
            exit_fees = proceeds * (comm + tax)
            stats["fees_paid"] += entry_fees + exit_fees
            cost = entry_price * shares
            pnl = (proceeds - exit_fees) - (cost + entry_fees)
            row = {"entry_signal_date": entry_sig_date,
                   "entry_exec_date": entry_exec_date, "entry_price": round(entry_price, 4),
                   "exit_signal_date": r["date_s"],
                   "exit_exec_date": nxt["date_s"], "exit_price": round(sell_px, 4),
                   "shares": round(shares, 6), "pnl": round(pnl, 2),
                   "ret_pct": round(pnl / (cost + entry_fees) * 100, 3) if cost else "",
                   "status": "completed"}
            if include_fees:
                row["fees"] = round(entry_fees + exit_fees, 2)
            trades.append(row)
            stats["completed"] += 1
            cash, shares = proceeds - exit_fees, 0.0
    if holding:  # 기말 미청산: 평가만 표시, 자동 청산 없음
        last_close = float(df.iloc[-1]["close"])
        cost = entry_price * shares
        upnl = shares * last_close - cost
        trades.append({"entry_signal_date": entry_sig_date,
                       "entry_exec_date": entry_exec_date, "entry_price": round(entry_price, 4),
                       "exit_signal_date": "", "exit_exec_date": "", "exit_price": "",
                       "shares": round(shares, 6), "pnl": round(upnl, 2),
                       "ret_pct": round(upnl / cost * 100, 3), "status": "open"})
        stats["open"] += 1
    return trades, stats


def build_sized(df: pd.DataFrame, sig_col: str, atr_col: str = "atr14",
                commission_bps: float = 0.0, sell_tax_bps: float = 0.0,
                slippage_bps: float = 0.0, include_fees: bool = False,
                risk: float = 0.01, k: float = 2.0
                ) -> tuple[list[dict], dict, list[float], list[int]]:
    """변동성 사이징: 진입=F신호 동일, 수량=자본*risk/(k*ATR), 청산=신호 또는
    트레일스탑(진입후 최고종가-k*진입시ATR) 하회 시 t+1 시가. 비용 규약은 build와 동일."""
    comm = commission_bps / 10_000.0
    tax = sell_tax_bps / 10_000.0
    slip = slippage_bps / 10_000.0
    cash, shares, holding = INITIAL_CAPITAL, 0.0, False
    entry_sig_date, entry_exec_date, entry_price = "", "", 0.0
    entry_fees, atr_entry, peak = 0.0, 0.0, 0.0
    trades: list[dict] = []
    stats = {"completed": 0, "open": 0, "unfilled": 0,
             "skip_dup_entry": 0, "skip_exit_flat": 0, "fees_paid": 0.0,
             "stop_exit": 0}
    eq, held = [], []
    n = len(df)
    for i, r in df.iterrows():
        close = float(r["close"])
        if holding:
            peak = max(peak, close)
            eq.append(cash + shares * close)
        else:
            eq.append(cash)
        held.append(1 if holding else 0)
        sig = r[sig_col]
        stop_hit = holding and close < peak - k * atr_entry
        if sig not in ("entry", "exit") and not stop_hit:
            continue
        if i + 1 >= n:
            stats["unfilled"] += 1
            trades.append({"entry_signal_date": entry_sig_date if holding else "",
                           "entry_exec_date": entry_exec_date if holding else "",
                           "entry_price": round(entry_price, 4) if holding else "",
                           "exit_signal_date": r["date_s"] if sig == "exit" else "",
                           "exit_exec_date": "", "exit_price": "",
                           "shares": "", "pnl": "", "ret_pct": "",
                           "status": "unfilled"})
            continue
        nxt = df.iloc[i + 1]
        px = float(nxt["open"])
        if sig == "entry" and not holding:
            dist = k * float(r[atr_col])
            if dist <= 0:
                continue
            equity = cash + shares * close
            buy_px = px * (1 + slip)
            shares = equity * risk / dist
            entry_fees = shares * buy_px * comm
            cash -= shares * buy_px + entry_fees
            holding = True
            atr_entry, peak = float(r[atr_col]), close
            entry_sig_date, entry_exec_date, entry_price = r["date_s"], nxt["date_s"], buy_px
        elif holding and (sig == "exit" or stop_hit):
            if stop_hit and sig != "exit":
                stats["stop_exit"] += 1
            holding = False
            sell_px = px * (1 - slip)
            proceeds = shares * sell_px
            exit_fees = proceeds * (comm + tax)
            stats["fees_paid"] += entry_fees + exit_fees
            cost = entry_price * shares
            pnl = (proceeds - exit_fees) - (cost + entry_fees)
            row = {"entry_signal_date": entry_sig_date,
                   "entry_exec_date": entry_exec_date, "entry_price": round(entry_price, 4),
                   "exit_signal_date": r["date_s"],
                   "exit_exec_date": nxt["date_s"], "exit_price": round(sell_px, 4),
                   "shares": round(shares, 6), "pnl": round(pnl, 2),
                   "ret_pct": round(pnl / (cost + entry_fees) * 100, 3) if cost else "",
                   "status": "completed",
                   "exit_reason": "stop" if stop_hit and sig != "exit" else "signal"}
            if include_fees:
                row["fees"] = round(entry_fees + exit_fees, 2)
            trades.append(row)
            stats["completed"] += 1
            cash, shares = cash + proceeds - exit_fees, 0.0
        elif sig == "entry":
            stats["skip_dup_entry"] += 1
        elif sig == "exit":
            stats["skip_exit_flat"] += 1
    if holding:
        last_close = float(df.iloc[-1]["close"])
        cost = entry_price * shares
        upnl = shares * last_close - cost
        trades.append({"entry_signal_date": entry_sig_date,
                       "entry_exec_date": entry_exec_date, "entry_price": round(entry_price, 4),
                       "exit_signal_date": "", "exit_exec_date": "", "exit_price": "",
                       "shares": round(shares, 6), "pnl": round(upnl, 2),
                       "ret_pct": round(upnl / cost * 100, 3), "status": "open"})
        stats["open"] += 1
        eq[-1] = cash + shares * last_close
    return trades, stats, eq, held


def main() -> None:
    snap = pd.read_csv(ROOT / "data" / "snapshots" / "exp002" / "ohlcv.csv", parse_dates=["date"])
    ind = pd.read_csv(RES / "indicators_satl.csv", parse_dates=["date"])
    satl = snap[snap["symbol"] == "SATL"].sort_values("date").reset_index(drop=True)
    satl["date_s"] = satl["date"].dt.date.astype(str)
    ind["date_s"] = ind["date"].dt.date.astype(str)
    df = ind[ind["in_eval"]].merge(satl[["date_s", "open"]],
                                   on="date_s", how="left").reset_index(drop=True)
    assert int(df[["open", "close"]].isna().sum().sum()) == 0, "평가구간 시세 결합 결측"

    lines = ["# P3 거래 요약 (exp002, 평가구간, t+1 시가·전액/전량·비용 0)", "",
             f"- 초기자본 {INITIAL_CAPITAL:,.0f} USD, 소수점 주식 허용(연구용), 분할·배당 조정가격 기준.", ""]
    for strat, col in STRATS.items():
        trades, st = build(df, col)
        pd.DataFrame(trades).to_csv(RES / f"trades_{strat}.csv", index=False)
        lines += [f"## 전략 {strat}",
                  f"- 완료 {st['completed']}건, 미청산(평가) {st['open']}건, 미체결(마지막봉) {st['unfilled']}건",
                  f"- 무시: 중복매수 {st['skip_dup_entry']}건, 미보유청산 {st['skip_exit_flat']}건", ""]
        print(strat, st, f"rows={len(trades)}")
    (RES / "trades_summary.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
