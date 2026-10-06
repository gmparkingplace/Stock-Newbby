"""exp004 검증: 2종목·실비용 전 단계 + 이전 실험 불변 확인.

실행: .venv/bin/python scripts/verify_exp004.py  (종료코드 0 = 통과)
출력: results/exp004/verify_exp004.md
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from verify_p2 import plain_rsi, plain_sma  # noqa: E402
from verify_p2b import plain_beta  # noqa: E402
from verify_p3 import replay  # noqa: E402

EXP = "exp004"
TARGETS = {"005930.KS": "005930KS", "000660.KS": "000660KS"}
EVAL_START = "2022-09-01"
TOL = 0.05
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)


def main() -> None:
    snap_path = ROOT / "data" / "snapshots" / EXP / "ohlcv.csv"
    manifest = json.loads((snap_path.parent / "manifest.json").read_text())
    check("비용 프로필", manifest["costs_bps"] == {"commission": 1.5, "sell_tax": 30.0,
                                                   "slippage": 0.0},
          str(manifest["costs_bps"]))
    check("스냅샷 sha 일치",
          hashlib.sha256(snap_path.read_bytes()).hexdigest() == manifest["sha256_ohlcv_csv"])
    snap = pd.read_csv(snap_path, parse_dates=["date"])
    run_ids = set()
    for target, stem in TARGETS.items():
        RES = ROOT / "results" / EXP
        kr = snap[snap["symbol"] == target].sort_values("date").reset_index(drop=True)
        check(f"{target} 품질",
              kr["date"].is_monotonic_increasing and not kr["date"].duplicated().any()
              and int(kr[["open", "high", "low", "close"]].isna().sum().sum()) == 0
              and int((kr["high"] < kr["low"]).sum()) == 0, f"rows={len(kr)}")
        closes, highs, lows = kr["close"].tolist(), kr["high"].tolist(), kr["low"].tolist()
        dates = kr["date"].dt.date.astype(str).tolist()
        ind = pd.read_csv(RES / f"indicators_{stem}.csv", parse_dates=["date"])
        ok_all = True
        for sd in ["2022-09-01", "2023-06-01", "2024-06-03"]:
            d0 = max(d for d in dates if d <= sd)
            i, r = dates.index(d0), ind.iloc[dates.index(d0)]
            ok = all(abs((a or 0) - (b or 0)) < TOL for a, b in
                     [(plain_sma(closes, i, 20), r["sma20"]),
                      (plain_sma(closes, i, 60), r["sma60"]),
                      (plain_rsi(closes, i), r["rsi14"]),
                      (max(highs[i - 20:i]) if i >= 20 else None, r["don_hi20"]),
                      (min(lows[i - 10:i]) if i >= 10 else None, r["don_lo10"])])
            ok_all &= ok
        check(f"{target} 지표 독립 재계산", ok_all)

        ctx = pd.read_csv(RES / f"context_{stem}.csv")
        first = ctx[ctx["date"] >= EVAL_START].iloc[0]
        check(f"{target} 첫 봉 추정창 ok",
              first["na_mkt_60"] == "ok" and first["na_sec_120"] == "ok", first["date"])

        lines = [ln for ln in (RES / f"ledger_{stem}.jsonl").read_text().splitlines() if ln.strip()]
        events = [json.loads(ln) for ln in lines]
        ids = [e["event_id"] for e in events]
        check(f"{target} 원장 무결성",
              len(ids) == len(set(ids)) and len({e["run_id"] for e in events}) == 1,
              f"{len(events)}건 {events[0]['run_id'] if events else ''}")
        run_ids.update(e["run_id"] for e in events)
        ind["date_s"] = ind["date"].dt.date.astype(str)
        expected = {(r["date_s"], s, r[c]) for _, r in ind[ind["date_s"] >= EVAL_START].iterrows()
                    for s, c in (("A", "sigA"), ("B", "sigB"), ("C", "sigC"))
                    if r[c] in ("entry", "exit")}
        got = {(e["signal_bar_close"][:10], e["strategy"], e["side"]) for e in events}
        check(f"{target} 원장==신호", expected == got, f"{len(expected)} vs {len(got)}")

        kr["date_s"] = kr["date"].dt.date.astype(str)
        ev = ind[ind["in_eval"]].merge(kr[["date_s", "open"]], on="date_s").reset_index(drop=True)
        for s, col in (("A", "sigA"), ("B", "sigB"), ("C", "sigC")):
            seq = [(d, x, xd) for d, x, xd, _ in replay(ev, col) if xd]
            t = pd.read_csv(RES / f"trades_{s}_{stem}.csv", dtype=str).fillna("")
            csv_exec = []
            for _, r in t.iterrows():
                if r["entry_exec_date"]:
                    csv_exec.append((r["entry_signal_date"], "entry", r["entry_exec_date"]))
                if r["exit_exec_date"]:
                    csv_exec.append((r["exit_signal_date"], "exit", r["exit_exec_date"]))
            check(f"{target}/{s} 순차==전체", seq == csv_exec, f"{len(csv_exec)}건")
        # 비용 검산: 첫 완료 거래의 수수료·세금·손익 재계산
        t = pd.read_csv(RES / f"trades_A_{stem}.csv", dtype=str).fillna("")
        done = t[t["status"] == "completed"]
        if len(done):
            r = done.iloc[0]
            sh = 10_000_000.0 * (1 - 0.00015) / float(r["entry_price"])
            gross = sh * float(r["exit_price"])
            fee = 10_000_000.0 * 0.00015 + gross * (0.00015 + 0.003)
            pnl = (gross - gross * (0.00015 + 0.003)) - 10_000_000.0
            check(f"{target}/A 비용 손익 일치",
                  abs(float(r["pnl"]) - pnl) < 1.0 and abs(float(r["fees"]) - fee) < 1.0,
                  f"pnl={r['pnl']} fees={r['fees']}")
        for s in ("A", "B", "C", "BH"):
            e = pd.read_csv(RES / f"equity_{s}_{stem}.csv", dtype={"date": str})
            check(f"{target}/{s} 지분 봉수", len(e) == len(ev), f"rows={len(e)}")
    check("단일 run_id (실험 전체)", len(run_ids) == 1, str(run_ids))

    pins = manifest["pinned_prev_sha256"]
    stale = [k for k, h in pins.items()
             if hashlib.sha256((ROOT / k).read_bytes()).hexdigest() != h]
    check("이전 실험 불변 (핀sha)", not stale, str(stale))
    git = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain",
                          "--", "results/exp002", "results/exp003",
                          "data/snapshots/exp002", "data/snapshots/exp003"],
                         capture_output=True, text=True)
    check("이전 실험 불변 (git)", git.stdout.strip() == "", git.stdout.strip()[:200])

    (ROOT / "results" / EXP / "verify_exp004.md").write_text(
        "# exp004 검증\n\n- 2종목·실비용 전 단계 통과, run_id " +
        (next(iter(run_ids)) if run_ids else "없음") + ", 이전 실험 불변.\n")
    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
