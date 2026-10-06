"""exp007 포트폴리오 합산: 14종목 동일가중 일별수익 평균 (규칙 변경 없음, 측정 전용).

실행: .venv/bin/python scripts/portfolio_exp007.py
출력: results/exp007/portfolio_{A,B,C,F,BH}.csv (date, equity, n)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "exp007"
TARGETS = {"005930.KS": "005930KS", "000660.KS": "000660KS",
           "AAPL": "AAPL", "NVDA": "NVDA", "SATL": "SATL",
           "^KS11": "KS11", "^KQ11": "KQ11", "QQQ": "QQQ", "SPY": "SPY",
           "069500.KS": "069500KS", "091160.KS": "091160KS",
           "XLK": "XLK", "IWM": "IWM", "ITA": "ITA"}


def load_ret(stem: str, strat: str) -> pd.Series:
    e = pd.read_csv(RES / f"equity_{strat}_{stem}.csv", dtype={"date": str})
    e = e.sort_values("date").reset_index(drop=True)
    r = e["equity"].astype(float) / float(e["equity"].iloc[0])
    return pd.Series(r.values, index=pd.to_datetime(e["date"]))


def main() -> None:
    for strat in ("A", "B", "C", "F", "BH"):
        rets = {t: load_ret(stem, strat) for t, stem in TARGETS.items()}
        cal = sorted(set().union(*[set(s.index) for s in rets.values()]))
        mat = pd.DataFrame({t: s.reindex(cal) for t, s in rets.items()})
        daily = mat.ffill().pct_change().fillna(0.0)
        avail = mat.notna()
        mean_r = (daily * avail).sum(axis=1) / avail.sum(axis=1)
        eq = (1 + mean_r).cumprod()
        out = pd.DataFrame({"date": [d.isoformat() for d in eq.index],
                            "equity": (eq * 10000).round(2),
                            "n": avail.sum(axis=1).astype(int)})
        out.to_csv(RES / f"portfolio_{strat}.csv", index=False)
        peak = eq.cummax()
        mdd = float(((eq - peak) / peak).min() * 100)
        vol = float(mean_r.std() * (252 ** 0.5) * 100)
        print(f"{strat}: 순수익 {float(eq.iloc[-1] - 1) * 100:.1f}% MDD {mdd:.1f}% "
              f"연변동성 {vol:.1f}% rows={len(out)}")


if __name__ == "__main__":
    main()
