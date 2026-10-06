"""실제 검증: 커밋된 전 단계 재검증 + 최신봉 라이브 신호 리포트 + Pine 확인표 대조.

실행: .venv/bin/python scripts/live_check.py  (종료코드 0 = 전부 통과)
출력: results/live_check_YYYY-MM-DD.md (포워드 추적용 스냅샷)
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
fails: list[str] = []
log: list[str] = []


def run(cmd: list[str]) -> bool:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    ok = r.returncode == 0
    print(("PASS" if ok else "FAIL"), " ".join(cmd[1:]))
    if not ok:
        fails.append(" ".join(cmd[1:]))
        log.append("```\n" + (r.stdout + r.stderr)[-1500:] + "\n```")
    return ok


def main() -> None:
    py = str(ROOT / ".venv" / "bin" / "python")
    today = date.today().isoformat()
    log.append(f"# 라이브 검증 ({today})")
    for args in (["scripts/verify_p2.py"], ["scripts/verify_p2b.py"], ["scripts/verify_p2c.py"],
                 ["scripts/verify_p3.py"], ["scripts/verify_p4.py"],
                 ["scripts/verify_p5kr.py"], ["scripts/verify_exp004.py"]):
        run([py, *args])

    # Pine 확인표 대조 (헤더 기대값 == CSV 신호)
    pine = (ROOT / "scripts" / "strategy_abc.pine").read_text()
    ind = pd.read_csv(ROOT / "results" / "exp002" / "indicators_satl.csv", parse_dates=["date"])
    ind["date_s"] = ind["date"].dt.date.astype(str)
    pine_cases = [("2022-09-27", "A", "exit"), ("2022-10-04", "A", "entry"),
                  ("2022-12-19", "B", "entry"), ("2022-10-03", "C", "entry")]
    for d, s, side in pine_cases:
        row = ind[ind["date_s"] == d]
        ok = len(row) == 1 and row.iloc[0][f"sig{s}"] == side and d in pine
        print(("PASS" if ok else "FAIL"), f"Pine 확인표 {s} {side} {d}")
        if not ok:
            fails.append(f"pine-{s}-{d}")

    # 최신봉 신호 현황 (전 종목·전 전략)
    log.append("\n## 최신봉 신호 현황")
    for exp, files in (("exp002", [("SATL", "indicators_satl.csv")]),
                       ("exp004", [("005930.KS", "indicators_005930KS.csv"),
                                   ("000660.KS", "indicators_000660KS.csv")])):
        for sym, f in files:
            d = pd.read_csv(ROOT / "results" / exp / f).tail(5)
            last = d.iloc[-1]
            sigs = " ".join(f"{s}:{last[f'sig{s}']}" for s in "ABC")
            log.append(f"- {sym} {last['date']} 종가 {last['close']} → {sigs}")
            n = len(d[d[[f'sig{s}' for s in 'ABC']].ne('none').any(axis=1)])
            log.append(f"  (최근 5봉 중 신호 {n}봉)")
    log.append("\n- 위 스냅샷이 다음 검증의 포워드 기준. 데이터는 수집 시점(yfinance) 기준이며 실시간이 아니다.")

    (ROOT / "results" / f"live_check_{today}.md").write_text("\n".join(log) + "\n")
    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
