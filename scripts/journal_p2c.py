"""P2c 신호 근거 원장: 신호 당시 조건·시장/섹터 상태를 JSONL 이벤트로 보관.

계약 출처: Context-and-Journal.md §1 (저장 항목표).
실행: .venv/bin/python scripts/journal_p2c.py  (재실행해도 중복 기록 없음)
입력: results/exp002/indicators_satl.csv + context_satl.csv + manifest.json
출력: results/exp002/ledger.jsonl + ledger_table.md (사람용 열람표)
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "exp002"
TARGET = "SATL"
EVAL_START = "2022-09-01"
CODE_FILES = ["indicators.py", "context_p2b.py", "journal_p2c.py"]

REASONS = {
    ("A", "entry"): ("A_ENTRY_SMA_CROSS_UP", "SMA20이 SMA60을 상향 교차"),
    ("A", "exit"): ("A_EXIT_SMA_CROSS_DOWN", "SMA20이 SMA60을 하향 교차"),
    ("B", "entry"): ("B_ENTRY_RSI_UP_30", "RSI14가 30을 상향 교차"),
    ("B", "exit"): ("B_EXIT_RSI_DOWN_70", "RSI14가 70을 하향 교차"),
    ("C", "entry"): ("C_ENTRY_DONCHIAN_BREAK", "종가가 직전 20봉 최고가 초과"),
    ("C", "exit"): ("C_EXIT_DONCHIAN_BREAK", "종가가 직전 10봉 최저가 하회"),
}
IND_COLS = {"A": ("sma20", "sma60"), "B": ("rsi14", None), "C": ("don_hi20", "don_lo10")}


def clean(v):
    """numpy 타입->표준 타입, NaN->None (JSONL 유효성 보장)."""
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return v


def code_hash() -> str:
    h = hashlib.sha256()
    for f in CODE_FILES:
        h.update((ROOT / "scripts" / f).read_bytes())
    return h.hexdigest()[:12]


def main() -> None:
    manifest = json.loads((RES.parent.parent / "data" / "snapshots" / "exp002" / "manifest.json").read_text())
    ind = pd.read_csv(RES / "indicators_satl.csv", parse_dates=["date"])
    ctx = pd.read_csv(RES / "context_satl.csv", parse_dates=["date"])
    run_id = f"exp002-{manifest['sha256_ohlcv_csv'][:8]}-{code_hash()}"
    data_ver = manifest["sha256_ohlcv_csv"][:12]

    merged = ind.merge(ctx, on="date", how="left", suffixes=("", "_ctx"))
    merged["date_s"] = merged["date"].dt.date.astype(str)
    events: list[dict] = []
    position = {"A": 0, "B": 0, "C": 0}  # 전략별 독립 보유 상태 (P3 자본 시뮬레이션과 별개)
    for _, r in merged[merged["date_s"] >= EVAL_START].iterrows():
        for strat, col in (("A", "sigA"), ("B", "sigB"), ("C", "sigC")):
            side = r[col]
            if side not in ("entry", "exit"):
                continue
            code, desc = REASONS[(strat, side)]
            c1, c2 = IND_COLS[strat]
            before = position[strat]
            repeated = (side == "entry" and before == 1) or (side == "exit" and before == 0)
            position[strat] = 1 if side == "entry" else 0
            events.append(clean({
                "event_id": f"{run_id}|{strat}|{TARGET}|{r['date_s']}|{side}",
                "run_id": run_id, "strategy": strat, "rule_version": "research-2026-09-03",
                "symbol": TARGET, "market": "USA", "timeframe": "1D",
                "signal_bar_close": r["date_s"] + "T16:00:00-04:00",
                "record_type": "historical_reconstruction",
                "side": side, "reason_code": code, "reason_desc": desc,
                "indicator_now": {c: r[c] for c in (c1, c2) if c},
                "signal_price": round(float(r["close"]), 4),
                "position_before": before, "repeated_signal": bool(repeated),
                "filter": None, "filter_decision": "allowed",
                "execution": None,  # P3에서 t+1봉 시가 모의 체결로 기입
                "market_ref": {"id": "IWM", "type": "ETF",
                               "trend": r["trend_mkt"], "beta_60": r["beta_mkt_60"],
                               "corr_60": r["corr_mkt_60"], "r2_60": r["r2_mkt_60"]},
                "sector_ref": {"id": "ITA", "type": "ETF",
                               "trend": r["trend_sec"], "beta_60": r["beta_sec_60"],
                               "corr_60": r["corr_sec_60"], "r2_60": r["r2_sec_60"]},
                "rel_pp": {"stock_mkt": r["rel_stock_mkt_pp"], "stock_sec": r["rel_stock_sec_pp"]},
                "estimation": {"window": 60, "na_reason_mkt": r["na_mkt_60"],
                               "na_reason_sec": r["na_sec_60"]},
                "data_version": data_ver, "code_hash": code_hash(),
                "source": "yfinance",
            }))

    ledger = RES / "ledger.jsonl"
    seen = set()
    if ledger.exists():
        seen = {json.loads(line)["event_id"] for line in ledger.read_text().splitlines() if line.strip()}
    new = [e for e in events if e["event_id"] not in seen]
    with ledger.open("a") as f:
        for e in new:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    table = ["# P2c 근거 열람표 (저장값, 재계산값 아님)", "",
             "| 봉 | 전략 | 방향 | 근거 | 지표값 | 시장/섹터 추세 | 베타m60/s60 |",
             "| --- | --- | --- | --- | --- | --- | ---: |"]
    for e in events:
        m, s = e["market_ref"], e["sector_ref"]
        table.append(f"| {e['signal_bar_close'][:10]} | {e['strategy']} | "
                     f"{'매수' if e['side'] == 'entry' else '청산'} | {e['reason_desc']} | "
                     f"{e['indicator_now']} | {m['trend']}/{s['trend']} | {m['beta_60']}/{s['beta_60']} |")
    (RES / "ledger_table.md").write_text("\n".join(table) + "\n")
    print(f"run_id={run_id} events={len(events)} appended={len(new)} ledger_total={len(seen) + len(new)}")


if __name__ == "__main__":
    main()
