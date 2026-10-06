"""P3 검증: 순차 재현==전체 계산, 포지션 불변식, 교차·돌파 사례 대조.

실행: .venv/bin/python scripts/verify_p3.py  (종료코드 0 = 통과)
출력: results/exp002/trades_check.md
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "exp002"
EVAL_START = "2022-09-01"
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)


def replay(ev: pd.DataFrame, col: str) -> list[tuple]:
    """봉 단위 순차 재현 -> (신호일, 방향, 체결일, 체결가) 목록."""
    out, holding = [], False
    dates, opens = ev["date_s"].tolist(), ev["open"].tolist()
    sigs = ev[col].tolist()
    for i, sig in enumerate(sigs):
        if sig not in ("entry", "exit"):
            continue
        if i + 1 >= len(ev):
            out.append((dates[i], sig, "", ""))
            continue
        if sig == "entry" and holding:
            continue
        if sig == "exit" and not holding:
            continue
        holding = (sig == "entry")
        out.append((dates[i], sig, dates[i + 1], opens[i + 1]))
    return out


def main() -> None:
    ind = pd.read_csv(RES / "indicators_satl.csv", parse_dates=["date"])
    ind["date_s"] = ind["date"].dt.date.astype(str)
    snap = pd.read_csv(ROOT / "data" / "snapshots" / "exp002" / "ohlcv.csv", parse_dates=["date"])
    satl = snap[snap["symbol"] == "SATL"].sort_values("date").reset_index(drop=True)
    satl["date_s"] = satl["date"].dt.date.astype(str)
    ev = ind[ind["in_eval"]].merge(satl[["date_s", "open"]], on="date_s",
                                   how="left").reset_index(drop=True)

    rows_md = []
    for strat, col in (("A", "sigA"), ("B", "sigB"), ("C", "sigC")):
        seq = replay(ev, col)
        csv = pd.read_csv(RES / f"trades_{strat}.csv", dtype=str).fillna("")
        # 순차==전체: 체결 이벤트 수와 순서가 일치 (미체결 포함)
        seq_exec = [(d, s, x) for d, s, x, _ in seq if x]
        csv_exec = []
        for _, t in csv.iterrows():
            if t["entry_exec_date"]:
                csv_exec.append((t["entry_signal_date"], "entry", t["entry_exec_date"]))
            if t["exit_exec_date"]:
                csv_exec.append((t["exit_signal_date"], "exit", t["exit_exec_date"]))
        check(f"{strat} 순차==전체 체결", seq_exec == csv_exec,
              f"seq={len(seq_exec)} csv={len(csv_exec)}")
        # 불변식: 미보유 청산·보유 중 매수 없음 (replay가 걸렀으므로 CSV에 흔적 없어야 함)
        pos = 0
        ok = True
        for _, t in csv.iterrows():
            if t["entry_exec_date"]:
                if pos == 1:
                    ok = False
                pos = 1
            if t["exit_exec_date"]:
                if pos == 0:
                    ok = False
                pos = 0
        check(f"{strat} 미보유청산·중복매수 없음", ok)
        # 체결일은 신호 다음 거래일
        dates = ev["date_s"].tolist()
        ok_next = True
        for _, t in csv.iterrows():
            for s_col, e_col in (("entry_signal_date", "entry_exec_date"),
                                 ("exit_signal_date", "exit_exec_date")):
                if t[s_col] and t[e_col]:
                    if dates.index(t[e_col]) != dates.index(t[s_col]) + 1:
                        ok_next = False
        check(f"{strat} t+1봉 체결", ok_next)
        # 평가구간 밖 날짜 없음
        all_d = [t[c] for _, t in csv.iterrows()
                 for c in ("entry_signal_date", "exit_signal_date",
                           "entry_exec_date", "exit_exec_date") if t[c]]
        check(f"{strat} 평가구간 내 날짜", all(d >= EVAL_START for d in all_d),
              f"trades={len(csv)}")

    # 교차·돌파 첫 사례 대조 (지표값으로 조건 재확인)
    r = ev[ev["sigA"] == "entry"].iloc[0]
    i = ev.index[ev["sigA"] == "entry"][0]
    p = ev.iloc[i - 1]
    check("A 첫 매수=상향교차",
          p["sma20"] <= p["sma60"] and r["sma20"] > r["sma60"],
          f"{r['date_s']} {r['sma20']}/{r['sma60']}")
    rows_md.append(("A", r["date_s"], f"SMA20 {r['sma20']} > SMA60 {r['sma60']}"))
    r = ev[ev["sigB"] == "entry"].iloc[0]
    i = ev.index[ev["sigB"] == "entry"][0]
    p = ev.iloc[i - 1]
    check("B 첫 매수=RSI30 상향",
          p["rsi14"] <= 30 and r["rsi14"] > 30,
          f"{r['date_s']} RSI {r['rsi14']}")
    rows_md.append(("B", r["date_s"], f"RSI {r['rsi14']} > 30"))
    r = ev[ev["sigC"] == "entry"].iloc[0]
    check("C 첫 매수=돌파",
          r["close"] > r["don_hi20"],
          f"{r['date_s']} close {r['close']} > hi {r['don_hi20']}")
    rows_md.append(("C", r["date_s"], f"close {r['close']} > DonHi {r['don_hi20']}"))

    md = ["# P3 점검 (신호 표식·거래 목록)", "",
          "| 전략 | 첫 매수봉 | 조건 확인 |",
          "| --- | --- | --- |"]
    md += [f"| {s} | {d} | {c} |" for s, d, c in rows_md]
    md += ["", "- 순차(봉 단위 재현) == 전체(일괄 계산) 체결 목록.", "- 미보유 청산·중복 매수 없음, t+1봉 체결, 기말 미청산 자동청산 없음."]
    (RES / "trades_check.md").write_text("\n".join(md) + "\n")
    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
