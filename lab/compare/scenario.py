"""PY-08: Scenario results and cost accounting.

A *scenario* is one strategy's event sequence (``{date: (side, price)}``)
executed over a shared evaluation bar series.  The scenario runner routes
every fill through :class:`FeeLedger` and :class:`PositionTracker`, so the
equity curve and the cost breakdown come from the same accounting engine —
there is no parallel bookkeeping path (unlike the legacy
``scripts/backtest_p4.py::simulate``, which re-implements the arithmetic
inline).

Execution semantics (match the legacy contract):

- Buy is all-in: ``qty = cash / (eff * (1 + commission_rate))`` where
  ``eff`` is the slippage-adjusted price.  At zero cost this reduces to
  ``qty = cash / price``, bit-identical to the legacy simulator.
- Sell is all-out (entire share balance).
- A buy with no cash, or a sell with no shares, is skipped — the same
  silent-skip rule the legacy simulator uses for repeated signals.
- Unknown event dates (not on the evaluation calendar) raise
  ``ValueError`` instead of being silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lab.accounting.fees import FeeLedger
from lab.accounting.position import PositionTracker


@dataclass
class ScenarioConfig:
    """Cost and capital parameters for one scenario run."""

    scenario_id: str
    initial_capital: float = 10_000.0
    commission_bps: float = 0.0
    sell_tax_bps: float = 0.0
    slippage_bps: float = 0.0


@dataclass
class Fill:
    """One executed fill (buy or sell)."""

    date: str
    side: str
    price: float
    quantity: float
    commission: float
    sell_tax: float


@dataclass
class ScenarioResult:
    """Complete outcome of one scenario run."""

    scenario_id: str
    config: ScenarioConfig
    dates: list[str]
    equity: list[float]
    held: list[int]
    fills: list[Fill] = field(default_factory=list)
    cost_summary: dict[str, Any] = field(default_factory=dict)
    round_trips: list[dict[str, Any]] = field(default_factory=list)

    @property
    def final_equity(self) -> float:
        """Last equity value."""
        return self.equity[-1]

    @property
    def is_held(self) -> bool:
        """True when the scenario ends with an open position."""
        return bool(self.held[-1])


def buy_and_hold_events(dates: list[str], opens: list[float]) -> dict[str, tuple[str, float]]:
    """Return the B&H event map: full-size buy at the second bar's open.

    Mirrors the legacy contract — B&H buys at ``dates[1]`` (the first
    evaluation bar's *next* open) and holds through the end.
    """
    if len(dates) < 2:
        raise ValueError(f"buy-and-hold needs at least 2 bars, got {len(dates)}")
    return {dates[1]: ("buy", opens[1])}


def run_scenario(
    dates: list[str],
    opens: list[float],
    closes: list[float],
    events: dict[str, tuple[str, float]],
    config: ScenarioConfig,
) -> ScenarioResult:
    """Execute one scenario over the evaluation bars.

    Parameters
    ----------
    dates, opens, closes:
        Evaluation calendar (ISO date strings) with per-bar open
        (execution price reference) and close (valuation price).
    events:
        ``{date: (side, price)}`` with ``side`` in ``{"buy", "sell"}``.
    config:
        Capital and cost parameters.

    Returns
    -------
    ScenarioResult
        Daily equity curve, held flags, fills, fee-ledger cost summary,
        and per-round-trip pnl/holding stats.
    """
    if not dates:
        raise ValueError("dates must not be empty")
    if not (len(dates) == len(opens) == len(closes)):
        raise ValueError(
            f"dates/opens/closes length mismatch: "
            f"{len(dates)}/{len(opens)}/{len(closes)}"
        )
    unknown = [d for d in events if d not in set(dates)]
    if unknown:
        raise ValueError(f"events on unknown dates: {unknown}")

    ledger = FeeLedger(
        commission_bps=config.commission_bps,
        sell_tax_bps=config.sell_tax_bps,
        slippage_bps=config.slippage_bps,
    )
    tracker = PositionTracker(initial_capital=config.initial_capital)

    comm_rate = ledger.commission_rate
    slip_rate = ledger.slippage_rate

    equity: list[float] = []
    held: list[int] = []
    fills: list[Fill] = []
    round_trips: list[dict[str, Any]] = []
    entry_cash = 0.0
    entry_date = ""

    for date, raw_open, close in zip(dates, opens, closes):
        if date in events:
            side, raw_price = events[date]
            if side == "buy" and tracker.cash > 0:
                eff = raw_price * (1.0 + slip_rate)
                quantity = tracker.cash / (eff * (1.0 + comm_rate))
                record = ledger.record_trade(
                    trade_id=f"{config.scenario_id}|{date}|buy",
                    date=date,
                    side="buy",
                    raw_price=raw_price,
                    quantity=quantity,
                )
                entry_cash = tracker.cash
                entry_date = date
                tracker.open_position("buy", raw_price, quantity, date, record)
                fills.append(Fill(date, "buy", raw_price, quantity,
                                  record.commission, record.sell_tax))
            elif side == "sell" and tracker.is_held:
                quantity = tracker.shares
                record = ledger.record_trade(
                    trade_id=f"{config.scenario_id}|{date}|sell",
                    date=date,
                    side="sell",
                    raw_price=raw_price,
                    quantity=quantity,
                )
                tracker.open_position("sell", raw_price, quantity, date, record)
                fills.append(Fill(date, "sell", raw_price, quantity,
                                  record.commission, record.sell_tax))
                round_trips.append({
                    "entry_date": entry_date,
                    "exit_date": date,
                    "pnl": tracker.cash - entry_cash,
                    "hold_bars": dates.index(date) - dates.index(entry_date),
                })
            elif side not in ("buy", "sell"):
                raise ValueError(f"unknown side {side!r} on {date}")

        state = tracker.daily_state(date, close)
        equity.append(state.equity)
        held.append(1 if state.held else 0)

    return ScenarioResult(
        scenario_id=config.scenario_id,
        config=config,
        dates=list(dates),
        equity=equity,
        held=held,
        fills=fills,
        cost_summary=ledger.summarize(),
        round_trips=round_trips,
    )
