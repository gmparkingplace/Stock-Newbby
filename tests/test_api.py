"""Tests for Phase 6: Consumer Connection (PY-11 export, PY-12 run).

Oracles: consumer key contracts read from ``scripts/serve_dashboard.py``
(``frame``/``lookup``/``backtest``) and ``results/dashboard/index.html``
(mark filtering), plus the real ``results/dashboard/data.js`` when present.

Run: ``cd <repo> && python -m pytest tests/test_api.py -v``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab.api import (
    check_backtest,
    check_dashboard_data,
    check_frame,
    check_marks,
    export_scenario,
    finalize_run,
    scenario_marks,
    verify_run,
)
from lab.compare import (
    ScenarioConfig,
    buy_and_hold_events,
    compare,
    run_scenario,
)
from lab.execution.run_paths import RunPaths, write_run_manifest
from lab.research import Study, evaluation_report

ROOT = Path(__file__).resolve().parent.parent
DATES = [f"2026-01-0{d}" for d in range(1, 6)]
OPENS = [100.0, 102.0, 104.0, 103.0, 105.0]
CLOSES = [101.0, 103.0, 102.0, 104.0, 106.0]
EVENTS = {DATES[1]: ("buy", 102.0), DATES[3]: ("sell", 103.0)}


def _result():
    return run_scenario(DATES, OPENS, CLOSES, EVENTS, ScenarioConfig("A"))


def _frame_payload() -> dict:
    return {
        "candles": [{"time": "2026-01-01", "open": 1.0, "high": 2.0,
                     "low": 0.5, "close": 1.5, "volume": 10}],
        "lines": {"sma20": []},
        "marks": {"F": [{"time": "2026-01-01", "side": "entry", "info": "x"}]},
        "state": [], "fib": {}, "levels": {},
    }


class TestMarks:
    def test_fills_become_entry_exit(self) -> None:
        marks = scenario_marks(_result())
        assert [m["side"] for m in marks["A"]] == ["entry", "exit"]
        assert [m["time"] for m in marks["A"]] == [DATES[1], DATES[3]]
        assert check_marks(marks) == []

    def test_bad_marks_flagged(self) -> None:
        assert check_marks({"A": [{"time": "t", "side": "hold", "info": ""}]}) != []
        assert check_marks({"A": [{"time": "t"}]}) != []
        assert check_marks([]) != []  # type: ignore[arg-type]


class TestConsumerContracts:
    def test_frame_contract(self) -> None:
        assert check_frame(_frame_payload()) == []
        bad = _frame_payload()
        del bad["marks"]
        assert check_frame(bad) != []

    def test_backtest_contract(self) -> None:
        payload = {"symbol": "X", "name": "X",
                   "per": {"F": {"ret": 1.0, "mdd": -2.0, "exposure": 3.0,
                                 "completed": 1, "winrate": 100.0}},
                   "trades": {}, "bh": 0.5, "note": "n"}
        assert check_backtest(payload) == []
        payload["per"]["F"] = {"ret": 1.0}
        assert check_backtest(payload) != []

    def test_real_dashboard_data(self) -> None:
        p = ROOT / "results" / "dashboard" / "data.js"
        if not p.exists():
            pytest.skip("no built dashboard")
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw.split("=", 1)[1].rstrip().rstrip(";"))
        assert check_dashboard_data(data) == []
        assert check_dashboard_data({}) == ["no exps"]


class TestExportRoundTrip:
    def test_scenario_reload(self, tmp_path: Path) -> None:
        r = _result()
        out = export_scenario(r, tmp_path)
        raw = json.loads(out.read_text(encoding="utf-8"))
        assert raw["dates"] == r.dates
        assert raw["equity"] == r.equity
        assert raw["cost_summary"] == r.cost_summary
        assert check_marks(raw["marks"]) == []


def _run_paths(run_dir: Path) -> RunPaths:
    return RunPaths(
        run_id=run_dir.name,
        snapshots_dir=run_dir / "snapshots",
        artifacts_dir=run_dir / "artifacts",
        results_dir=run_dir / "results",
        ledger_dir=run_dir / "ledgers",
        events_dir=run_dir / "events",
        export_dir=run_dir / "export",
        run_manifest_path=run_dir / "run_manifest.json",
    )


class TestFinalize:
    def _finalize(self, run_dir: Path):
        run_dir.mkdir(parents=True, exist_ok=True)  # real runs: create_run()
        paths = _run_paths(run_dir)
        write_run_manifest(paths, {"profile": "test"})
        scenarios = {
            "A": _result(),
            "BH": run_scenario(DATES, OPENS, CLOSES,
                               buy_and_hold_events(DATES, OPENS),
                               ScenarioConfig("BH")),
        }
        table = compare(scenarios)
        study = Study("s1", DATES[3], {"v": 1})
        rep = evaluation_report(scenarios["A"], study, study.freeze())
        summary = finalize_run(paths, scenarios, table,
                               "2026-01-01~2026-01-05", [rep])
        return paths, summary

    def test_finalize_writes_and_summarizes(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "demo_20260101"
        _, summary = self._finalize(run_dir)
        assert summary["scenario_ids"] == ["A", "BH"]
        assert len(summary["frozen_hashes"]) == 1
        assert (run_dir / "export" / "scenarios" / "A.json").exists()
        assert (run_dir / "export" / "comparison.md").exists()
        assert (run_dir / "export" / "evaluation" / "s1_A.json").exists()
        assert (run_dir / "results" / "run_summary.json").exists()

    def test_finalize_rejects_empty(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="nothing to finalize"):
            finalize_run(_run_paths(tmp_path / "r"), {}, {}, "p", [])

    def test_verify_healthy(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "demo_20260101"
        self._finalize(run_dir)
        assert verify_run(run_dir) == []

    def test_verify_problems(self, tmp_path: Path) -> None:
        assert verify_run(tmp_path / "missing") != []
        run_dir = tmp_path / "bad_20260101"
        (run_dir / "export" / "scenarios").mkdir(parents=True)
        (run_dir / "export" / "scenarios" / "A.json").write_text("{broken")
        (run_dir / "export" / "evaluation").mkdir()
        (run_dir / "export" / "evaluation" / "s_A.json").write_text('{"a": 1}')
        problems = verify_run(run_dir)
        assert any("manifest" in p for p in problems)
        assert any("unparsable" in p for p in problems)
        assert any("comparison" in p for p in problems)
        assert any("frozen_hash" in p for p in problems)
