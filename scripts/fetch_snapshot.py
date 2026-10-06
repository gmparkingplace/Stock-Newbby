"""P2 스냅샷 수집: yfinance 일봉 원본 -> 조정 OHLCV CSV + manifest + 품질 요약.

Source of truth: experiments/exp002-satl-iwm-daily-v1.yaml
(yaml 파서가 venv에 없어 핵심 값을 아래에 미러했다. 변경 시 yaml이 우선.)
실행: .venv/bin/python scripts/fetch_snapshot.py
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT_ID = "exp002-satl-iwm-v1"
SYMBOLS = ["SATL", "IWM", "ITA"]  # ITA: P2b 섹터 기준 (exp002 미러)
FETCH_START = "2022-02-01"
EXCHANGE_TZ = "America/New_York"
OUT_DIR = ROOT / "data" / "snapshots" / "exp002"


def fetch_raw(sym: str) -> pd.DataFrame:
    df = yf.Ticker(sym).history(start=FETCH_START, auto_adjust=False)
    df = df.tz_convert(EXCHANGE_TZ) if df.index.tz is not None else df.tz_localize(EXCHANGE_TZ)
    return df


def to_adjusted(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower().replace(" ", "_"): c for c in df.columns}
    o, h, l, c = (df[cols[k]] for k in ("open", "high", "low", "close"))
    adj = df[cols["adj_close"]] if "adj_close" in cols else c
    factor = (adj / c).where(c != 0, 1.0).fillna(1.0)
    return pd.DataFrame({
        "open": o * factor, "high": h * factor, "low": l * factor,
        "close": adj, "volume": df[cols["volume"]],
        "adj_factor": factor,
        "dividends": df[cols["dividends"]] if "dividends" in cols else 0.0,
        "split": df[cols["stock_splits"]] if "stock_splits" in cols else 0.0,
    }, index=df.index)


def quality_checks(frames: dict[str, pd.DataFrame]) -> dict:
    report: dict = {}
    for sym, df in frames.items():
        idx = df.index
        bad_hl = df[df["high"] < df["low"]]
        bad_oc = df[(df["high"] < df[["open", "close"]].max(axis=1)) |
                    (df["low"] > df[["open", "close"]].min(axis=1))]
        report[sym] = {
            "rows": int(len(df)),
            "first": str(idx[0].date()), "last": str(idx[-1].date()),
            "time_monotonic": bool(idx.is_monotonic_increasing),
            "duplicates": int(idx.duplicated().sum()),
            "nan_ohlc": int(df[["open", "high", "low", "close"]].isna().sum().sum()),
            "nan_volume": int(df["volume"].isna().sum()),
            "zero_volume": int((df["volume"] == 0).sum()),
            "high_lt_low": int(len(bad_hl)),
            "high_low_outside_oc_range": int(len(bad_oc)),
            "adjusted_bars": int((df["adj_factor"] != 1.0).sum()),
            "splits": int((df["split"] != 0).sum()),
            "dividends_paid": int((df["dividends"] != 0).sum()),
        }
    return report


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames = {s: to_adjusted(fetch_raw(s)) for s in SYMBOLS}
    quality = quality_checks(frames)

    long = pd.concat(
        [df.assign(symbol=s) for s, df in frames.items()]
    ).reset_index(names="timestamp")
    long["date"] = pd.to_datetime(long["timestamp"]).dt.date.astype(str)
    long = long[["date", "symbol", "open", "high", "low", "close",
                 "volume", "adj_factor", "dividends", "split"]]
    csv_path = OUT_DIR / "ohlcv.csv"
    long.to_csv(csv_path, index=False, float_format="%.6f")

    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "symbols": SYMBOLS,
        "fetch_start": FETCH_START,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_end": {s: quality[s]["last"] for s in SYMBOLS},
        "provider": "yfinance",
        "versions": {"python": sys_version(), "yfinance": yf.__version__,
                     "pandas": pd.__version__, "numpy": np.__version__},
        "exchange_timezone": EXCHANGE_TZ,
        "adjustment": "adjusted-close (OHLC x AdjClose/Close, volume unadjusted)",
        "corporate_action_policy": "adjusted-price-study",
        "sha256_ohlcv_csv": sha,
        "rows": int(len(long)),
        "quality": quality,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    lines = [f"# P2 데이터 품질 요약 ({EXPERIMENT_ID})", "",
             f"- 수집: {FETCH_START} ~ {max(quality[s]['last'] for s in SYMBOLS)} (yfinance, 인증 불필요)",
             f"- 스냅샷: data/snapshots/exp002/ohlcv.csv (sha256 {sha[:12]}...), manifest.json",
             f"- 시간대: {EXCHANGE_TZ} · 조정: 수정종가 기준 (OHLC 전체에 동일 factor, 거래량 미조정)", ""]
    for s in SYMBOLS:
        q = quality[s]
        lines += [f"## {s}", "",
                  f"- 구간 {q['first']} ~ {q['last']}, {q['rows']}행",
                  f"- 시간 단조증가: {q['time_monotonic']}, 중복: {q['duplicates']}, OHLC 결측: {q['nan_ohlc']}",
                  f"- 거래량 결측(NaN): {q['nan_volume']}, 거래량 0: {q['zero_volume']} (NaN과 0 구분 보관)",
                  f"- 고저가 오류(high<low): {q['high_lt_low']}, H/L이 O/C 범위 밖: {q['high_low_outside_oc_range']}",
                  f"- 조정 적용 봉: {q['adjusted_bars']}, 분할: {q['splits']}, 배당: {q['dividends_paid']}", ""]
    lines += ["판정: 휴장일 보간 없음(거래일만 존재). 결측·오류 0이면 P2 품질 DoD 통과.",
              "SATL 2021년 SPAC NAV 구간은 수집 시작일(2022-02-01)로 원천 제외했다."]
    (ROOT / "results" / "exp002" / "quality_summary.md").parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "exp002" / "quality_summary.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(quality, indent=2))


def sys_version() -> str:
    import sys
    return sys.version.split()[0]


if __name__ == "__main__":
    main()
