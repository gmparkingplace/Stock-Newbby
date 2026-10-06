"""P5 검증: 한국 파이프라인 전 단계 + 미국 결과 불변 확인.

실행: .venv/bin/python scripts/verify_p5kr.py  (종료코드 0 = 통과)
출력: results/exp003/verify_p5kr.md
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

RES = ROOT / "results" / "exp003"
SNAP = ROOT / "data" / "snapshots" / "exp003" / "ohlcv.csv"
EVAL_START = "2022-09-01"
TOL = 0.05  # KRW 2자리 반올림(≤0.005) + 여유
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)


def main() -> None:
    manifest = json.loads((SNAP.parent / "manifest.json").read_text())
    check("프로필 KR", manifest["exchange_timezone"] == "Asia/Seoul"
          and manifest["currency"] == "KRW"
          and manifest["symbols"] == ["005930.KS", "069500.KS", "091160.KS"],
          str(manifest["symbols"]))
    check("스냅샷 sha 일치",
          hashlib.sha256(SNAP.read_bytes()).hexdigest() == manifest["sha256_ohlcv_csv"])
    q = manifest["quality"]["005930.KS"]
    check("KR 품질", q["nan_ohlc"] == 0 and q["high_lt_low"] == 0
          and q["duplicates"] == 0 and q["time_monotonic"], str(q["rows"]))

    snap = pd.read_csv(SNAP, parse_dates=["date"])
    kr = snap[snap["symbol"] == "005930.KS"].sort_values("date").reset_index(drop=True)
    closes, highs, lows = kr["close"].tolist(), kr["high"].tolist(), kr["low"].tolist()
    dates = kr["date"].dt.date.astype(str).tolist()
    ind = pd.read_csv(RES / "indicators_kr.csv", parse_dates=["date"])
    check("평가구간 지표 결측 0",
          int(ind[ind["date"] >= EVAL_START][["sma20", "sma60", "rsi14", "don_hi20", "don_lo10"]]
              .isna().sum().sum()) == 0)
    for sd in ["2022-09-01", "2023-06-01", "2024-06-03"]:
        d0 = max(d for d in dates if d <= sd)
        i, r = dates.index(d0), ind.iloc[dates.index(d0)]
        ok = all(abs((a or 0) - (b or 0)) < TOL for a, b in
                 [(plain_sma(closes, i, 20), r["sma20"]), (plain_sma(closes, i, 60), r["sma60"]),
                  (plain_rsi(closes, i), r["rsi14"]),
                  (max(highs[i - 20:i]) if i >= 20 else None, r["don_hi20"]),
                  (min(lows[i - 10:i]) if i >= 10 else None, r["don_lo10"])])
        check(f"지표 독립 재계산 ({d0})", ok)

    ctx = pd.read_csv(RES / "context_kr.csv")
    px0 = snap.pivot(index="date", columns="symbol", values="close").sort_index()
    rm = (px0 / px0.shift(1) - 1)["069500.KS"].dropna().tolist()[100:220]
    b2 = plain_beta([2 * x for x in rm], rm)
    check("베타 함수 정상 (인공 2배=2)", b2 is not None and abs(b2 - 2.0) < 1e-9, str(b2))
    first = ctx[ctx["date"] >= EVAL_START].iloc[0]
    check("평가 첫 봉 60/120일창 ok",
          first["na_mkt_60"] == "ok" and first["na_sec_120"] == "ok", first["date"])

    lines = [ln for ln in (RES / "ledger.jsonl").read_text().splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    ids = [e["event_id"] for e in events]
    check("원장 JSON·무중복·단일 run_id",
          len(ids) == len(set(ids)) and len({e["run_id"] for e in events}) == 1,
          f"{len(events)}건")
    check("원장 KR 스키마", all(e["market"] == "KR" and e["currency"] == "KRW"
          and e["signal_bar_close"].endswith("T15:30:00+09:00") for e in events))
    ind["date_s"] = ind["date"].dt.date.astype(str)
    expected = {(r["date_s"], s, r[c]) for _, r in ind[ind["date_s"] >= EVAL_START].iterrows()
                for s, c in (("A", "sigA"), ("B", "sigB"), ("C", "sigC"))
                if r[c] in ("entry", "exit")}
    got = {(e["signal_bar_close"][:10], e["strategy"], e["side"]) for e in events}
    check("원장==지표 신호", expected == got, f"{len(expected)} vs {len(got)}")

    kr["date_s"] = kr["date"].dt.date.astype(str)
    ev = ind[ind["in_eval"]].merge(kr[["date_s", "open"]], on="date_s").reset_index(drop=True)
    for s, col in (("A", "sigA"), ("B", "sigB"), ("C", "sigC")):
        seq = [(d, x, xdate) for d, x, xdate, _ in replay(ev, col) if xdate]
        t = pd.read_csv(RES / f"trades_{s}.csv", dtype=str).fillna("")
        csv_exec = []
        for _, r in t.iterrows():
            if r["entry_exec_date"]:
                csv_exec.append((r["entry_signal_date"], "entry", r["entry_exec_date"]))
            if r["exit_exec_date"]:
                csv_exec.append((r["exit_signal_date"], "exit", r["exit_exec_date"]))
        check(f"{s} 순차==전체·t+1",
              [(d, x, xd) for d, x, xd in seq] == csv_exec, f"{len(csv_exec)}건")

    eqs = {s: pd.read_csv(RES / f"equity_{s}.csv", dtype={"date": str}) for s in ("A", "B", "C", "BH")}
    check("전 후보 지분곡선", all(len(e) == len(eqs["A"]) for e in eqs.values()))
    opens = dict(zip(kr["date_s"], kr["open"]))
    closes_d = dict(zip(kr["date_s"], kr["close"]))
    bh = eqs["BH"]["equity"].astype(float).tolist()
    check("B&H 회계", abs(bh[-1] - 10_000_000.0 / opens[ev['date_s'].iloc[1]] * closes_d[ev['date_s'].iloc[-1]]) < 1.0)

    pins = manifest["us_pinned_sha256"]
    stale = [name for name, h in pins.items()
             if hashlib.sha256((ROOT / ("data/snapshots/exp002" if name == "ohlcv.csv"
                                       else "results/exp002") / name).read_bytes()).hexdigest() != h]
    check("미국 결과 불변 (핀sha)", not stale, str(stale))
    git = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain",
                          "--", "results/exp002", "data/snapshots/exp002"],
                         capture_output=True, text=True)
    check("미국 결과 불변 (git)", git.stdout.strip() == "", git.stdout.strip()[:200])

    (RES / "verify_p5kr.md").write_text(
        "# P5 검증\n\n- 한국 전 단계(지표·맥락·원장·거래·성과) 통과, 미국 exp002 불변 확인.\n"
        f"- 원장 {len(events)}건, run_id {events[0]['run_id'] if events else '없음'}.\n")
    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
