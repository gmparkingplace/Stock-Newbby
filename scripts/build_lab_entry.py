"""lab 런 → 대시보드 연결: exp008 공표 산출물을 lab 회계로 재실행해 data.js에 lab008 엔트리로 추가.

실행: .venv/bin/python scripts/build_lab_entry.py
입력: data/snapshots/exp008/ohlcv.csv + results/exp008/{indicators,trades}_*
출력: results/dashboard/data.js (exp008 엔트리 복사 + marks·performance_md만 교체)

실행 모델 차이(반드시 라벨에 명시): 공표 exp008 = 건당 1% 리스크·2ATR sizing,
lab008 = 동일 비용(수수료 1.5bp·매도세 30bp)·자본 1000만원의 전액/전량.
캔들·지표·해설은 동일 스냅샷이라 exp008 것을 그대로 공유한다.
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lab.api import check_dashboard_data, scenario_marks  # noqa: E402
from lab.compare import (  # noqa: E402
    ScenarioConfig,
    buy_and_hold_events,
    compare,
    run_scenario,
    to_markdown,
)
from lab.compare.performance import trade_stats  # noqa: E402
from lab.compat import (  # noqa: E402
    bars_from_snapshot,
    eval_dates_from_indicators,
    events_from_trades_csv,
)

RES = ROOT / "results" / "exp008"
SNAP = ROOT / "data" / "snapshots" / "exp008" / "ohlcv.csv"
DATA_JS = ROOT / "results" / "dashboard" / "data.js"
TARGETS = {"005930.KS": "005930KS", "000660.KS": "000660KS",
           "AAPL": "AAPL", "NVDA": "NVDA", "SATL": "SATL",
           "^KS11": "KS11", "^KQ11": "KQ11", "QQQ": "QQQ", "SPY": "SPY",
           "069500.KS": "069500KS", "091160.KS": "091160KS",
           "XLK": "XLK", "IWM": "IWM", "ITA": "ITA"}
STRATS = ("A", "B", "C", "F")
CAPITAL = 10_000_000.0
COSTS = {"commission_bps": 1.5, "sell_tax_bps": 30.0, "slippage_bps": 0.0}


def run_symbol(sym: str, stem: str) -> tuple[dict, dict]:
    """한 종목의 lab 시나리오 실행 → (scenarios, comparison table)."""
    eval_dates = eval_dates_from_indicators(RES / f"indicators_{stem}.csv")
    dates, opens, closes = bars_from_snapshot(SNAP, sym, eval_dates)
    scenarios = {}
    for s in STRATS:
        events = events_from_trades_csv(RES / f"trades_{s}_{stem}.csv")
        cfg = ScenarioConfig(f"{stem}_{s}", CAPITAL, **COSTS)
        scenarios[s] = run_scenario(dates, opens, closes, events, cfg)
    scenarios["BH"] = run_scenario(
        dates, opens, closes, buy_and_hold_events(dates, opens),
        ScenarioConfig(f"{stem}_BH", CAPITAL, **COSTS))
    return scenarios, compare(scenarios)


def main() -> None:
    before = DATA_JS.stat().st_size
    raw = DATA_JS.read_text(encoding="utf-8")
    prefix = "const DASHBOARD_DATA = "
    assert raw.startswith(prefix) and raw.rstrip().endswith(";"), "data.js 형식 변경됨"
    data = json.loads(raw[len(prefix):].rstrip().rstrip(";"))

    base = next(e for e in data["exps"] if e["id"] == "exp008")
    entry = copy.deepcopy(base)
    entry["id"] = "lab008"
    entry["label"] = ("lab 전액/전량 런 (exp008 동일 비용·자본, 1%리스크 아님 — "
                      "수수료 1.5bp·매도세 30bp·자본 1000만원)")
    md_parts = [f"# lab008 (비용·자본 exp008과 동일, 전액/전량 집행)",
                "- 공표 exp008(1%리스크 sizing)와 직접 비교 불가. lab 회계 기준선.",
                ""]
    for sym, stem in TARGETS.items():
        scenarios, table = run_symbol(sym, stem)
        for s, r in scenarios.items():
            marks = scenario_marks(r)[r.scenario_id]
            if s in entry["symbols"][sym]["marks"]:
                entry["symbols"][sym]["marks"][s] = marks
        md_parts.append(to_markdown(
            table, f"{sym} {scenarios['A'].dates[0]}~{scenarios['A'].dates[-1]}",
            order=[*STRATS, "BH"]).replace("# Performance comparison",
                                            f"## {sym}"))
        n = {s: len(scenarios[s].fills) for s in scenarios}
        t = {s: trade_stats(scenarios[s])["completed"] for s in STRATS}
        print(f"{sym}: bars={len(scenarios['A'].dates)} fills={n} done={t}")

    entry["performance_md"] = "\n".join(md_parts)
    data["exps"] = [e for e in data["exps"] if e["id"] != "lab008"] + [entry]
    problems = check_dashboard_data(data)
    assert not problems, problems
    DATA_JS.write_text(prefix + json.dumps(data, ensure_ascii=False) + ";",
                       encoding="utf-8")
    after = DATA_JS.stat().st_size
    print(f"data.js: {before // 1024}KB -> {after // 1024}KB (+{(after - before) // 1024}KB)")


if __name__ == "__main__":
    main()
