"""Regression tests for PY-06 review fixes (spec: work-items PY-03/PY-05/PY-06).

- clean() must map NaN/Inf/numpy types (spec PY-05: "NaN·무한대·numpy 타입을 포함").
- code_hash() must be stable when the tree is relocated (spec PY-06: run identification).
- PositionTracker must not double-charge slippage (spec PY-03: unify cost definitions).
- to_list() must return copies (docstring contract).
- LotManager.remove_quantity must be FIFO with pro-rata proceeds (spec PY-04 lots).

Run: ``cd <repo> && python -m pytest tests/test_review_fixes.py -v``
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from lab.accounting.fees import FeeLedger
from lab.accounting.lots import LotManager
from lab.accounting.position import PositionTracker
from lab.ledger.event import EventLedger, ExecutionEvent, SignalEvent, clean
from lab.ledger.manifest import code_hash


class TestCleanNonFinite:
    def test_inf_to_none(self) -> None:
        import numpy as np
        assert clean(float("inf")) is None
        assert clean(float("-inf")) is None
        assert clean(np.inf) is None
        assert clean(np.float64("-inf")) is None

    def test_ndarray_to_list(self) -> None:
        import numpy as np
        out = clean(np.array([1.0, float("nan")]))
        assert out == [1.0, None]

    def test_nested(self) -> None:
        import numpy as np
        d = {"a": [np.float64(2.0), float("inf")], "b": {"c": np.int64(3)}}
        assert clean(d) == {"a": [2.0, None], "b": {"c": 3}}

    def test_ledger_persists_strict_json(self, tmp_path: Path) -> None:
        led = EventLedger(tmp_path / "s.jsonl", tmp_path / "e.jsonl")
        sig = SignalEvent(
            event_id="r|S|T|2026-01-15|entry",
            run_id="r",
            scenario_id="S",
            symbol="T",
            strategy="A",
            rule_version="v1",
            signal_date="2026-01-15",
            signal_time="2026-01-15T15:30:00+09:00",
            side="entry",
            reason_code="X",
            reason_desc="x",
            indicator_now={"rsi_14": float("inf"), "arr": [1.0, 2.0]},
            signal_price=100.0,
        )
        assert led.append_signal(sig) is True
        raw = (tmp_path / "s.jsonl").read_text(encoding="utf-8")
        assert "Infinity" not in raw
        d = json.loads(raw)
        assert d["indicator_now"]["rsi_14"] is None


class TestCodeHashRelocation:
    def test_stable_across_copy(self, tmp_path: Path) -> None:
        ROOT = Path(__file__).resolve().parent.parent
        h1 = code_hash(dirs=[ROOT / "lab"], deps={"numpy": "2.5.2"})
        dst = tmp_path / "copy"
        shutil.copytree(ROOT / "lab", dst / "lab")
        h2 = code_hash(dirs=[dst / "lab"], deps={"numpy": "2.5.2"})
        assert h1 == h2

    def test_distinguishes_trees(self) -> None:
        ROOT = Path(__file__).resolve().parent.parent
        h_lab = code_hash(dirs=[ROOT / "lab"], deps={"numpy": "2.5.2"})
        h_tests = code_hash(dirs=[ROOT / "tests"], deps={"numpy": "2.5.2"})
        assert h_lab != h_tests


class TestSlippageSymmetry:
    def test_round_trip_same_price(self) -> None:
        fl = FeeLedger(commission_bps=0.0, sell_tax_bps=0.0, slippage_bps=100.0)
        rb = fl.record_trade("T", "2026-01-01", "buy", 100.0, 10.0)
        rs = fl.record_trade("T", "2026-01-02", "sell", 100.0, 10.0)
        pt = PositionTracker(initial_capital=100000.0)
        pt.open_position("buy", 100.0, 10.0, "2026-01-01", rb)
        # Buy pays the slippage-adjusted price exactly once (no double charge).
        assert pt.cash == pytest.approx(100000.0 - 10.0 * rb.effective_price)
        pt.open_position("sell", 100.0, 10.0, "2026-01-02", rs)
        # Symmetric cost: drag is exactly the bid/ask slippage spread.
        assert pt.cash == pytest.approx(100000.0 - (10.0 * 101.0 - 10.0 * 99.0))
        assert pt.shares == 0.0


class TestToListCopies:
    def test_fee_ledger_isolated(self) -> None:
        fl = FeeLedger(commission_bps=10.0, sell_tax_bps=0.0, slippage_bps=0.0)
        fl.record_trade("T1", "2026-01-01", "buy", 100.0, 1.0)
        fl.to_list()[0]["commission"] = 999.0
        assert fl.summarize()["commission_total"] != pytest.approx(999.0)

    def test_position_tracker_isolated(self) -> None:
        pt = PositionTracker(initial_capital=1000.0)
        pt.daily_state("2026-01-01", 100.0)
        pt.to_list()[0]["cash"] = -1.0
        assert pt.to_list()[0]["cash"] == 1000.0

    def test_lot_manager_isolated(self) -> None:
        lm = LotManager()
        lm.add_lot(100.0, 10.0, 1.0, "2026-01-01")
        lots, _ = lm.to_list()
        lots[0]["quantity"] = 0.0
        assert lm.total_shares() == 10.0


class TestLotFifo:
    def test_multi_lot_proceeds_split(self) -> None:
        lm = LotManager()
        lm.add_lot(100.0, 100.0, 0.0, "2026-01-01")
        lm.add_lot(110.0, 100.0, 0.0, "2026-01-02")
        out = lm.remove_quantity(150.0, "2026-01-03", 0.0, 150.0 * 105.0)
        assert len(out) == 2
        assert sum(r.proceeds for r in out) == pytest.approx(150.0 * 105.0)
        assert out[0].proceeds == pytest.approx(100.0 * 105.0)
        assert out[1].proceeds == pytest.approx(50.0 * 105.0)
        assert lm.total_shares() == pytest.approx(50.0)

    def test_over_removal_raises(self) -> None:
        lm = LotManager()
        lm.add_lot(100.0, 10.0, 0.0, "2026-01-01")
        with pytest.raises(ValueError):
            lm.remove_quantity(11.0, "2026-01-02", 0.0, 1100.0)
