"""lab.compare — Fair Comparison (Phase 4: PY-08/PY-09)."""

from __future__ import annotations

from lab.compare.performance import (
    compare,
    max_drawdown,
    scenario_metrics,
    to_markdown,
    trade_stats,
)
from lab.compare.scenario import (
    Fill,
    ScenarioConfig,
    ScenarioResult,
    buy_and_hold_events,
    run_scenario,
)

__all__ = [
    "Fill",
    "ScenarioConfig",
    "ScenarioResult",
    "buy_and_hold_events",
    "run_scenario",
    "compare",
    "max_drawdown",
    "scenario_metrics",
    "to_markdown",
    "trade_stats",
]
