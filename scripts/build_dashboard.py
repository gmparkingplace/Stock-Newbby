"""대시보드 데이터 export: exp006 유니버스 단일 통합 -> results/dashboard/data.js.

실행: .venv/bin/python scripts/build_dashboard.py
입력: exp006 스냅샷·지표·거래·성과 (과거 실험은 파일로만 보존, UI에서 제외)
출력: results/dashboard/data.js
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from serve_dashboard import frame, to_weekly  # noqa: E402 (지표·주봉 재계산 공유)
OUT = ROOT / "results" / "dashboard" / "data.js"  # file:// 직접 열기 대응 (fetch CORS 회피)
NAMES = {"005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "069500.KS": "KODEX 200",
         "091160.KS": "KODEX 반도체", "^KS11": "KOSPI", "^KQ11": "KOSDAQ",
         "QQQ": "나스닥100", "SPY": "S&P500",
         "XLK": "미국 기술섹터", "IWM": "러셀2000", "ITA": "미국 방산", "AAPL": "애플",
         "NVDA": "엔비디아", "SATL": "새틀러직"}
EXPS = {
    "exp002": {"targets": {"SATL": "indicators_satl.csv"}, "snap": "data/snapshots/exp002/ohlcv.csv",
               "res": "results/exp002", "tr": "trades_{}.csv", "ledger": "ledger.jsonl",
               "muse": "commentaries_muse.jsonl", "perf": "performance_p4.md", "label": "미국 SATL (비용 0)"},
    "exp004": {"targets": {"005930.KS": "005930KS", "000660.KS": "000660KS"},
               "snap": "data/snapshots/exp004/ohlcv.csv", "res": "results/exp004",
               "tr": "trades_{}_{}.csv", "ledger": "ledger_{}.jsonl",
               "muse": None, "perf": "performance.md", "label": "한국 2종목 실비용"},
    "exp005": {"targets": {"005930.KS": "005930KS", "000660.KS": "000660KS"},
               "snap": "data/snapshots/exp005/ohlcv.csv", "res": "results/exp005",
               "tr": "trades_{}_{}.csv", "ledger": "ledger_{}.jsonl",
               "muse": "commentaries_muse_{}.jsonl", "perf": "performance.md",
               "label": "한국 2종목 F게이트"},
    "exp006": {"targets": {"005930.KS": "005930KS", "000660.KS": "000660KS",
                           "AAPL": "AAPL", "NVDA": "NVDA", "SATL": "SATL"},
               "watch": ["^KS11", "QQQ", "SPY", "069500.KS", "091160.KS", "XLK", "IWM", "ITA"],
               "snap": "data/snapshots/exp006/ohlcv.csv", "res": "results/exp006",
               "tr": "trades_{}_{}.csv", "ledger": "ledger_{}.jsonl",
               "muse": None, "perf": "performance.md",
               "label": "한미 대표 유니버스 F게이트"},
    "exp008": {"targets": {"005930.KS": "005930KS", "000660.KS": "000660KS",
                           "AAPL": "AAPL", "NVDA": "NVDA", "SATL": "SATL",
                           "^KS11": "KS11", "^KQ11": "KQ11", "QQQ": "QQQ", "SPY": "SPY",
                           "069500.KS": "069500KS", "091160.KS": "091160KS",
                           "XLK": "XLK", "IWM": "IWM", "ITA": "ITA"},
               "snap": "data/snapshots/exp008/ohlcv.csv", "res": "results/exp008",
               "tr": "trades_{}_{}.csv", "ledger": "ledger_{}.jsonl",
               "muse": "commentaries_{}.jsonl", "perf": "performance.md",
               "label": "지속가능형 F게이트 1%리스크+2ATR (14종목)"},
}


def sym_data(exp: str, cfg: dict, sym: str, stem: str, with_signals: bool = True) -> dict:
    snap = pd.read_csv(ROOT / cfg["snap"], parse_dates=["date"])
    d = snap[snap["symbol"] == sym].sort_values("date").reset_index(drop=True)
    d["t"] = d["date"].dt.date.astype(str)
    ind_name = {"exp002": "indicators_satl.csv"}.get(exp, f"indicators_{stem}.csv")
    ind = pd.read_csv(ROOT / cfg["res"] / ind_name, parse_dates=["date"])
    ind["t"] = ind["date"].dt.date.astype(str)
    m = d.merge(ind, on="t", how="left", suffixes=(" snap", "_ind"))
    candles = [{"time": r["t"], "open": round(float(r["open"]), 4),
                "high": round(float(r["high"]), 4), "low": round(float(r["low"]), 4),
                "close": round(float(r["close snap"]), 4),
                "volume": int(r["volume"])} for _, r in m.iterrows()]
    sigs = sorted({c[3:] for c in ind.columns if c.startswith("sig")})
    lines, marks = {}, {}
    info = {}
    for lname in [f"ledger_{stem}.jsonl", "ledger.jsonl"]:
        lp = ROOT / cfg["res"] / lname
        if lp.exists():
            for ln in lp.read_text().splitlines():
                if ln.strip():
                    e = json.loads(ln)
                    if e["symbol"] == sym:
                        info[(e["signal_bar_close"][:10], e["strategy"], e["side"])] = \
                            f"{e['reason_desc']} · 참고가 {e['signal_price']}"
            break
    for col in ("sma20", "sma60"):
        if col in ind.columns:
            lines[col] = [{"time": t, "value": round(float(v), 4)}
                          for t, v in zip(ind["t"], ind[col]) if v == v]
    for s in sigs:
        marks[s] = [{"time": r["t"], "side": r[f"sig{s}"],
                     "info": info.get((r["t"], s, r[f"sig{s}"]), "")}
                    for _, r in ind[ind[f"sig{s}"].isin(["entry", "exit"])].iterrows()]
    if "{}" in cfg["tr"] and cfg["tr"].count("{}") == 2:
        tname = lambda s: cfg["tr"].format(s, stem)  # noqa: E731
    else:
        tname = lambda s: cfg["tr"].format(s)  # noqa: E731
    trades = {}
    for s in sigs:
        p = ROOT / cfg["res"] / tname(s)
        trades[s] = pd.read_csv(p, dtype=str).fillna("").to_dict(orient="records") if p.exists() else []
    last = candles[-120:]
    hi, lo = max(c["high"] for c in last), min(c["low"] for c in last)
    rng = hi - lo or 1.0
    fib = {"from": last[0]["time"], "to": last[-1]["time"], "high": hi, "low": lo,
           "levels": {str(r): round(lo + rng * r, 4)
                      for r in (0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.618)}}
    state = []
    for _, r in m.iterrows():
        st = {}
        for k in ("rsi14", "atr14", "vol_ratio"):
            v = r.get(k)
            st[k] = None if v is None or v != v else round(float(v), 3)
        for k, col in (("don_hi", "don_hi20"), ("don_lo", "don_lo10")):
            v = r.get(col)
            st[k] = None if v is None or v != v else round(float(v), 2)
        for s in sigs:
            v = r.get(f"sig{s}")
            st[f"sig{s}"] = v if v in ("entry", "exit") else "none"
        state.append(st)
    lr = m.iloc[-1]
    def num(x):
        return None if x is None or x != x else round(float(x), 4)
    levels = {"close": round(float(lr["close snap"]), 4),
              "sma20": num(lr.get("sma20")), "sma60": num(lr.get("sma60")),
              "don_hi": num(lr.get("don_hi20")), "don_lo": num(lr.get("don_lo10")),
              "atr14": num(lr.get("atr14")), "rsi14": num(lr.get("rsi14")),
              "vol_ratio": num(lr.get("vol_ratio"))}
    w = to_weekly(d.rename(columns={"close snap": "close"})[["t", "open", "high", "low", "close", "volume"]]
                  .assign(open=lambda x: x["open"].astype(float),
                          high=lambda x: x["high"].astype(float),
                          low=lambda x: x["low"].astype(float),
                          close=lambda x: x["close"].astype(float),
                          volume=lambda x: x["volume"].astype(float)))
    return {"symbol": sym, "name": NAMES.get(sym, sym), "candles": candles,
            "lines": lines, "marks": marks, "trades": trades,
            "strats": sigs, "fib": fib, "state": state,
            "levels": levels, "weekly": frame(w, False)}


def candles_only(exp: str, cfg: dict, sym: str) -> dict:
    snap = pd.read_csv(ROOT / cfg["snap"], parse_dates=["date"])
    d = snap[snap["symbol"] == sym].sort_values("date").reset_index(drop=True)
    d["t"] = d["date"].dt.date.astype(str)
    for c in ("open", "high", "low", "close", "volume"):
        d[c] = d[c].astype(float)
    out = frame(d[["t", "open", "high", "low", "close", "volume"]], False)
    out.update({"symbol": sym, "name": NAMES.get(sym, sym), "watch": True,
                "strats": ["A", "B", "C", "F"], "trades": {},
                "weekly": frame(to_weekly(d), False)})
    return out


def main() -> None:
    data = {"exps": []}
    for exp, cfg in EXPS.items():
        if exp != "exp008":
            continue  # UI는 현행 유니버스로 통합, 과거 실험은 파일 보존
        symbols = {sym: sym_data(exp, cfg, sym, stem) for sym, stem in cfg["targets"].items()}
        for w in cfg.get("watch", []):
            symbols[w] = candles_only(exp, cfg, w)
        perf = (ROOT / cfg["res"] / cfg["perf"]).read_text() if (ROOT / cfg["res"] / cfg["perf"]).exists() else ""
        muse = {}
        for sym, stem in cfg["targets"].items():
            mf = cfg["muse"].format(stem) if cfg["muse"] and "{}" in cfg["muse"] else cfg["muse"]
            p = ROOT / cfg["res"] / mf if mf else None
            if p and p.exists():
                muse[sym] = [json.loads(l) for l in p.read_text().splitlines()][-5:]
        data["exps"].append({"id": exp, "label": cfg["label"], "symbols": symbols,
                             "performance_md": perf, "muse_recent": muse})
    OUT.write_text("const DASHBOARD_DATA = " + json.dumps(data, ensure_ascii=False) + ";")
    print(f"{OUT.name}: {OUT.stat().st_size // 1024}KB, exps={len(data['exps'])}")


if __name__ == "__main__":
    main()
