"""Tests for Phase 5: Research Validation (PY-10 phase separation).

Oracles: hand-computed segment metrics on the 5-bar series shared with
``tests/test_compare.py``, plus freeze/hash and walk-forward invariants.

Run: ``cd <repo> && python -m pytest tests/test_research.py -v``
"""

from __future__ import annotations

import pytest

from lab.compare import ScenarioConfig, run_scenario
from lab.research import (
    Study,
    evaluation_report,
    freeze_params,
    segment_metrics,
    segment_trades,
    split_calendar,
    walk_forward,
)

DATES = [f"2026-01-0{d}" for d in range(1, 6)]
OPENS = [100.0, 102.0, 104.0, 103.0, 105.0]
CLOSES = [101.0, 103.0, 102.0, 104.0, 106.0]
EVENTS = {DATES[1]: ("buy", 102.0), DATES[3]: ("sell", 103.0)}
BOUNDARY = DATES[3]

QTY = 10_000.0 / 102.0
EQ2 = QTY * 103.0


def _result():
    return run_scenario(DATES, OPENS, CLOSES, EVENTS, ScenarioConfig("A"))


class TestSplitCalendar:
    def test_mid_split(self) -> None:
        sel, eva = split_calendar(DATES, BOUNDARY)
        assert sel == DATES[:3]
        assert eva == DATES[3:]

    def test_holiday_boundary(self) -> None:
        gap = [DATES[0], DATES[1], DATES[3], DATES[4]]
        sel, eva = split_calendar(gap, DATES[2])  # DATES[2] not a trading bar
        assert sel == gap[:2]
        assert eva == gap[2:]

    def test_empty_segments_raise(self) -> None:
        with pytest.raises(ValueError, match="selection empty"):
            split_calendar(DATES, DATES[0])
        with pytest.raises(ValueError, match="evaluation empty"):
            split_calendar(DATES, "2099-01-01")
        with pytest.raises(ValueError):
            split_calendar([], BOUNDARY)


class TestFreeze:
    def test_stable_across_key_order(self) -> None:
        assert freeze_params({"b": 2, "a": 1}) == freeze_params({"a": 1, "b": 2})

    def test_distinguishes_params(self) -> None:
        assert freeze_params({"v": 1.0}) != freeze_params({"v": 1.1})

    def test_numpy_safe(self) -> None:
        import numpy as np
        assert freeze_params({"v": np.float64(1.0)}) == freeze_params({"v": 1.0})

    def test_study_freeze_records(self) -> None:
        s = Study("s1", BOUNDARY, {"volume_ratio": 1.0})
        assert s.frozen_hash == ""
        h = s.freeze()
        assert s.frozen_hash == h == freeze_params({"volume_ratio": 1.0})
        assert s.to_dict()["frozen_hash"] == h


class TestSegments:
    def test_hand_computed_segment_metrics(self) -> None:
        assert segment_metrics(_result(), BOUNDARY) == {
            "selection": {"net_ret_pct": 0.0, "mdd_pct": -0.97, "exposure_pct": 66.7},
            "evaluation": {"net_ret_pct": 0.0, "mdd_pct": 0.0, "exposure_pct": 0.0},
        }

    def test_trip_assignment_by_entry(self) -> None:
        trades = segment_trades(_result(), BOUNDARY)
        assert trades["selection"]["completed"] == 1
        assert trades["selection"]["open"] == 1  # still held at cut
        assert trades["evaluation"]["completed"] == 0
        assert trades["evaluation"]["open"] == 0


class TestEvaluationReport:
    def test_requires_freeze(self) -> None:
        s = Study("s1", BOUNDARY, {"v": 1})
        with pytest.raises(ValueError, match="not frozen"):
            evaluation_report(_result(), s, "anything")

    def test_rejects_stale_hash(self) -> None:
        s = Study("s1", BOUNDARY, {"v": 1})
        stale = s.freeze()
        s.rule_params["v"] = 2  # rules changed: must re-freeze (new study state)
        s.freeze()
        with pytest.raises(ValueError, match="hash mismatch"):
            evaluation_report(_result(), s, stale)

    def test_accepts_frozen_hash(self) -> None:
        s = Study("s1", BOUNDARY, {"v": 1})
        good = s.freeze()
        rep = evaluation_report(_result(), s, good)
        assert rep["metrics"] == {"net_ret_pct": 0.0, "mdd_pct": 0.0, "exposure_pct": 0.0}
        assert rep["trades"]["completed"] == 0
        assert rep["frozen_hash"] == good
        assert rep["boundary"] == BOUNDARY


class TestWalkForward:
    def test_anchored_folds(self) -> None:
        dates = [f"2026-03-{d:02d}" for d in range(1, 11)]
        folds = list(walk_forward(dates, train_bars=4, test_bars=2, step_bars=2))
        assert len(folds) == 3
        assert folds[0] == (dates[:4], dates[4:6])
        assert folds[2] == (dates[:8], dates[8:10])
        for train, test in folds:
            assert train[0] == dates[0]  # anchored
            assert test[0] > train[-1]  # test strictly after train

    def test_too_short_yields_nothing(self) -> None:
        assert list(walk_forward(DATES[:3], 4, 2, 1)) == []

    def test_bad_sizes_raise(self) -> None:
        with pytest.raises(ValueError):
            list(walk_forward(DATES, 0, 2, 1))
