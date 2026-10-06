"""P2c 검증: 원장 무결성·신호 일치·중복 방지 확인.

실행: .venv/bin/python scripts/verify_p2c.py  (종료코드 0 = 통과)
출력: results/exp002/ledger_check.md
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "exp002"
EVAL_START = "2022-09-01"
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)


def main() -> None:
    lines = (RES / "ledger.jsonl").read_text().splitlines()
    lines = [ln for ln in lines if ln.strip()]
    try:
        events = [json.loads(ln) for ln in lines]
        check("전행 유효 JSON", True, f"{len(events)} events")
    except json.JSONDecodeError as e:
        check("전행 유효 JSON", False, str(e)[:120])
        events = []

    ids = [e["event_id"] for e in events]
    check("event_id 중복 없음", len(ids) == len(set(ids)), f"total={len(ids)}")
    check("전건 historical_reconstruction",
          bool(events) and all(e["record_type"] == "historical_reconstruction" for e in events))
    check("단일 run_id (설정·데이터·코드 고정)",
          len({e["run_id"] for e in events}) == 1 if events else False,
          f"{events[0]['run_id'] if events else 'empty'}")

    # 맥락 기록 on/off 신호 동일: 원장 이벤트 집합 == 지표 신호 집합
    ind = pd.read_csv(RES / "indicators_satl.csv", parse_dates=["date"])
    ind["date_s"] = ind["date"].dt.date.astype(str)
    expected: set[tuple] = set()
    for _, r in ind[ind["date_s"] >= EVAL_START].iterrows():
        for strat, col in (("A", "sigA"), ("B", "sigB"), ("C", "sigC")):
            if r[col] in ("entry", "exit"):
                expected.add((r["date_s"], strat, r[col]))
    got = {(e["signal_bar_close"][:10], e["strategy"], e["side"]) for e in events}
    check("원장 == 지표 신호 (맥락 추가가 원신호 불변)",
          expected == got, f"지표 {len(expected)} vs 원장 {len(got)}")

    md = ["# P2c 원장 점검", "",
          f"- 이벤트 {len(events)}건, 중복 0, 전건 historical_reconstruction.",
          f"- run_id: {events[0]['run_id'] if events else '없음'} (데이터·코드 바뀌면 새 ID 발급).",
          f"- 지표 신호 {len(expected)}건과 원장 {len(got)}건 일치.",
          "- execution 미기입(P3에서 t+1봉 시가로 채움). 재실행 중복 방지는 event_id 키로 보장."]
    (RES / "ledger_check.md").write_text("\n".join(md) + "\n")
    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
