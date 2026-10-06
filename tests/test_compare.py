"""Tests for Phase 4: Fair Comparison (PY-08 scenario, PY-09 comparison).

Oracles:

- Hand-computed equity on a 5-bar series (independent arithmetic).
- Legacy ``scripts/backtest_p4.py::simulate`` parity at zero cost: the lab
  scenario runner must reproduce the published baseline bit-for-bit when no
  costs are charged.
- FeeLedger invariants under commission / sell-tax / slippage.
- Same-condition enforcement (unknown dates, mismatched calendars raise).

Run: ``cd <repo> && python -m pytest tests/test_compare.py -v``
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from lab.compare import (
    ScenarioConfig,
    buy_and_hold_events,
    compare,
    run_scenario,
    scenario_metrics,
    to_markdown,
)

DATES = [f"2026-01-0{d}" for d in range(1, 6)]
OPENS = [100.0, 102.0, 104.0, 103.0, 105.0]
CLOSES = [101.0, 103.0, 102.0, 104.0, 106.0]
EVENTS = {DATES[1]: ("buy", 102.0), DATES[3]: ("sell", 103.0)}

QTY = 10_000.0 / 102.0  # all-in zero-cost buy quantity


def _legacy_simulate():
    path = Path(__file__).resolve().parent.parent / "scripts" / "backtest_p4.py"
    spec = importlib.util.spec_from_file_location("backtest_p4", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.simulate


class TestScenarioZeroCost:
    def test_hand_computed_equity(self) -> None:
        r = run_scenario(DATES, OPENS, CLOSES, EVENTS, ScenarioConfig("T"))
        assert r.equity == pytest.approx(
            [10_000.0, QTY * 103.0, 10_000.0, QTY * 103.0, QTY * 103.0]
        )
        assert r.held == [0, 1, 1, 0, 0]

    def test_legacy_parity(self) -> None:
        simulate = _legacy_simulate()
        eq, held = simulate(DATES, OPENS, CLOSES, EVENTS)
        r = run_scenario(DATES, OPENS, CLOSES, EVENTS, ScenarioConfig("T"))
        assert r.equity == pytest.approx(eq)
        assert r.held == held

    def test_round_trip_stats(self) -> None:
        r = run_scenario(DATES, OPENS, CLOSES, EVENTS, ScenarioConfig("T"))
        assert len(r.round_trips) == 1
        trip = r.round_trips[0]
        assert trip["entry_date"] == DATES[1]
        assert trip["exit_date"] == DATES[3]
        assert trip["pnl"] == pytest.approx(QTY * 103.0 - 10_000.0)
        assert trip["hold_bars"] == 2
        assert r.cost_summary["total_costs"] == 0.0


class TestScenarioCosts:
    def test_commission_accounting(self) -> None:
        cfg = ScenarioConfig("C", commission_bps=100.0)  # 1 %
        r = run_scenario(DATES, OPENS, CLOSES, EVENTS, cfg)
        qty = 10_000.0 / (102.0 * 1.01)
        buy_comm = qty * 102.0 * 0.01
        sell_comm = qty * 103.0 * 0.01
        assert r.cost_summary["commission_total"] == pytest.approx(buy_comm + sell_comm)
        assert r.cost_summary["sell_tax_total"] == 0.0
        assert r.equity[-1] == pytest.approx(qty * 103.0 * 0.99)
        assert r.fills[0].quantity == pytest.approx(qty)

    def test_sell_tax_only_on_sell(self) -> None:
        cfg = ScenarioConfig("X", sell_tax_bps=30.0)
        r = run_scenario(DATES, OPENS, CLOSES, EVENTS, cfg)
        qty = 10_000.0 / 102.0
        assert r.cost_summary["commission_total"] == 0.0
        assert r.cost_summary["sell_tax_total"] == pytest.approx(qty * 103.0 * 0.003)
        assert r.equity[-1] == pytest.approx(qty * 103.0 * (1 - 0.003))

    def test_slippage_adjusts_price(self) -> None:
        cfg = ScenarioConfig("S", slippage_bps=100.0)  # 1 %
        r = run_scenario(DATES, OPENS, CLOSES, EVENTS, cfg)
        buy_qty = 10_000.0 / (102.0 * 1.01)
        assert r.fills[0].quantity == pytest.approx(buy_qty)
        assert r.cost_summary["slippage_cost_total"] == pytest.approx(
            buy_qty * 102.0 * 0.01 + buy_qty * 103.0 * 0.01,
        )


class TestScenarioGuards:
    def test_unknown_event_date_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown dates"):
            run_scenario(DATES, OPENS, CLOSES, {"2099-01-01": ("buy", 1.0)},
                         ScenarioConfig("T"))

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="length mismatch"):
            run_scenario(DATES, OPENS, CLOSES[:-1], EVENTS, ScenarioConfig("T"))

    def test_repeat_signals_skipped(self) -> None:
        events = dict(EVENTS)
        events[DATES[2]] = ("buy", 104.0)  # already held: skipped
        events[DATES[4]] = ("sell", 105.0)  # already flat: skipped
        r = run_scenario(DATES, OPENS, CLOSES, events, ScenarioConfig("T"))
        assert [f.date for f in r.fills] == [DATES[1], DATES[3]]

    def test_buy_and_hold_helper(self) -> None:
        assert buy_and_hold_events(DATES, OPENS) == {DATES[1]: ("buy", 102.0)}
        with pytest.raises(ValueError):
            buy_and_hold_events(["2026-01-01"], [100.0])


class TestComparison:
    def _two(self):
        a = run_scenario(DATES, OPENS, CLOSES, EVENTS, ScenarioConfig("A"))
        bh = run_scenario(DATES, OPENS, CLOSES,
                          buy_and_hold_events(DATES, OPENS), ScenarioConfig("BH"))
        return compare({"A": a, "BH": bh})

    def test_hand_computed_metrics(self) -> None:
        r = run_scenario(DATES, OPENS, CLOSES, EVENTS, ScenarioConfig("A"))
        assert scenario_metrics(r.equity, r.held) == {
            "net_ret_pct": 0.98,
            "mdd_pct": -0.97,
            "exposure_pct": 40.0,
        }

    def test_compare_trades_and_halves(self) -> None:
        table = self._two()
        assert table["A"]["trades"]["completed"] == 1
        assert table["A"]["trades"]["open"] == 0
        assert table["A"]["trades"]["win_rate_pct"] == 100.0
        assert table["A"]["trades"]["avg_pnl"] == pytest.approx(QTY * 103.0 - 10_000.0, abs=0.01)
        assert table["BH"]["trades"] == {
            "completed": 0, "open": 1,
            "win_rate_pct": "-", "avg_pnl": "-", "avg_hold_bars": "-",
        }
        # h2 rebased at mid: BH h2 = (close[-1]/close[mid] - 1) with zero cost
        assert table["BH"]["h2"]["net_ret_pct"] == round(
            (106.0 / 102.0 - 1) * 100, 2)

    def test_calendar_mismatch_raises(self) -> None:
        a = run_scenario(DATES, OPENS, CLOSES, EVENTS, ScenarioConfig("A"))
        other_dates = [f"2026-02-0{d}" for d in range(1, 6)]
        b = run_scenario(other_dates, OPENS, CLOSES, {}, ScenarioConfig("B"))
        with pytest.raises(ValueError, match="differs"):
            compare({"A": a, "B": b})

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            compare({})

    def test_markdown_shape(self) -> None:
        md = to_markdown(self._two(), "2026-01-01~2026-01-05", order=["A", "BH"])
        assert "| A | 0.98 | -0.97 | 40.0 | 1 | 0 |" in md
        assert "| BH |" in md and "h1_net%" in md
