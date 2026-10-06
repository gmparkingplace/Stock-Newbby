"""한국 파이프라인 (exp003·exp004): 수집→지표→맥락→원장→거래→성과.

공통 계산은 미국 스크립트의 순수 함수를 재사용한다 (Wilder RSI·교차·베타·원장 clean·거래·지분).
실행: .venv/bin/python scripts/kr_p5.py [exp003|exp004]  (기본 exp003, 재실행 시 스냅샷 갱신 주의)
차트: .venv/bin/python scripts/chart_p3.py <exp> indicators_<stem>.csv chart_<stem>.html <심볼>
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_snapshot import quality_checks, to_adjusted  # noqa: E402
from indicators import cross_down, cross_up, wilder_rsi  # noqa: E402
from context_p2b import beta_corr, cumret, trend  # noqa: E402
from journal_p2c import clean  # noqa: E402
from trades_p3 import build  # noqa: E402
from backtest_p4 import seg_metrics, simulate  # noqa: E402

FETCH_START, EVAL_START = "2022-02-01", "2022-09-01"
TZ, CURRENCY = "Asia/Seoul", "KRW"
FAST, SLOW = 20, 60
RSI_P, RSI_IN, RSI_OUT = 14, 30, 70
C_IN_LB, C_OUT_LB = 20, 10
WINDOWS = [60, 120]
# 비용 근거: 위탁수수료 온라인 0.015% 관행, 매도세 2025 코스피 실효 0.30%(거래세 0.15%+농특 0.15%).
# 2026 세법개정안 인상분은 미반영 (Decisions 참조, 변동 시 새 실험).
PROFILES = {
    "exp003": {"targets": {"005930.KS": "kr"}, "market": "069500.KS", "sector": "091160.KS",
               "initial": 10_000_000.0, "comm_bps": 0.0, "tax_bps": 0.0, "slip_bps": 0.0,
               "tag": "P5 한국 단일종목 베이스라인"},
    "exp004": {"targets": {"005930.KS": "005930KS", "000660.KS": "000660KS"},
               "market": "069500.KS", "sector": "091160.KS",
               "initial": 10_000_000.0, "comm_bps": 1.5, "tax_bps": 30.0, "slip_bps": 0.0,
               "tag": "P5+ 한국 2종목 실비용 (수수료 1.5bp·매도세 30bp)"},
    "exp005": {"targets": {"005930.KS": "005930KS", "000660.KS": "000660KS"},
               "market": "069500.KS", "sector": "091160.KS",
               "initial": 10_000_000.0, "comm_bps": 1.5, "tax_bps": 30.0, "slip_bps": 0.0,
               "tag": "F게이트 합성 (C 돌파+A 추세+거래량+ATR완충), 홀드아웃 2025~",
               "gate": True, "split": "2025-01-01"},
    "exp006": {"targets": {"005930.KS": "005930KS", "000660.KS": "000660KS",
                           "AAPL": "AAPL", "NVDA": "NVDA", "SATL": "SATL"},
               "market": "069500.KS", "sector": "091160.KS",
               "initial": 10_000_000.0, "comm_bps": 1.5, "tax_bps": 30.0, "slip_bps": 0.0,
               "tag": "한미 대표 유니버스 F게이트 (심볼별 시장·통화 적용)",
               "gate": True, "split": "2025-01-01", "multi": True},
    "exp007": {"targets": {"005930.KS": "005930KS", "000660.KS": "000660KS",
                           "AAPL": "AAPL", "NVDA": "NVDA", "SATL": "SATL",
                           "^KS11": "KS11", "^KQ11": "KQ11", "QQQ": "QQQ", "SPY": "SPY",
                           "069500.KS": "069500KS", "091160.KS": "091160KS",
                           "XLK": "XLK", "IWM": "IWM", "ITA": "ITA"},
               "market": "069500.KS", "sector": "091160.KS",
               "initial": 10_000_000.0, "comm_bps": 1.5, "tax_bps": 30.0, "slip_bps": 0.0,
               "tag": "누적 10년·전 유니버스 백테스트 (지수 포함, 홀드아웃 2025~)",
               "gate": True, "split": "2025-01-01", "multi": True,
               "fetch_start": "2015-01-01", "eval_start": "2016-01-01", "watch": []},
    "exp008": {"targets": {"005930.KS": "005930KS", "000660.KS": "000660KS",
                           "AAPL": "AAPL", "NVDA": "NVDA", "SATL": "SATL",
                           "^KS11": "KS11", "^KQ11": "KQ11", "QQQ": "QQQ", "SPY": "SPY",
                           "069500.KS": "069500KS", "091160.KS": "091160KS",
                           "XLK": "XLK", "IWM": "IWM", "ITA": "ITA"},
               "market": "069500.KS", "sector": "091160.KS",
               "initial": 10_000_000.0, "comm_bps": 1.5, "tax_bps": 30.0, "slip_bps": 0.0,
               "tag": "F게이트+1%리스크+2ATR트레일 (지속가능형, 홀드아웃 2025~)",
               "gate": True, "split": "2025-01-01", "multi": True,
               "fetch_start": "2015-01-01", "eval_start": "2016-01-01", "watch": [],
               "sized": True, "risk": 0.01, "stop_k": 2.0},
}
# 심볼별 시장 프로필 (exp006 멀티마켓용. 비용: 미국 $0 수수료·SEC 미반영 베이스라인)
SYM_PROFILE = {
    "005930.KS": {"tz": "Asia/Seoul", "ccy": "KRW", "mkt": "KR",
                  "market": "069500.KS", "sector": "091160.KS",
                  "initial": 10_000_000.0, "comm": 1.5, "tax": 30.0},
    "000660.KS": {"tz": "Asia/Seoul", "ccy": "KRW", "mkt": "KR",
                  "market": "069500.KS", "sector": "091160.KS",
                  "initial": 10_000_000.0, "comm": 1.5, "tax": 30.0},
    "AAPL": {"tz": "America/New_York", "ccy": "USD", "mkt": "USA",
             "market": "SPY", "sector": "XLK",
             "initial": 10_000.0, "comm": 0.0, "tax": 0.0},
    "NVDA": {"tz": "America/New_York", "ccy": "USD", "mkt": "USA",
             "market": "SPY", "sector": "XLK",
             "initial": 10_000.0, "comm": 0.0, "tax": 0.0},
    "SATL": {"tz": "America/New_York", "ccy": "USD", "mkt": "USA",
             "market": "IWM", "sector": "ITA",
             "initial": 10_000.0, "comm": 0.0, "tax": 0.0},
    "^KS11": {"tz": "Asia/Seoul", "ccy": "KRW", "mkt": "KR",
              "market": "069500.KS", "sector": "091160.KS",
              "initial": 10_000_000.0, "comm": 0.0, "tax": 0.0},
    "^KQ11": {"tz": "Asia/Seoul", "ccy": "KRW", "mkt": "KR",
              "market": "069500.KS", "sector": "091160.KS",
              "initial": 10_000_000.0, "comm": 0.0, "tax": 0.0},
    "QQQ": {"tz": "America/New_York", "ccy": "USD", "mkt": "USA",
            "market": "SPY", "sector": "XLK",
            "initial": 10_000.0, "comm": 0.0, "tax": 0.0},
    "SPY": {"tz": "America/New_York", "ccy": "USD", "mkt": "USA",
            "market": "SPY", "sector": "XLK",
            "initial": 10_000.0, "comm": 0.0, "tax": 0.0},
    "069500.KS": {"tz": "Asia/Seoul", "ccy": "KRW", "mkt": "KR",
                  "market": "069500.KS", "sector": "091160.KS",
                  "initial": 10_000_000.0, "comm": 1.5, "tax": 30.0},
    "091160.KS": {"tz": "Asia/Seoul", "ccy": "KRW", "mkt": "KR",
                  "market": "069500.KS", "sector": "091160.KS",
                  "initial": 10_000_000.0, "comm": 1.5, "tax": 30.0},
    "XLK": {"tz": "America/New_York", "ccy": "USD", "mkt": "USA",
            "market": "SPY", "sector": "XLK",
            "initial": 10_000.0, "comm": 0.0, "tax": 0.0},
    "IWM": {"tz": "America/New_York", "ccy": "USD", "mkt": "USA",
            "market": "SPY", "sector": "XLK",
            "initial": 10_000.0, "comm": 0.0, "tax": 0.0},
    "ITA": {"tz": "America/New_York", "ccy": "USD", "mkt": "USA",
            "market": "SPY", "sector": "XLK",
            "initial": 10_000.0, "comm": 0.0, "tax": 0.0},
}
REASONS = {
    ("A", "entry"): ("A_ENTRY_SMA_CROSS_UP", "SMA20이 SMA60을 상향 교차"),
    ("A", "exit"): ("A_EXIT_SMA_CROSS_DOWN", "SMA20이 SMA60을 하향 교차"),
    ("B", "entry"): ("B_ENTRY_RSI_UP_30", "RSI14가 30을 상향 교차"),
    ("B", "exit"): ("B_EXIT_RSI_DOWN_70", "RSI14가 70을 하향 교차"),
    ("C", "entry"): ("C_ENTRY_DONCHIAN_BREAK", "종가가 직전 20봉 최고가 초과"),
    ("C", "exit"): ("C_EXIT_DONCHIAN_BREAK", "종가가 직전 10봉 최저가 하회"),
    ("F", "entry"): ("F_ENTRY_GATED_BREAK", "돌파+추세순행(SMA)+거래량1.0초과+ATR강도0.1초과"),
    ("F", "exit"): ("F_EXIT_BREAK_OR_CROSS", "Donchian 하회 또는 SMA 하향교차"),
}

EXP, TARGET, STEM = "exp003", "005930.KS", "kr"
MARKET, SECTOR, INITIAL = "069500.KS", "091160.KS", 10_000_000.0
COMM_BPS, TAX_BPS, SLIP_BPS = 0.0, 0.0, 0.0
MKT, TZ, CURRENCY = "KR", "Asia/Seoul", "KRW"
SYMBOLS = [TARGET, MARKET, SECTOR]
SNAP_DIR = ROOT / "data" / "snapshots" / EXP
RES = ROOT / "results" / EXP
WITH_FEES = False
WATCH = ["^KS11", "QQQ"]  # 조회 전용 (신호·거래 없음)


def use(exp: str, target: str) -> None:
    global EXP, TARGET, STEM, MARKET, SECTOR, INITIAL
    global COMM_BPS, TAX_BPS, SLIP_BPS, SYMBOLS, SNAP_DIR, RES, WITH_FEES
    global MKT, TZ, CURRENCY, EVAL_START
    p = PROFILES[exp]
    EXP, TARGET = exp, target
    STEM = p["targets"][target]
    EVAL_START = p.get("eval_start", "2022-09-01")
    if p.get("multi"):
        sp = SYM_PROFILE[target]
        MARKET, SECTOR = sp["market"], sp["sector"]
        INITIAL, COMM_BPS, TAX_BPS = sp["initial"], sp["comm"], sp["tax"]
        SLIP_BPS = 0.0
        MKT, TZ, CURRENCY = sp["mkt"], sp["tz"], sp["ccy"]
    else:
        MARKET, SECTOR, INITIAL = p["market"], p["sector"], p["initial"]
        COMM_BPS, TAX_BPS, SLIP_BPS = p["comm_bps"], p["tax_bps"], p["slip_bps"]
        MKT, TZ, CURRENCY = "KR", "Asia/Seoul", "KRW"
    WITH_FEES = (COMM_BPS, TAX_BPS, SLIP_BPS) != (0.0, 0.0, 0.0)
    extra = [b for t in p["targets"] for b in (SYM_PROFILE[t]["market"], SYM_PROFILE[t]["sector"])] \
        if p.get("multi") else [MARKET, SECTOR]
    watch = p.get("watch", WATCH)
    SYMBOLS = sorted(set([*p["targets"], *extra] + (watch if p.get("multi") else [])))
    SNAP_DIR = ROOT / "data" / "snapshots" / EXP
    RES = ROOT / "results" / EXP


def close_stamp(date_s: str) -> str:
    """장 마감 시각 (서머타임 자동)."""
    if TZ == "Asia/Seoul":
        return date_s + "T15:30:00+09:00"
    off = pd.Timestamp(date_s, tz=TZ).utcoffset()
    s = int(off.total_seconds() // 3600)
    return f"{date_s}T16:00:00{'-' if s < 0 else '+'}{abs(s):02d}:00"


def sha_short(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fetch(exp: str) -> None:
    use(exp, sorted(PROFILES[exp]["targets"])[0])
    p = PROFILES[exp]
    start = p.get("fetch_start", FETCH_START)
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    RES.mkdir(parents=True, exist_ok=True)
    frames = {}
    dropped = {}
    for s in SYMBOLS:
        tz = SYM_PROFILE[s]["tz"] if s in SYM_PROFILE else \
            ("Asia/Seoul" if s.endswith(".KS") or s.startswith("^KS") else "America/New_York")
        df = yf.Ticker(s).history(start=start, auto_adjust=False)
        if len(df) == 0:
            raise SystemExit(f"수집 실패(0행): {s} — 기존 스냅샷 유지, 다음 실행으로 연기")
        df = df.tz_convert(tz) if df.index.tz is not None else df.tz_localize(tz)
        adj = to_adjusted(df)
        bad_rows = adj[["open", "high", "low", "close"]].isna().any(axis=1)
        dropped[s] = sorted(str(d.date()) for d in adj.index[bad_rows])
        frames[s] = adj[~bad_rows]  # 공급처 글리치 행 제거 (기록 유지, 보간 없음)
    quality = quality_checks(frames)
    for s, ds in dropped.items():
        quality[s]["dropped_nan_ohlc"] = ds
    bad = [s for s, q in quality.items() if q["rows"] < 100]
    if bad:
        raise SystemExit(f"수집 부족 {bad} — 기존 스냅샷 유지, 다음 실행으로 연기")
    parts = []
    for s, df in frames.items():
        part = df.assign(symbol=s).reset_index(names="timestamp")
        part["date"] = pd.to_datetime(part["timestamp"], utc=True).dt.tz_convert(
            df.index.tz).dt.date.astype(str)  # 심볼 현지 거래일 기준
        parts.append(part)
    long = pd.concat(parts)
    long = long[["date", "symbol", "open", "high", "low", "close",
                 "volume", "adj_factor", "dividends", "split"]]
    csv_path = SNAP_DIR / "ohlcv.csv"
    long.to_csv(csv_path, index=False, float_format="%.6f")
    sha = sha_short(csv_path)
    manifest = {
        "experiment_id": exp + "-kr-daily-v1",
        "symbols": SYMBOLS, "fetch_start": start,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_end": {s: quality[s]["last"] for s in SYMBOLS},
        "provider": "yfinance",
        "versions": {"python": sys.version.split()[0], "yfinance": yf.__version__,
                     "pandas": pd.__version__, "numpy": np.__version__},
        "exchange_timezone": TZ, "currency": CURRENCY,
        "costs_bps": ({t: {"commission": SYM_PROFILE[t]["comm"],
                            "sell_tax": SYM_PROFILE[t]["tax"], "slippage": 0.0}
                      for t in p["targets"]} if p.get("multi") else
                      {"commission": p["comm_bps"],
                       "sell_tax": p["tax_bps"], "slippage": p["slip_bps"]}),
        "adjustment": "adjusted-close (OHLC x AdjClose/Close, volume unadjusted)",
        "corporate_action_policy": "adjusted-price-study",
        "sha256_ohlcv_csv": sha, "rows": int(len(long)), "quality": quality,
        "pinned_prev_sha256": prior_pins(exp),
    }
    (SNAP_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (RES / "quality_summary.md").write_text(
        f"# 품질 요약 ({exp}, {CURRENCY}·{TZ})\n\n"
        + "".join(f"- {s}: {quality[s]['rows']}행 {quality[s]['first']}~{quality[s]['last']}, "
                  f"결측 {quality[s]['nan_ohlc']}, 고저오류 {quality[s]['high_lt_low']}\n"
                  for s in SYMBOLS))
    print(json.dumps({s: (quality[s]["rows"], quality[s]["first"], quality[s]["last"])
                      for s in SYMBOLS}))


def atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, p: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    seed = tr.rolling(p, min_periods=p).mean()
    a = seed.to_numpy().copy()
    v = tr.to_numpy()
    for i in range(p + 1, len(tr)):
        if a[i - 1] == a[i - 1] and v[i] == v[i]:
            a[i] = (a[i - 1] * (p - 1) + v[i]) / p
    return pd.Series(a, index=tr.index)


def indicators() -> pd.DataFrame:
    snap = pd.read_csv(SNAP_DIR / "ohlcv.csv", parse_dates=["date"])
    df = snap[snap["symbol"] == TARGET].sort_values("date").reset_index(drop=True)
    close, high, low = df["close"], df["high"], df["low"]
    sma20 = close.rolling(FAST, min_periods=FAST).mean()
    sma60 = close.rolling(SLOW, min_periods=SLOW).mean()
    rsi = wilder_rsi(close, RSI_P)
    don_hi = high.shift(1).rolling(C_IN_LB, min_periods=C_IN_LB).max()
    don_lo = low.shift(1).rolling(C_OUT_LB, min_periods=C_OUT_LB).min()
    atr = atr_wilder(high, low, close)
    vol_ratio = df["volume"] / df["volume"].rolling(20, min_periods=20).mean()
    out = pd.DataFrame({
        "date": df["date"].dt.date.astype(str),
        "close": close.round(2), "sma20": sma20.round(2), "sma60": sma60.round(2),
        "rsi14": rsi.round(2), "don_hi20": don_hi.round(2), "don_lo10": don_lo.round(2),
        "atr14": atr.round(2), "vol_ratio": vol_ratio.round(3),
    })
    ready = sma60.notna() & rsi.notna() & don_hi.notna() & don_lo.notna()
    for col in ("sigA", "sigB", "sigC"):
        out[col] = "none"
    out.loc[cross_up(sma20, sma60) & ready, "sigA"] = "entry"
    out.loc[cross_down(sma20, sma60) & ready, "sigA"] = "exit"
    out.loc[(rsi.shift(1) <= RSI_IN) & (rsi > RSI_IN) & ready, "sigB"] = "entry"
    out.loc[(rsi.shift(1) >= RSI_OUT) & (rsi < RSI_OUT) & ready, "sigB"] = "exit"
    out.loc[(close > don_hi) & ready, "sigC"] = "entry"
    out.loc[(close < don_lo) & ready, "sigC"] = "exit"
    if PROFILES[EXP].get("gate"):
        # F게이트: C 돌파 + A 추세순행 + 거래량 + ATR 강도완충
        gate = (close > sma60) & (sma20 > sma60) & ready
        strength = (close - don_hi) / atr > 0.1
        out["sigF"] = "none"
        out.loc[(close > don_hi) & gate & (vol_ratio > 1.0) & strength, "sigF"] = "entry"
        out.loc[((close < don_lo) | cross_down(sma20, sma60)) & ready, "sigF"] = "exit"
    out["in_eval"] = df["date"] >= pd.Timestamp(EVAL_START)
    out.to_csv(RES / f"indicators_{STEM}.csv", index=False)
    ev = out[out["in_eval"]]
    print(f"{TARGET} rows={len(out)} eval={len(ev)} "
          f"A={dict(ev['sigA'].value_counts())} B={dict(ev['sigB'].value_counts())} "
          f"C={dict(ev['sigC'].value_counts())}")
    return out


def context() -> None:
    snap = pd.read_csv(SNAP_DIR / "ohlcv.csv", parse_dates=["date"])
    px = snap.pivot(index="date", columns="symbol", values="close").sort_index()
    all_dates = px.index
    out = pd.DataFrame({"date": all_dates.date.astype(str)})
    own = px[TARGET].dropna()
    out["trend_tgt"] = trend(own).reindex(all_dates).to_numpy()
    for label, bench in (("mkt", MARKET), ("sec", SECTOR)):
        if bench == TARGET:  # 자기참조(지수·ETF 자체가 벤치마크): 항등값
            out[f"trend_{label}"] = out["trend_tgt"]
            for w in WINDOWS:
                out[f"beta_{label}_{w}"] = 1.0
                out[f"corr_{label}_{w}"] = 1.0
                out[f"r2_{label}_{w}"] = 1.0
                out[f"na_{label}_{w}"] = "self"
            continue
        out[f"trend_{label}"] = trend(px[bench].dropna()).reindex(all_dates).to_numpy()
        pair = px[[TARGET, bench]].dropna()
        rt = pair[TARGET] / pair[TARGET].shift(1) - 1
        rb = pair[bench] / pair[bench].shift(1) - 1
        for w in WINDOWS:
            b, c, r2, reason = beta_corr(rt.shift(1), rb.shift(1), w)
            for name, ser in (("beta", b), ("corr", c), ("r2", r2)):
                out[f"{name}_{label}_{w}"] = ser.round(6).reindex(all_dates).to_numpy()
            out[f"na_{label}_{w}"] = reason.reindex(all_dates).fillna("no_overlap").to_numpy()
    mkt, sec = px[MARKET].dropna(), px[SECTOR].dropna()
    pm = pd.concat([own, mkt], axis=1, join="inner")
    ps = pd.concat([own, sec], axis=1, join="inner")
    pms = pd.concat([sec, mkt], axis=1, join="inner")
    out["rel_stock_mkt_pp"] = ((cumret(pm.iloc[:, 0], 20) - cumret(pm.iloc[:, 1], 20)) * 100) \
        .round(3).reindex(all_dates).to_numpy()
    out["rel_stock_sec_pp"] = ((cumret(ps.iloc[:, 0], 20) - cumret(ps.iloc[:, 1], 20)) * 100) \
        .round(3).reindex(all_dates).to_numpy()
    out["rel_sec_mkt_pp"] = ((cumret(pms.iloc[:, 0], 20) - cumret(pms.iloc[:, 1], 20)) * 100) \
        .round(3).reindex(all_dates).to_numpy()
    out.to_csv(RES / f"context_{STEM}.csv", index=False)
    ev = out[out["date"] >= EVAL_START]
    print(f"{TARGET} rows={len(out)} mkt60_ok={int((ev['na_mkt_60'] == 'ok').sum())}")


STRAT_COLS = [("A", "sigA"), ("B", "sigB"), ("C", "sigC")]
IND_COLS = {"A": ("sma20", "sma60"), "B": ("rsi14",), "C": ("don_hi20", "don_lo10"),
            "F": ("don_hi20", "sma20", "sma60", "atr14", "vol_ratio")}


def strat_list() -> list[tuple[str, str]]:
    return STRAT_COLS + ([("F", "sigF")] if PROFILES[EXP].get("gate") else [])


def ledger(run_id: str) -> int:
    ind = pd.read_csv(RES / f"indicators_{STEM}.csv", parse_dates=["date"])
    ctx = pd.read_csv(RES / f"context_{STEM}.csv", parse_dates=["date"])
    merged = ind.merge(ctx, on="date", how="left")
    merged["date_s"] = merged["date"].dt.date.astype(str)
    events: list[dict] = []
    strats = strat_list()
    position = {s: 0 for s, _ in strats}
    for _, r in merged[merged["date_s"] >= EVAL_START].iterrows():
        for strat, col in strats:
            side = r[col]
            if side not in ("entry", "exit"):
                continue
            code, desc = REASONS[(strat, side)]
            before = position[strat]
            position[strat] = 1 if side == "entry" else 0
            events.append(clean({
                "event_id": f"{run_id}|{strat}|{TARGET}|{r['date_s']}|{side}",
                "run_id": run_id, "strategy": strat, "rule_version": "research-2026-09-03",
                "symbol": TARGET, "market": MKT, "timeframe": "1D",
                "signal_bar_close": close_stamp(r["date_s"]),
                "record_type": "historical_reconstruction",
                "side": side, "reason_code": code, "reason_desc": desc,
                "indicator_now": {k: r[k] for k in IND_COLS[strat]},
                "signal_price": round(float(r["close"]), 2),
                "position_before": before,
                "repeated_signal": bool((side == "entry" and before == 1) or
                                        (side == "exit" and before == 0)),
                "filter": None, "filter_decision": "allowed", "execution": None,
                "market_ref": {"id": MARKET, "type": "INDEX" if TARGET.startswith("^") else "ETF",
                               "trend": r["trend_mkt"], "beta_60": r["beta_mkt_60"],
                               "corr_60": r["corr_mkt_60"], "r2_60": r["r2_mkt_60"]},
                "sector_ref": {"id": SECTOR, "type": "ETF",
                               "trend": r["trend_sec"], "beta_60": r["beta_sec_60"],
                               "corr_60": r["corr_sec_60"], "r2_60": r["r2_sec_60"]},
                "rel_pp": {"stock_mkt": r["rel_stock_mkt_pp"],
                           "stock_sec": r["rel_stock_sec_pp"]},
                "estimation": {"window": 60, "na_reason_mkt": r["na_mkt_60"],
                               "na_reason_sec": r["na_sec_60"]},
                "data_version": manifest_sha()[:12],
                "code_hash": hashlib.sha256((ROOT / "scripts" / "kr_p5.py").read_bytes()
                                            ).hexdigest()[:12],
                "source": "yfinance", "currency": CURRENCY,
            }))
    with (RES / f"ledger_{STEM}.jsonl").open("w") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return len(events)


def manifest_sha() -> str:
    return json.loads((SNAP_DIR / "manifest.json").read_text())["sha256_ohlcv_csv"]


SIZED_EQ: dict = {}


def trades() -> None:
    import trades_p3
    trades_p3.INITIAL_CAPITAL = INITIAL
    snap = pd.read_csv(SNAP_DIR / "ohlcv.csv", parse_dates=["date"])
    ind = pd.read_csv(RES / f"indicators_{STEM}.csv", parse_dates=["date"])
    tgt = snap[snap["symbol"] == TARGET].sort_values("date").reset_index(drop=True)
    tgt["date_s"] = tgt["date"].dt.date.astype(str)
    ind["date_s"] = ind["date"].dt.date.astype(str)
    df = ind[ind["in_eval"]].merge(tgt[["date_s", "open"]],
                                   on="date_s", how="left").reset_index(drop=True)
    sized = PROFILES[EXP].get("sized", False)
    for strat, col in strat_list():
        if sized:
            tr, st, eq, held = trades_p3.build_sized(
                df, col, "atr14", COMM_BPS, TAX_BPS, SLIP_BPS,
                include_fees=WITH_FEES, risk=PROFILES[EXP]["risk"], k=PROFILES[EXP]["stop_k"])
            SIZED_EQ[(TARGET, strat)] = (eq, held)
        else:
            tr, st = build(df, col, COMM_BPS, TAX_BPS, SLIP_BPS, include_fees=WITH_FEES)
        pd.DataFrame(tr).to_csv(RES / f"trades_{strat}_{STEM}.csv", index=False)
        print(TARGET, strat, {k: round(v, 2) if isinstance(v, float) else v
                              for k, v in st.items()}, f"rows={len(tr)}")


def performance(all_eq: dict) -> None:
    split = PROFILES[EXP].get("split")
    md = [f"# 성과 비교 ({EXP}, 비용 수수료 {COMM_BPS}bp·매도세 {TAX_BPS}bp)", "",
          f"- 초기자본 {INITIAL:,.0f} {CURRENCY}·전액/전량·t+1 시가. B&H는 첫 평가봉 다음 시가 매수.",
          "- 국내 실제 비용(수수료·매도세) 반영 베이스라인(세전, 실전 아님).", ""]
    if PROFILES[EXP].get("sized"):
        md += [f"- 포지션: 건당 {PROFILES[EXP]['risk'] * 100:.0f}% 리스크·"
               f"{PROFILES[EXP]['stop_k']:.0f}ATR 트레일스탑 (전액/전량 아님, B&H 제외).", ""]
    if split:
        md += [f"- 구간 분리: 인샘플(평가~{split} 전날) vs 홀드아웃({split}~). "
               "합성 규칙은 평가 이전에 고정했고, 홀드아웃은 사후 보고용(선택 편향 주의).", ""]
        md += ["| 종목 | 전략 | 순수익% | MDD% | 노출% | 완료 | 승률% | 평균손익 | 수수료합 | 인샘플% | 홀드아웃% |",
               "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    else:
        md += ["| 종목 | 전략 | 순수익% | MDD% | 노출% | 완료 | 승률% | 평균손익 | 수수료합 |",
               "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for (tgt, s), (eq, held, tr, st, dates) in all_eq.items():
        full = seg_metrics(eq, held)
        pnl = pd.to_numeric(tr["pnl"], errors="coerce").tolist() if len(tr) and "pnl" in tr else []
        pnl = [v for v in pnl if v == v]
        row = (f"| {tgt} | {s} | {full['net_ret_pct']} | {full['mdd_pct']} | "
               f"{full['exposure_pct']} | {st['completed']} | "
               f"{round(sum(1 for v in pnl if v > 0) / len(pnl) * 100, 1) if pnl else '-'} | "
               f"{round(sum(pnl) / len(pnl)) if pnl else '-'} | "
               f"{round(st.get('fees_paid', 0.0))} |")
        if split:
            k = next(i for i, d in enumerate(dates) if d >= split)
            pre = seg_metrics(eq[:k], held[:k])
            post = seg_metrics(eq[k:], held[k:])
            row += f" {pre['net_ret_pct']}% | {post['net_ret_pct']}% |"
        md.append(row)
        print(tgt, s, full)
    (RES / "performance.md").write_text("\n".join(md) + "\n")


def run_target(run_id: str, all_eq: dict) -> None:
    indicators()
    context()
    ledger(run_id)
    trades()
    snap = pd.read_csv(SNAP_DIR / "ohlcv.csv", parse_dates=["date"])
    ind = pd.read_csv(RES / f"indicators_{STEM}.csv", parse_dates=["date"])
    tgt = snap[snap["symbol"] == TARGET].sort_values("date").reset_index(drop=True)
    tgt["date_s"] = tgt["date"].dt.date.astype(str)
    ind["date_s"] = ind["date"].dt.date.astype(str)
    ev = ind[ind["in_eval"]].merge(tgt[["date_s", "open", "close"]], on="date_s",
                                   how="left", suffixes=("", "_snap")).reset_index(drop=True)
    ev["close"] = ev["close_snap"]
    dates, opens, closes = ev["date_s"].tolist(), ev["open"].tolist(), ev["close"].tolist()
    import trades_p3
    trades_p3.INITIAL_CAPITAL = INITIAL
    for s, _ in strat_list():
        t = pd.read_csv(RES / f"trades_{s}_{STEM}.csv", dtype=str).fillna("")
        if PROFILES[EXP].get("sized"):
            eq, held = SIZED_EQ[(TARGET, s)]
        else:
            events = {}
            for _, r in t.iterrows():
                if r["entry_exec_date"]:
                    events[r["entry_exec_date"]] = ("buy", float(r["entry_price"]))
                if r["exit_exec_date"]:
                    events[r["exit_exec_date"]] = ("sell", float(r["exit_price"]))
            eq, held = simulate(dates, opens, closes, events, COMM_BPS, TAX_BPS, SLIP_BPS)
        pd.DataFrame({"date": dates, "equity": [round(v) for v in eq]}
                     ).to_csv(RES / f"equity_{s}_{STEM}.csv", index=False)
        all_eq[(TARGET, s)] = (eq, held, t, {"completed": int((t["status"] == "completed").sum()),
                                             "fees_paid": float(t["fees"].astype(float).sum())
                                             if "fees" in t.columns and len(t) else 0.0}, dates)
    eq, _ = simulate(dates, opens, closes, {dates[1]: ("buy", opens[1])},
                     COMM_BPS, TAX_BPS, SLIP_BPS)
    held_bh = [0] + [1] * (len(dates) - 1)
    pd.DataFrame({"date": dates, "equity": [round(v) for v in eq]}
                 ).to_csv(RES / f"equity_BH_{STEM}.csv", index=False)
    all_eq[(TARGET, "BH")] = (eq, held_bh, pd.DataFrame(), {"completed": 0, "fees_paid": 0.0}, dates)


def main() -> None:
    exp = sys.argv[1] if len(sys.argv) > 1 else "exp003"
    if exp == "exp003":
        raise SystemExit("exp003은 동결됨(커밋 7259ad9). 재실행 금지.")
    fetch(exp)
    code_h = hashlib.sha256((ROOT / "scripts" / "kr_p5.py").read_bytes()).hexdigest()[:12]
    run_id = f"{exp}-{manifest_sha_for(exp)[:8]}-{code_h}"
    all_eq: dict = {}
    for target in sorted(PROFILES[exp]["targets"]):
        use(exp, target)
        run_target(run_id, all_eq)
    use(exp, sorted(PROFILES[exp]["targets"])[0])
    performance(all_eq)
    (RES / "README.md").write_text(
        f"# 결과 — {exp} ({PROFILES[exp]['tag']})\n\n재실행: `.venv/bin/python scripts/kr_p5.py {exp}` "
        f"+ 차트·`verify_exp004.py`.\n")


def manifest_sha_for(exp: str) -> str:
    return json.loads((ROOT / "data" / "snapshots" / exp / "manifest.json").read_text()
                      )["sha256_ohlcv_csv"]


def prior_pins(exp: str) -> dict:
    """이전 실험 산출물 핀 (불변 증거)."""
    pins = {}
    for prior in ["exp002", *[p for p in sorted(PROFILES) if p < exp]]:
        for base in ("results", "data/snapshots"):
            d = ROOT / base / prior
            if d.is_dir():
                for p in sorted(d.glob("*.csv")) + sorted(d.glob("*.jsonl")):
                    pins[f"{base}/{prior}/{p.name}"] = sha_short(p)
    return pins


if __name__ == "__main__":
    main()
