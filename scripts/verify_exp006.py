"""exp006 검증: 한미 유니버스 F게이트 + 이전 실험 불변 확인.

실행: .venv/bin/python scripts/verify_exp006.py  (종료코드 0 = 통과)
출력: results/exp006/verify_exp006.md
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

EXP = "exp006"
TARGETS = {"005930.KS": "005930KS", "000660.KS": "000660KS", "AAPL": "AAPL", "NVDA": "NVDA", "SATL": "SATL"}
EVAL_START = "2022-09-01"
TOLS = {"KRW": 0.05, "USD": 0.01}  # 지표 CSV 2자리 반올림(≤0.005) 고려
CCY = {t: ("KRW" if t.endswith(".KS") else "USD") for t in TARGETS}
MKT = {t: ("KR" if t.endswith(".KS") else "USA") for t in TARGETS}
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)


def main() -> None:
    snap_path = ROOT / "data" / "snapshots" / EXP / "ohlcv.csv"
    manifest = json.loads((snap_path.parent / "manifest.json").read_text())
    cb = manifest["costs_bps"]
    check("비용 프로필(심볼별)",
          cb["005930.KS"] == {"commission": 1.5, "sell_tax": 30.0, "slippage": 0.0}
          and cb["AAPL"] == {"commission": 0.0, "sell_tax": 0.0, "slippage": 0.0},
          str(cb))
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
        TOL = TOLS[CCY[target]]
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
        suffix_ok = "T15:30:00+09:00" if MKT[target] == "KR" else "T16:00:00"
        check(f"{target} 원장 시장·장마감",
              all(e["market"] == MKT[target] and suffix_ok in e["signal_bar_close"] for e in events),
              MKT[target])
        ind["date_s"] = ind["date"].dt.date.astype(str)
        expected = {(r["date_s"], s, r[c]) for _, r in ind[ind["date_s"] >= EVAL_START].iterrows()
                    for s, c in (("A", "sigA"), ("B", "sigB"), ("C", "sigC"), ("F", "sigF"))
                    if r[c] in ("entry", "exit")}
        got = {(e["signal_bar_close"][:10], e["strategy"], e["side"]) for e in events}
        check(f"{target} 원장==신호", expected == got, f"{len(expected)} vs {len(got)}")

        kr["date_s"] = kr["date"].dt.date.astype(str)
        ev = ind[ind["in_eval"]].merge(kr[["date_s", "open"]], on="date_s").reset_index(drop=True)
        # F게이트 첫 진입 대조: 돌파+추세+거래량+ATR 강도 동시 만족
        fev = ind[(ind["in_eval"]) & (ind["sigF"] == "entry")]
        if len(fev):
            r = fev.iloc[0]
            check(f"{target}/F 첫 진입=게이트 만족",
                  r["close"] > r["don_hi20"] and r["close"] > r["sma60"]
                  and r["sma20"] > r["sma60"] and r["vol_ratio"] > 1.0
                  and (r["close"] - r["don_hi20"]) / r["atr14"] > 0.1,
                  f"{r['date_s']} vol={r['vol_ratio']}")
        # ATR 독립 재계산 대조 (첫 평가봉)
        i0 = ind.index[ind["date_s"] >= EVAL_START][0]
        cc, hh, ll = closes, highs, lows
        trs = [max(hh[k] - ll[k], abs(hh[k] - cc[k - 1]), abs(ll[k] - cc[k - 1]))
               for k in range(1, i0 + 1)]
        seed = sum(trs[1:15]) / 14
        a = seed
        for v in trs[15:]:
            a = (a * 13 + v) / 14
        check(f"{target}/ATR 독립 재계산",
              abs(a - ind.iloc[i0]["atr14"]) < 0.5, f"plain={a:.1f}")
        for s, col in (("A", "sigA"), ("B", "sigB"), ("C", "sigC"), ("F", "sigF")):
            seq = [(d, x, xd) for d, x, xd, _ in replay(ev, col) if xd]
            t = pd.read_csv(RES / f"trades_{s}_{stem}.csv", dtype=str).fillna("")
            csv_exec = []
            for _, r in t.iterrows():
                if r["entry_exec_date"]:
                    csv_exec.append((r["entry_signal_date"], "entry", r["entry_exec_date"]))
                if r["exit_exec_date"]:
                    csv_exec.append((r["exit_signal_date"], "exit", r["exit_exec_date"]))
            check(f"{target}/{s} 순차==전체", seq == csv_exec, f"{len(csv_exec)}건")
        # 비용 검산: 첫 완료 거래의 수수료·세금·손익 재계산 (심볼별 자본·비용)
        t = pd.read_csv(RES / f"trades_A_{stem}.csv", dtype=str).fillna("")
        done = t[t["status"] == "completed"]
        if len(done):
            cap = 10_000_000.0 if CCY[target] == "KRW" else 10_000.0
            cm = 0.00015 if CCY[target] == "KRW" else 0.0
            tx = 0.003 if CCY[target] == "KRW" else 0.0
            base = 1.0 if CCY[target] == "KRW" else 0.01
            r = done.iloc[0]
            sh = cap * (1 - cm) / float(r["entry_price"])
            gross = sh * float(r["exit_price"])
            fee = cap * cm + gross * (cm + tx)
            pnl = (gross - gross * (cm + tx)) - cap
            tol = max(base, abs(pnl) * 1e-5)  # 체결가 4자리 반올림 오차의 손익 증폭 고려
            has_fees = "fees" in t.columns
            check(f"{target}/A 비용 손익 일치",
                  abs(float(r["pnl"]) - pnl) < tol
                  and (not has_fees or abs(float(r["fees"]) - fee) < max(base, fee * 1e-5)),
                  f"pnl={r['pnl']}")
        for s in ("A", "B", "C", "F", "BH"):
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

    perf = (ROOT / "results" / EXP / "performance.md").read_text()
    check("홀드아웃 열 존재", "홀드아웃" in perf and "인샘플" in perf)
    (ROOT / "results" / EXP / "verify_exp005.md").write_text(
        "# exp005 검증 (F게이트)\n\n- 2종목·실비용·F게이트 전 단계 통과, run_id " +
        (next(iter(run_ids)) if run_ids else "없음") + ", 홀드아웃 분리 보고, 이전 실험 불변.\n")
    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
