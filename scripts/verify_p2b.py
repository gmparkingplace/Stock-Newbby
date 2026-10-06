"""P2b 검증: 인공 자료 베타=2, N/A 처리, 3개봉 독립 재계산 대조.

실행: .venv/bin/python scripts/verify_p2b.py  (종료코드 0 = 통과)
출력: results/exp002/context_spotcheck.md
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "exp002"
EVAL_START = "2022-09-01"
SAMPLE_DATES = ["2022-09-01", "2023-06-01", "2024-06-03"]
TOL = 1e-6
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)


def plain_beta(s: list[float], m: list[float]) -> float | None:
    n = len(s)
    ms, mm = sum(s) / n, sum(m) / n
    cov = sum((a - ms) * (b - mm) for a, b in zip(s, m)) / (n - 1)
    var = sum((b - mm) ** 2 for b in m) / (n - 1)
    if abs(var) < 1e-12:
        return None
    return cov / var


def main() -> None:
    ctx = pd.read_csv(RES / "context_satl.csv")
    snap = pd.read_csv(ROOT / "data" / "snapshots" / "exp002" / "ohlcv.csv", parse_dates=["date"])
    px = snap.pivot(index="date", columns="symbol", values="close").sort_index()
    rets = px / px.shift(1) - 1
    dates = [d.date().isoformat() for d in px.index]

    # 1) 인공 2배 수익률 -> 시장 베타 2 (실제 IWM 수익률 기반, 결정적)
    m = rets["IWM"].dropna().tolist()[100:220]
    s = [2 * x for x in m]
    b = plain_beta(s, m)
    check("인공 2배 수익률 베타=2", b is not None and abs(b - 2.0) < 1e-9, f"beta={b}")

    # 2) 분산 0 벤치마크 -> N/A (None)
    check("분산 0 -> N/A", plain_beta(s, [0.01] * len(s)) is None)

    # 3) 평가구간 첫 봉부터 60일창 유효 (웜업 147일 확보)
    first = ctx[ctx["date"] >= EVAL_START].iloc[0]
    check("평가 첫 봉 60일창 ok", first["na_mkt_60"] == "ok" and first["na_sec_60"] == "ok",
          f"{first['date']}")
    check("평가 첫 봉 120일창 ok", first["na_mkt_120"] == "ok" and first["na_sec_120"] == "ok")

    # 4) 3개봉 독립 재계산 대조 (t-1까지 60개 표본)
    rows = []
    for sd in SAMPLE_DATES:
        d0 = max(d for d in dates if d <= sd)
        i = dates.index(d0)
        r = ctx[ctx["date"] == d0].iloc[0]
        e_b = plain_beta(rets["SATL"].tolist()[i - 60:i], rets["IWM"].tolist()[i - 60:i])
        ok = e_b is not None and abs(e_b - r["beta_mkt_60"]) < 1e-4
        check(f"베타 독립 재계산 ({d0})", ok, f"csv={r['beta_mkt_60']} plain={e_b}")
        rows.append((d0, r))

    md = ["# P2b 대조표 (SATL 맥락값)", "",
          "| 봉 | 추세(종목/시장/섹터) | 베타m60 | 베타m120 | 베타s60 | 종목-시장pp | 종목-섹터pp |",
          "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for d0, r in rows:
        md.append(f"| {d0} | {r['trend_satl']}/{r['trend_mkt']}/{r['trend_sec']} | "
                  f"{r['beta_mkt_60']} | {r['beta_mkt_120']} | {r['beta_sec_60']} | "
                  f"{r['rel_stock_mkt_pp']} | {r['rel_stock_sec_pp']} |")
    md += ["", "베타 허용오차 1e-4(독립 루프 누적 순서 차이). 베타는 민감도이며 예측 배율이 아니다."]
    (RES / "context_spotcheck.md").write_text("\n".join(md) + "\n")
    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
